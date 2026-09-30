"""Freeze explicit behavior inputs, append reviewed reports, and select reruns.

This independent schema checks provenance, never evaluates research conclusions or
invokes an evaluator, project, model, Git, or training entrypoint.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


SCHEMA_VERSION = 1
NORMALIZATION = 'crlf_and_cr_to_lf'
VERDICTS = {'passed', 'failed', 'needs_review'}
SOURCE_MATCHES = {'confirmed', 'unknown', 'mismatch'}


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                     allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'Invalid {label} fields')


def _header(value, kind, fields):
    _keys(value, {'kind', 'schema_version', *fields}, kind)
    if value['kind'] != kind or type(value['schema_version']) is not int or value['schema_version'] != SCHEMA_VERSION:
        raise ValueError(f'Unsupported {kind} format')


def _identifier(value, label, tag=False):
    pattern = r'[a-z][a-z0-9_.-]{0,63}' if tag else r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'Invalid {label}; use a public identifier, not a path')
    return value


def _sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(f'Invalid {label}')


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            '\x00' in value or any(ord(c) < 32 or c in '<>"|?*' for c in value)):
        raise ValueError('File paths must be canonical relative POSIX paths')
    path = PurePosixPath(value)
    parts = value.split('/')
    if path.is_absolute() or PureWindowsPath(value).drive or any(p in {'', '.', '..'} for p in parts):
        raise ValueError('File paths must stay within the input root')
    # Apply portable Windows rules even on a case-sensitive POSIX filesystem.
    # Win32 can normalize trailing dots/spaces into another existing path.
    if any(p.endswith(('.', ' ')) for p in parts):
        raise ValueError('File path components cannot end with a dot or space')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    if any(p.split('.')[0].upper() in reserved for p in parts):
        raise ValueError('File paths cannot contain Windows reserved device names')
    return value


def _paths(values, label, nonempty=False):
    if not isinstance(values, list) or (nonempty and not values):
        raise ValueError(f'Invalid {label} list')
    result = [_relative(p) for p in values]
    if len({p.casefold() for p in result}) != len(result):
        raise ValueError(f'Duplicate or case-colliding {label} paths')
    return sorted(result)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f'Invalid JSON constant: {value}')

    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def _file(root, relative):
    path = root.joinpath(*PurePosixPath(_relative(relative)).parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Input must resolve to a file within the input root')
    return path


def snapshot(root, files):
    """Hash only the explicit relative files; line endings normalize to LF."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Input root must be a directory')
    entries = []
    for relative in _paths(files, 'snapshot', nonempty=True):
        raw = _file(root, relative).read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        entries.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'normalized_bytes': len(raw)})
    return {'kind': 'behavior_file_snapshot', 'schema_version': SCHEMA_VERSION,
            'normalization': NORMALIZATION, 'files': entries, 'files_sha256': fingerprint(entries)}


def validate_snapshot(value):
    _header(value, 'behavior_file_snapshot', {'normalization', 'files', 'files_sha256'})
    if value['normalization'] != NORMALIZATION or not isinstance(value['files'], list) or not value['files']:
        raise ValueError('Invalid snapshot normalization or files')
    paths = []
    for entry in value['files']:
        _keys(entry, {'path', 'sha256', 'normalized_bytes'}, 'snapshot file')
        paths.append(_relative(entry['path']))
        _sha(entry['sha256'], 'file sha256')
        if type(entry['normalized_bytes']) is not int or entry['normalized_bytes'] < 0:
            raise ValueError('Invalid normalized byte count')
    if paths != _paths(paths, 'snapshot') or value['files_sha256'] != fingerprint(value['files']):
        raise ValueError('Snapshot set fingerprint or canonical order mismatch')
    return value


def validate_index(value):
    _header(value, 'behavior_case_index', {'shared_source_paths', 'cases'})
    shared = _paths(value['shared_source_paths'], 'shared source')
    if not isinstance(value['cases'], list) or not value['cases']:
        raise ValueError('Case index must contain cases')
    ids = []
    for case in value['cases']:
        _keys(case, {'case_id', 'rule_tags', 'request_path', 'fixture_paths', 'source_paths'}, 'case')
        ids.append(_identifier(case['case_id'], 'case id'))
        if not isinstance(case['rule_tags'], list) or not case['rule_tags']:
            raise ValueError('Each case requires rule tags')
        tags = [_identifier(tag, 'rule tag', tag=True) for tag in case['rule_tags']]
        if len(set(tags)) != len(tags):
            raise ValueError('Duplicate rule tags')
        request = _relative(case['request_path'])
        fixtures = _paths(case['fixture_paths'], 'fixture')
        sources = _paths(case['source_paths'], 'source')
        _paths([request, *fixtures], 'case inputs', nonempty=True)
        _paths([*shared, *sources], 'case sources', nonempty=True)
        if {p.casefold() for p in [request, *fixtures]} & {p.casefold() for p in [*shared, *sources]}:
            raise ValueError('Inputs and skill sources must be separate')
    if len({i.casefold() for i in ids}) != len(ids):
        raise ValueError('Duplicate or case-colliding case ids')
    return value


