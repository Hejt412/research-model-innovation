"""Freeze source/config evidence and flag changes outside one declared factor."""
import argparse
import hashlib
from pathlib import Path
from _static import emit, inventory
from _records import changes, manifest, read_json, seal


def unresolved_paths(value, path=''):
    if isinstance(value, dict):
        return [pointer for key, item in value.items()
                for pointer in unresolved_paths(item, path + '/' + key.replace('~', '~0').replace('/', '~1'))]
    if value is None or (path.endswith('/seeds') and value == []):
        return [path]
    if isinstance(value, list):
        return [pointer for i, item in enumerate(value) for pointer in unresolved_paths(item, path + '/' + str(i))]
    return []


def snapshot(root, config_path, experiment_id, control_id=None):
    config = read_json(config_path)
    if not isinstance(config, dict) or not config:
        raise ValueError('Provide a nonempty, reviewed effective config as a JSON object')
    root, paths, skipped, errors = inventory(root)
    if errors:
        raise ValueError('Cannot freeze a manifest with unreadable files: ' + str(errors))
    files = {}
    for path in paths:
        if path.suffix.lower() != '.md':
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return seal({'schema_version': 1, 'kind': 'experiment_manifest', 'experiment_id': experiment_id,
                 'control_id': control_id, 'config': config, 'files': files, 'skipped': skipped,
                 'unresolved_config_paths': unresolved_paths(config),
                 'coverage': 'Python and text configs under root; no binary data/notebooks/runtime validation',
                 'effective_config_verified_at_runtime': False})


def audit(before, after, factor, config_paths, allowed_files):
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
    return {'schema_version': 1, 'kind': 'experiment_audit', 'status': status, 'factor': factor,
            'control_sha256': before['manifest_sha256'], 'experiment_sha256': after['manifest_sha256'],
            'declared_config_paths': sorted(config_paths), 'declared_files': sorted(allowed_files),
            'config_changes': delta, 'file_changes': files,
            'unexpected_config_changes': unexpected_config, 'unexpected_file_changes': unexpected_files,
            'unresolved_config_paths': {'control': before.get('unresolved_config_paths', unresolved_paths(before['config'])),
                                        'experiment': after.get('unresolved_config_paths', unresolved_paths(after['config']))},
            'skipped': {'control': before['skipped'], 'experiment': after['skipped']},
            'single_factor_causality_verified': False,
            'review_required': 'Review the actual diff: one allowed file can contain multiple independent changes. '
                               'Config overrides, binary datasets and runtime state are not verified.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    snap = commands.add_parser('snapshot')
    snap.add_argument('root', type=Path)
    snap.add_argument('--config', type=Path, required=True)
    snap.add_argument('--experiment-id', required=True)
    snap.add_argument('--control-id')
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
            result = snapshot(args.root, args.config, args.experiment_id, args.control_id)
        else:
            result = audit(manifest(args.control), manifest(args.experiment), args.factor,
                           args.allow_config, args.allow_file)
        emit(result, args.out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))
    if result.get('status') in {'extra_changes_detected', 'no_change_detected'}:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
