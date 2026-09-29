"""Audit declared text-freeze coverage separately from the allowed change set."""


def coverage(record):
    scope = record.get('source_scope')
    if not isinstance(scope, dict):
        return {'status': 'unverified_legacy_scope', 'missing_required_files': [], 'gaps': record.get('skipped', [])}
    missing = sorted(set(scope['required_files']) - set(record['files']))
    gaps = [s for s in record['skipped'] if s['reason'] != 'excluded_directory']
    complete = bool(record['files']) and not missing and not gaps
    return {'status': 'complete_in_declared_scope' if complete else 'incomplete',
            'missing_required_files': missing, 'gaps': gaps,
            'excluded_directories': [s['path'] for s in record['skipped'] if s['reason'] == 'excluded_directory'],
            'dependency_closure_verified': False,
            'limitation': 'Only declared text scope; required files must include reviewed entrypoints and dependencies. Exclusions are not evidence of irrelevance.'}


def compare_coverage(before, after):
    left, right = coverage(before), coverage(after)
    status = ('incomplete_or_unverified' if any(r['status'] != 'complete_in_declared_scope' for r in (left, right)) else
              'scope_changed' if before['source_scope'] != after['source_scope'] else 'complete_in_declared_scope')
    return {'status': status, 'control': left, 'experiment': right}
