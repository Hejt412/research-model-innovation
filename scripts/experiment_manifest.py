"""Freeze source/config evidence and flag changes outside one declared factor."""
import argparse
import hashlib
from pathlib import Path
from _static import emit, inventory
from _records import changes, manifest, read_json, seal
from _config_schema import evaluation_plan, validate_config
from data_protocol import inspect_plan
from _source_coverage import coverage, compare_coverage
from _versions import annotate, require_readable


def unresolved_paths(value, path=''):
    report = validate_config(value)
    return sorted(set(report['missing'] + report['unknown'] + [item['path'] for item in report['invalid']]))


def snapshot(root, config_path, experiment_id, control_id=None, data_plan=None, *, required_files=(), max_bytes=2_000_000, exclude_dirs=()):
    config = read_json(config_path)
    if not isinstance(config, dict) or not config:
        raise ValueError('Provide a nonempty, reviewed effective config as a JSON object')
    validation = validate_config(config)
    if validation['invalid']:
        raise ValueError('Invalid config fields: ' + str(validation['invalid']))
    root, paths, skipped, errors = inventory(root, max_bytes, exclude_dirs)
    required = []
    for name in required_files:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Required files must be inside the scan root')
        required.append(path.relative_to(root).as_posix())
    if errors:
        raise ValueError('Cannot freeze a manifest with unreadable files: ' + str(errors))
    files = {}
    for path in paths:
        if path.suffix.lower() != '.md':
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    data_report = inspect_plan(read_json(data_plan)) if data_plan else None
    if data_report:
        expected_plan = evaluation_plan(config)
        sampling = config.get('evaluation', {}).get('sampling')
        if sampling != data_report['mode']:
            data_report['issues'].append({'kind': 'sampling_mode_unconfirmed_or_mismatch'})
        if data_report['mode'] == 'episodic':
            observed_pairs = {(r['task'], r['seed']) for r in data_report['task_seed_counts']}
            wanted_pairs = {(task, seed) for task in expected_plan['tasks'] for seed in expected_plan['seeds']}
            if not expected_plan['declared']:
                data_report['issues'].append({'kind': 'evaluation_plan_undeclared'})
            for task, seed in sorted(wanted_pairs - observed_pairs):
                data_report['issues'].append({'kind': 'missing_task_seed_episodes', 'task': task, 'seed': seed})
            for task, seed in sorted(observed_pairs - wanted_pairs):
                data_report['issues'].append({'kind': 'unplanned_task_seed_episodes', 'task': task, 'seed': seed})
        if data_report['issues']:
            data_report['status'] = 'protocol_conflicts'
    record = {'schema_version': 2, 'kind': 'experiment_manifest', 'experiment_id': experiment_id,
                 'control_id': control_id, 'config': config, 'files': files, 'skipped': skipped,
                 'unresolved_config_paths': unresolved_paths(config),
                 'config_validation': validation,
                 'data_protocol': data_report,
                 'coverage': 'Python and text configs under root; no binary data/notebooks/runtime validation',
                 'effective_config_verified_at_runtime': False,
                 'source_scope': {'required_files': sorted(set(required)), 'max_bytes': max_bytes,
                                  'exclude_dirs': sorted(set(exclude_dirs))}}
    record['source_coverage'] = coverage(record)
    return seal(annotate(record))


def audit(before, after, factor, config_paths, allowed_files):
    versions = {'control': require_readable(before), 'experiment': require_readable(after)}
    if before['experiment_id'] == after['experiment_id']:
        raise ValueError('Control and experiment IDs must differ')
    if after['control_id'] != before['experiment_id']:
        raise ValueError('Experiment control_id does not match the control manifest')
    if not factor.strip():
        raise ValueError('A human-readable single-factor declaration is required')
    delta = changes(before['config'], after['config'])
    files = [key for key in sorted(before['files'].keys() | after['files'].keys())
             if before['files'].get(key) != after['files'].get(key)]
    unexpected_config = [row for row in delta if row['path'] not in config_paths]
    unexpected_files = [key for key in files if key not in allowed_files]
    status = ('extra_changes_detected' if unexpected_config or unexpected_files else
              'no_change_detected' if not delta and not files else 'within_declared_scope')
    left_data, right_data = before.get('data_protocol'), after.get('data_protocol')
    data_status = ('not_supplied' if not left_data or not right_data else
                   'protocol_conflicts' if left_data['issues'] or right_data['issues'] else
                   'few_shot_unverified' if any(d.get('mode') == 'episodic' and d.get('few_shot', {}).get('status') != 'declared_counts_consistent' for d in (left_data, right_data)) else
                   'declared_plan_changed' if left_data['plan_sha256'] != right_data['plan_sha256'] else 'same_declared_plan')
    return annotate({'schema_version': 2, 'kind': 'experiment_audit', 'status': status, 'factor': factor,
            'input_versions': versions,
            'control_sha256': before['manifest_sha256'], 'experiment_sha256': after['manifest_sha256'],
            'declared_config_paths': sorted(config_paths), 'declared_files': sorted(allowed_files),
            'config_changes': delta, 'file_changes': files,
            'unexpected_config_changes': unexpected_config, 'unexpected_file_changes': unexpected_files,
            'unresolved_config_paths': {'control': unresolved_paths(before['config']),
                                        'experiment': unresolved_paths(after['config'])},
            'config_validation': {'control': validate_config(before['config']), 'experiment': validate_config(after['config'])},
            'data_protocol_status': data_status,
            'source_coverage': compare_coverage(before, after),
            'skipped': {'control': before['skipped'], 'experiment': after['skipped']},
            'single_factor_causality_verified': False,
            'review_required': 'Review the actual diff: one allowed file can contain multiple independent changes. '
                               'Config overrides, binary datasets and runtime state are not verified.'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    snap = commands.add_parser('snapshot')
    snap.add_argument('root', type=Path)
    snap.add_argument('--config', type=Path, required=True)
    snap.add_argument('--experiment-id', required=True)
    snap.add_argument('--control-id')
    snap.add_argument('--data-plan', type=Path, help='Sample split and episode JSON; metadata only')
    snap.add_argument('--required-file', action='append', default=[], help='Reviewed critical entrypoint/dependency, relative to root; repeatable')
    snap.add_argument('--max-bytes', type=int, default=2_000_000)
    snap.add_argument('--exclude-dir', action='append', default=[])
    snap.add_argument('--out', type=Path, required=True)
    check = commands.add_parser('check')
    check.add_argument('control', type=Path)
    check.add_argument('experiment', type=Path)
    check.add_argument('--factor', required=True)
    check.add_argument('--allow-config', action='append', default=[], help='Exact JSON pointer; no wildcards')
    check.add_argument('--allow-file', action='append', default=[], help='Exact project-relative POSIX path')
    check.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        if args.command == 'snapshot':
            if args.out.resolve().is_relative_to(args.root.resolve()):
                raise ValueError('Store manifests outside the scanned project root to avoid self-inclusion')
            result = snapshot(args.root, args.config, args.experiment_id, args.control_id, args.data_plan,
                              required_files=args.required_file, max_bytes=args.max_bytes, exclude_dirs=args.exclude_dir)
        else:
            result = audit(manifest(args.control), manifest(args.experiment), args.factor,
                           args.allow_config, args.allow_file)
        emit(result, args.out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))
    if (result.get('status') in {'extra_changes_detected', 'no_change_detected'} or
        result.get('data_protocol_status') in {'protocol_conflicts', 'declared_plan_changed', 'few_shot_unverified'} or
        result.get('source_coverage', {}).get('status') != 'complete_in_declared_scope'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