def _case(index, case_id):
    validate_index(index)
    for case in index['cases']:
        if case['case_id'] == case_id:
            return case
    raise ValueError('Unknown case id')


def _definition(index, case):
    return {'case_id': case['case_id'], 'rule_tags': sorted(case['rule_tags']),
            'request_path': case['request_path'], 'fixture_paths': sorted(case['fixture_paths']),
            'source_paths': sorted([*index['shared_source_paths'], *case['source_paths']])}


def case_snapshot(index, case_id, root):
    """Freeze the indexed request/fixtures and the explicit skill source scope."""
    case = _case(index, case_id)
    definition = _definition(index, case)
    root = Path(root).resolve(strict=True)
    input_paths = [_file(root, p) for p in [case['request_path'], *case['fixture_paths']]]
    source_paths = [_file(root, p) for p in definition['source_paths']]
    # resolve() covers internal symlinks; samefile() also detects hard links.
    # Content equality alone is allowed and does not imply a physical alias.
    if any(a == b or a.samefile(b) for a in input_paths for b in source_paths):
        raise ValueError('Inputs and skill sources cannot alias the same physical file')
    value = {'kind': 'behavior_case_snapshot', 'schema_version': SCHEMA_VERSION,
             'case_id': case_id, 'case_definition_sha256': fingerprint(definition),
             'input_snapshot': snapshot(root, [case['request_path'], *case['fixture_paths']]),
             'source_snapshot': snapshot(root, definition['source_paths'])}
    value['snapshot_sha256'] = fingerprint(value)
    return value


def validate_case_snapshot(value):
    _header(value, 'behavior_case_snapshot', {'case_id', 'case_definition_sha256',
                                            'input_snapshot', 'source_snapshot', 'snapshot_sha256'})
    _identifier(value['case_id'], 'case id')
    _sha(value['case_definition_sha256'], 'case definition sha256')
    validate_snapshot(value['input_snapshot'])
    validate_snapshot(value['source_snapshot'])
    inputs = {e['path'].casefold() for e in value['input_snapshot']['files']}
    sources = {e['path'].casefold() for e in value['source_snapshot']['files']}
    if inputs & sources:
        raise ValueError('Inputs and skill sources must be separate')
    if value['snapshot_sha256'] != fingerprint({k: v for k, v in value.items() if k != 'snapshot_sha256'}):
        raise ValueError('Case snapshot fingerprint mismatch')
    return value


def _revision(tested_commit=None, base_commit=None, dirty=None):
    if tested_commit is not None:
        if base_commit is not None or dirty is not None:
            raise ValueError('tested_commit cannot also describe a dirty worktree')
        value = {'type': 'tested_commit', 'tested_commit': tested_commit}
    elif base_commit is not None:
        if type(dirty) is not bool:
            raise ValueError('base_commit requires explicit dirty=True or False')
        value = {'type': 'worktree', 'base_commit': base_commit, 'dirty': dirty}
    else:
        if dirty is not None:
            raise ValueError('dirty requires base_commit')
        value = {'type': 'snapshot_only'}
    _validate_revision(value)
    return value


