"""Link completed-run artifacts to observations using byte hashes; never load model weights."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
from _records import read_json, fingerprint, manifest
from _static import emit
from _versions import annotate, require_readable

FIELDS = ('experiment_id', 'seed', 'task', 'metric', 'value', 'unit', 'manifest_sha256', 'run_id')
ARTIFACTS = ('checkpoint', 'training_log', 'evaluation_log', 'results')


def sha256_text(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def file_evidence(path):
    before = path.stat()
    if not path.is_file() or before.st_size == 0:
        raise ValueError('Run artifacts must be nonempty regular files: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Artifact changed while hashing: ' + str(path))
    return {'path': str(path.resolve()), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def observations(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(FIELDS).issubset(reader.fieldnames):
            raise ValueError('Run observation CSV requires unique columns including run_id')
        rows = []
        for row in reader:
            if any(not isinstance(row.get(k), str) or not row[k].strip() for k in FIELDS):
                raise ValueError('Missing run observation field')
            rows.append({k: row[k].strip() for k in FIELDS})
    if not rows:
        raise ValueError('Run observation CSV is empty')
    # Also validates numeric values and duplicate identities.
    keys = [observation_key(row)[:4] for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate run observation identity')
    return rows


def observation_key(row):
    seed, number = int(row['seed']), float(row['value'])
    if seed < 0 or not math.isfinite(number):
        raise ValueError('Invalid run observation seed/value')
    return (row['experiment_id'], str(seed), row['task'], row['metric'], number,
            row['unit'], row['manifest_sha256'], row.get('run_id'))


def identity(run):
    if not isinstance(run, dict):
        raise ValueError('Run identity must be an object')
    for key in ('run_id', 'experiment_id'):
        if not isinstance(run.get(key), str) or not run[key].strip():
            raise ValueError('Each run requires nonempty ' + key)
    if type(run.get('seed')) is not int or run['seed'] < 0 or not sha256_text(run.get('manifest_sha256')):
        raise ValueError('Each run requires an integer seed and manifest SHA-256')
    return {k: run[k] for k in ('run_id', 'experiment_id', 'seed', 'manifest_sha256')}


def receipt_errors(run, receipt):
    expected = {**identity(run), 'kind': 'evaluation_receipt', 'schema_version': 1,
                **{kind + '_sha256': run['artifacts'][kind]['sha256'] for kind in ('checkpoint', 'training_log', 'results')}}
    if not isinstance(receipt, dict):
        return ['receipt_not_object']
    return [key for key, value in expected.items() if type(receipt.get(key)) is not type(value) or receipt.get(key) != value]


def capture(spec_path):
    spec = read_json(spec_path)
    if not isinstance(spec, dict) or type(spec.get('schema_version')) is not int or spec['schema_version'] != 1 or spec.get('kind') != 'run_spec' or not isinstance(spec.get('runs'), list) or not spec['runs']:
        raise ValueError('Expected nonempty run_spec schema_version=1')
    runs, seen = [], set()
    for row in spec['runs']:
        if not isinstance(row, dict):
            raise ValueError('Run must be an object')
        run = identity(row)
        if run['run_id'] in seen:
            raise ValueError('Duplicate run_id')
        seen.add(run['run_id'])
        artifacts = {}
        for kind in ARTIFACTS:
            name = row.get(kind + '_path')
            if not isinstance(name, str) or not name:
                raise ValueError('Missing artifact path: ' + kind)
            artifacts[kind] = file_evidence(spec_path.parent / name)
        run['artifacts'] = artifacts
        mismatches = receipt_errors(run, read_json(Path(artifacts['evaluation_log']['path'])))
        if mismatches:
            raise ValueError('Evaluation receipt differs from supplied artifacts/identity: ' + ', '.join(mismatches))
        for observation in observations(Path(artifacts['results']['path'])):
            if any(str(observation[k]) != str(run[k]) for k in ('run_id', 'experiment_id', 'seed', 'manifest_sha256')):
                raise ValueError('Per-run results contain a different run identity')
        runs.append(run)
    ledger = annotate({'schema_version': 1, 'kind': 'run_ledger', 'runs': runs,
                       'training_executed_by_tool': False, 'weights_deserialized': False})
    return {**ledger, 'record_sha256': fingerprint(ledger)}


def verify(ledger_path, manifests, rows):
    if ledger_path is None:
        return {'status': 'not_supplied', 'issues': [], 'independence_verified': False,
                'independence_status': 'unknown', 'statistical_use_allowed': False}
    from record_versions import unwrap
    ledger = unwrap(read_json(ledger_path))
    version_status = require_readable(ledger)
    if ledger.get('kind') != 'run_ledger' or ledger.get('record_sha256') != fingerprint({k: v for k, v in ledger.items() if k != 'record_sha256'}):
        raise ValueError('Run ledger kind/fingerprint mismatch')
    if not isinstance(ledger.get('runs'), list) or not ledger['runs']:
        raise ValueError('Run ledger must contain runs')
    issues, runs, originals = [], {}, {}
    if not rows:
        issues.append({'kind': 'no_observations'})
    if version_status['status'] != 'supported_current':
        issues.append({'kind': 'run_ledger_version_unverified', 'version': version_status})
    digests = {k: defaultdict(set) for k in ('checkpoint', 'training_log')}
    for run in ledger['runs']:
        identity(run)
        rid = run['run_id']
        if rid in runs:
            raise ValueError('Duplicate run_id')
        runs[rid] = run
        exp = manifests.get(run['experiment_id'])
        if not exp or exp['manifest_sha256'] != run['manifest_sha256']:
            issues.append({'kind': 'run_manifest_mismatch', 'run_id': rid})
        artifacts = run.get('artifacts')
        if not isinstance(artifacts, dict) or any(not isinstance(artifacts.get(k), dict) or
                not sha256_text(artifacts[k].get('sha256')) or not isinstance(artifacts[k].get('path'), str) for k in ARTIFACTS):
            raise ValueError('Malformed run artifact records')
        paths, intact = {}, True
        for kind in ARTIFACTS:
            paths[kind] = ledger_path.parent / artifacts[kind]['path']
            try:
                current = file_evidence(paths[kind])
                if current['sha256'] != artifacts[kind]['sha256'] or current['bytes'] != artifacts[kind].get('bytes'):
                    raise ValueError('bytes or hash differ')
            except (OSError, ValueError) as exc:
                issues.append({'kind': 'artifact_unavailable_or_changed', 'run_id': rid, 'artifact': kind, 'reason': str(exc)})
                intact = False
        for kind in digests:
            digests[kind][artifacts[kind]['sha256']].add(rid)
        if intact:
            try:
                mismatch = receipt_errors(run, read_json(paths['evaluation_log']))
                if mismatch:
                    issues.append({'kind': 'receipt_mismatch', 'run_id': rid, 'fields': mismatch})
                source_rows = observations(paths['results'])
                if any(any(str(row[k]) != str(run[k]) for k in ('run_id', 'experiment_id', 'seed', 'manifest_sha256')) for row in source_rows):
                    issues.append({'kind': 'source_results_identity_mismatch', 'run_id': rid})
                originals[rid] = {observation_key(row) for row in source_rows}
            except (OSError, ValueError, TypeError, KeyError) as exc:
                issues.append({'kind': 'invalid_source_log_or_results', 'run_id': rid, 'reason': str(exc)})
    for kind, groups in digests.items():
        for digest, ids in groups.items():
            if len(ids) > 1:
                issues.append({'kind': kind + '_reused_across_run_ids', 'run_ids': sorted(ids), 'sha256': digest})
    task_runs = defaultdict(set)
    for row in rows:
        rid = row.get('run_id')
        run = runs.get(rid)
        if not run:
            issues.append({'kind': 'observation_run_missing', 'run_id': rid})
            continue
        if any(str(row[k]) != str(run[k]) for k in ('experiment_id', 'seed', 'manifest_sha256')):
            issues.append({'kind': 'observation_run_identity_mismatch', 'run_id': rid})
        if observation_key(row) not in originals.get(rid, set()):
            issues.append({'kind': 'observation_not_in_source_results', 'run_id': rid, 'task': row['task'], 'metric': row['metric']})
        task_runs[(row['experiment_id'], str(row['seed']), row['task'])].add(rid)
    for key, ids in task_runs.items():
        if len(ids) > 1:
            issues.append({'kind': 'mixed_runs_within_task_seed', 'group': list(key), 'run_ids': sorted(ids)})
    return {'status': 'conflicts_or_unavailable' if issues else 'linked_artifacts_no_reuse_detected',
            'ledger_file_sha256': hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            'ledger_record_sha256': ledger['record_sha256'], 'issues': issues,
            'independence_verified': False, 'independence_status': 'unknown' if issues else 'declared_only_no_reuse_detected',
            'statistical_use_allowed': not issues,
            'limitations': ['Byte hashes and receipts check supplied provenance, not authenticity or statistical independence.',
                           'Different serialized bytes can still encode identical weights; no tensors are deserialized.',
                           'Repeated evaluation of one run should reuse run_id across tasks/metrics, never invent training replicates.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('capture')
    c.add_argument('spec', type=Path)
    c.add_argument('--out', type=Path, required=True)
    v = sub.add_parser('check')
    v.add_argument('ledger', type=Path)
    v.add_argument('--control', type=Path, required=True)
    v.add_argument('--experiment', type=Path, required=True)
    v.add_argument('--results', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == 'capture':
            result = capture(args.spec)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open('x', encoding='utf-8') as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            emit({'ledger': str(args.out), 'runs': len(result['runs']), 'training_executed': False}, None)
        else:
            a, b = manifest(args.control), manifest(args.experiment)
            result = verify(args.ledger, {a['experiment_id']: a, b['experiment_id']: b}, observations(args.results))
            emit(result, None)
            if not result['statistical_use_allowed']:
                raise SystemExit(2)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
