"""Read-only compatibility checks and lossless, non-overwriting archive migration."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from _records import read_json, fingerprint, loads_json
from _static import emit
from _versions import annotate, compatibility, require_readable


def unwrap(record):
    if not isinstance(record, dict) or record.get('kind') != 'archived_record_envelope':
        return record
    if record.get('schema_version') != 1:
        raise ValueError('Unsupported archive envelope format')
    content = {k: v for k, v in record.items() if k != 'envelope_sha256'}
    if record.get('envelope_sha256') != fingerprint(content):
        raise ValueError('Archive envelope fingerprint mismatch')
    try:
        raw = base64.b64decode(record['original_bytes_base64'], validate=True)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('Invalid archived original bytes') from exc
    if hashlib.sha256(raw).hexdigest() != record.get('original_file_sha256'):
        raise ValueError('Archived original byte fingerprint mismatch')
    original = loads_json(raw.decode('utf-8-sig'))
    if isinstance(original, dict) and original.get('kind') == 'archived_record_envelope':
        raise ValueError('Nested archive envelopes are not supported')
    return original


def check(path):
    record = read_json(path)
    original = unwrap(record)
    result = compatibility(original)
    if isinstance(original, dict) and original.get('kind') == 'experiment_manifest':
        if original.get('manifest_sha256') != fingerprint({k: v for k, v in original.items() if k != 'manifest_sha256'}):
            raise ValueError('Manifest fingerprint mismatch')
    elif isinstance(original, dict) and original.get('kind') == 'run_ledger':
        if original.get('record_sha256') != fingerprint({k: v for k, v in original.items() if k != 'record_sha256'}):
            raise ValueError('Run ledger fingerprint mismatch')
    return {**result, 'archived': record is not original, 'input_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'files_modified': False, 'analysis_reexecuted': False}


def migrate(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError('Migration must preserve the source; choose a new output path')
    raw = source.read_bytes()
    record = loads_json(raw.decode('utf-8-sig'))
    if isinstance(record, dict) and record.get('kind') == 'archived_record_envelope':
        raise ValueError('Already archived; do not wrap again')
    require_readable(record)
    check(source)
    envelope = annotate({'schema_version': 1, 'kind': 'archived_record_envelope',
                         'original_file_sha256': hashlib.sha256(raw).hexdigest(),
                         'original_bytes_base64': base64.b64encode(raw).decode('ascii'),
                         'original_compatibility': compatibility(record),
                         'migration': 'lossless_archive_only', 'original_semantics_upgraded': False,
                         'next_step': 'Re-run audit with original manifests under current rules; never rewrite old CSV provenance or substitute current source for historical source.'})
    envelope['envelope_sha256'] = fingerprint(envelope)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as handle:
        json.dump(envelope, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    return {'output': str(destination), 'original_preserved': True, 'semantics_upgraded': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('check')
    c.add_argument('record', type=Path)
    m = sub.add_parser('migrate')
    m.add_argument('record', type=Path)
    m.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        result = check(args.record) if args.command == 'check' else migrate(args.record, args.out)
        emit(result, None)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        p.error(str(exc))
    if args.command == 'check' and result['status'] != 'supported_current':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