def _validate_revision(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid historical revision')
    kind = value.get('type')
    if kind == 'snapshot_only':
        _keys(value, {'type'}, 'snapshot revision')
        return
    if kind == 'tested_commit':
        _keys(value, {'type', 'tested_commit'}, 'tested commit revision')
        commit = value['tested_commit']
    elif kind == 'worktree':
        _keys(value, {'type', 'base_commit', 'dirty'}, 'worktree revision')
        if type(value['dirty']) is not bool:
            raise ValueError('Invalid dirty flag')
        commit = value['base_commit']
    else:
        raise ValueError('Unsupported historical revision type')
    if not isinstance(commit, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
        raise ValueError('Use a full historical Git commit hash')


def register(frozen_snapshot, report_path, record_id, reviewer, verdict, source_match,
             reviewed_at=None, tested_commit=None, base_commit=None, dirty=None):
    """Record a maintainer review of actual report bytes against a prior snapshot.

    source_match is the maintainer's review of which frozen inputs produced the
    report; hashing cannot infer that fact. The local report path is never stored.
    """
    validate_case_snapshot(frozen_snapshot)
    raw = Path(report_path).read_bytes()
    if not raw:
        raise ValueError('A nonempty actual report is required')
    value = {'kind': 'behavior_acceptance_record', 'schema_version': SCHEMA_VERSION,
             'record_id': record_id, 'case_id': frozen_snapshot['case_id'],
             'frozen_snapshot': frozen_snapshot,
             'historical_revision': _revision(tested_commit, base_commit, dirty),
             'report': {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)},
             'review': {'reviewer': reviewer, 'reviewed_at': reviewed_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'verdict': verdict, 'source_match': source_match, 'scope': 'behavior_only'},
             'research_conclusions_certified': False}
    value['record_sha256'] = fingerprint(value)
    validate_record(value)
    return value


def validate_record(value):
    _header(value, 'behavior_acceptance_record', {'record_id', 'case_id', 'frozen_snapshot',
            'historical_revision', 'report', 'review', 'research_conclusions_certified', 'record_sha256'})
    _identifier(value['record_id'], 'record id')
    _identifier(value['case_id'], 'case id')
    validate_case_snapshot(value['frozen_snapshot'])
    if value['case_id'] != value['frozen_snapshot']['case_id']:
        raise ValueError('Record case and snapshot case mismatch')
    _validate_revision(value['historical_revision'])
    _keys(value['report'], {'sha256', 'bytes'}, 'report')
    _sha(value['report']['sha256'], 'report sha256')
    if type(value['report']['bytes']) is not int or value['report']['bytes'] <= 0:
        raise ValueError('Invalid report byte count')
    review = value['review']
    _keys(review, {'reviewer', 'reviewed_at', 'verdict', 'source_match', 'scope'}, 'review')
    _identifier(review['reviewer'], 'reviewer')
    if not isinstance(review['reviewed_at'], str):
        raise ValueError('Invalid review date')
    try:
        parsed = datetime.strptime(review['reviewed_at'], '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as exc:
        raise ValueError('Review date must be a valid UTC timestamp') from exc
    if parsed.strftime('%Y-%m-%dT%H:%M:%SZ') != review['reviewed_at']:
        raise ValueError('Review date must use canonical UTC timestamp spelling')
    if (review['verdict'] not in VERDICTS or review['source_match'] not in SOURCE_MATCHES or
            review['scope'] != 'behavior_only' or value['research_conclusions_certified'] is not False):
        raise ValueError('Invalid review scope, verdict, or source match')
    if value['record_sha256'] != fingerprint({k: v for k, v in value.items() if k != 'record_sha256'}):
        raise ValueError('Acceptance record fingerprint mismatch')
    return value


def write_new(value, destination):
    """Exclusive creation: historical records and snapshots are never overwritten."""
    validators = {'behavior_file_snapshot': validate_snapshot, 'behavior_case_snapshot': validate_case_snapshot,
                  'behavior_acceptance_record': validate_record}
    if not isinstance(value, dict) or value.get('kind') not in validators:
        raise ValueError('Unsupported output format')
    validators[value['kind']](value)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def _input_match(index, root, record):
    case = _case(index, record['case_id'])
    frozen = record['frozen_snapshot']
    reasons = []
    if frozen['case_definition_sha256'] != fingerprint(_definition(index, case)):
        reasons.append('case_definition_drift')
    try:
        current = case_snapshot(index, record['case_id'], root)
    except (OSError, ValueError):
        return [*reasons, 'input_unavailable']
    for group, reason in [('input_snapshot', 'request_or_fixture_drift'), ('source_snapshot', 'source_drift')]:
        if current[group]['files_sha256'] != frozen[group]['files_sha256']:
            reasons.append(reason)
    return reasons


def check_current(index, root, record, report_path=None):
    """Check this particular historical review, including the local report original."""
    validate_record(record)
    reasons = _input_match(index, root, record)
    inputs_match = not reasons
    if record['review']['verdict'] != 'passed':
        reasons.append('review_not_passed')
    if record['review']['source_match'] != 'confirmed':
        reasons.append('report_source_not_confirmed')
    report_match = False
    if report_path is None:
        reasons.append('report_unavailable')
    else:
        try:
            raw = Path(report_path).read_bytes()
        except OSError:
            reasons.append('report_unavailable')
        else:
            report_match = (len(raw) == record['report']['bytes'] and
                            hashlib.sha256(raw).hexdigest() == record['report']['sha256'])
            if not report_match:
                reasons.append('report_bytes_drift')
    return {'kind': 'behavior_acceptance_check', 'schema_version': SCHEMA_VERSION,
            'case_id': record['case_id'], 'record_id': record['record_id'],
            'inputs_match': inputs_match, 'report_match': report_match,
            'current_pass': not reasons, 'reasons': reasons,
            'research_conclusions_certified': False}


def rerun_plan(index, changed_rule_tags, root=None, records=()):
    """Select tag hits; optionally add drift in the latest supplied historical review.

    Unrecorded cases do not silently expand a directed plan into the whole suite.
    A plan does not claim any case has passed or dispatch evaluation.
    """
    validate_index(index)
    if not isinstance(changed_rule_tags, list) or not changed_rule_tags:
        raise ValueError('Provide at least one changed rule tag')
    tags = [_identifier(t, 'changed rule tag', tag=True) for t in changed_rule_tags]
    if len(set(tags)) != len(tags):
        raise ValueError('Duplicate changed rule tags')
    known = {t for case in index['cases'] for t in case['rule_tags']}
    if set(tags) - known:
        raise ValueError('Unknown changed rule tag; update the public index explicitly')
    latest = {}
    seen_ids = set()
    if records and root is None:
        raise ValueError('Input root is required to inspect historical drift')
    for record in records:
        validate_record(record)
        _case(index, record['case_id'])
        if record['record_id'] in seen_ids:
            raise ValueError('Duplicate historical record id')
        seen_ids.add(record['record_id'])
        prior = latest.get(record['case_id'])
        if prior and prior['review']['reviewed_at'] == record['review']['reviewed_at']:
            raise ValueError('Ambiguous latest review timestamp for a case')
        if prior is None or record['review']['reviewed_at'] > prior['review']['reviewed_at']:
            latest[record['case_id']] = record
    cases = []
    for case in index['cases']:
        hits = sorted(set(tags) & set(case['rule_tags']))
        reasons = ['changed_rule'] if hits else []
        if case['case_id'] in latest:
            reasons.extend(_input_match(index, root, latest[case['case_id']]))
        if reasons:
            cases.append({'case_id': case['case_id'], 'rule_hits': hits,
                          'request_path': case['request_path'], 'fixture_paths': sorted(case['fixture_paths']),
                          'reasons': reasons})
    return {'kind': 'behavior_rerun_plan', 'schema_version': SCHEMA_VERSION,
            'changed_rule_tags': sorted(tags), 'cases': cases, 'evaluation_dispatched': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    plain = sub.add_parser('snapshot', help='freeze an explicit relative file list')
    plain.add_argument('--root', type=Path, required=True)
    plain.add_argument('--files', nargs='+', required=True)
    plain.add_argument('--out', type=Path, required=True)
    capture = sub.add_parser('case-snapshot', help='freeze one public indexed case')
    capture.add_argument('--index', type=Path, required=True)
    capture.add_argument('--root', type=Path, required=True)
    capture.add_argument('--case', required=True)
    capture.add_argument('--out', type=Path, required=True)
    reg = sub.add_parser('register', help='append maintainer review metadata of actual report bytes')
    reg.add_argument('--snapshot', type=Path, required=True)
    reg.add_argument('--report', type=Path, required=True)
    reg.add_argument('--record-id', required=True)
    reg.add_argument('--reviewer', required=True)
    reg.add_argument('--verdict', choices=sorted(VERDICTS), required=True)
    reg.add_argument('--source-match', choices=sorted(SOURCE_MATCHES), required=True)
    reg.add_argument('--reviewed-at')
    revisions = reg.add_mutually_exclusive_group()
    revisions.add_argument('--tested-commit')
    revisions.add_argument('--base-commit')
    reg.add_argument('--dirty', choices=['true', 'false'])
    reg.add_argument('--out', type=Path, required=True)
    check = sub.add_parser('check', help='check a recorded review against current inputs and local report')
    check.add_argument('--index', type=Path, required=True)
    check.add_argument('--root', type=Path, required=True)
    check.add_argument('--record', type=Path, required=True)
    check.add_argument('--report', type=Path)
    rerun = sub.add_parser('rerun', help='list cases for explicitly changed rules and optional historical drift')
    rerun.add_argument('--index', type=Path, required=True)
    rerun.add_argument('--changed-rule', nargs='+', required=True)
    rerun.add_argument('--root', type=Path)
    rerun.add_argument('--records', nargs='+', type=Path, default=[])
    args = parser.parse_args()
    try:
        if args.command == 'snapshot':
            result = snapshot(args.root, args.files)
            write_new(result, args.out)
        elif args.command == 'case-snapshot':
            result = case_snapshot(read_json(args.index), args.case, args.root)
            write_new(result, args.out)
        elif args.command == 'register':
            dirty = None if args.dirty is None else args.dirty == 'true'
            result = register(read_json(args.snapshot), args.report, args.record_id, args.reviewer,
                              args.verdict, args.source_match, args.reviewed_at,
                              args.tested_commit, args.base_commit, dirty)
            write_new(result, args.out)
        elif args.command == 'check':
            result = check_current(read_json(args.index), args.root, read_json(args.record), args.report)
        else:
            result = rerun_plan(read_json(args.index), args.changed_rule, args.root,
                                [read_json(p) for p in args.records])
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    if args.command == 'check' and not result['current_pass']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
