"""Compare two static model inventories, without assuming ancestry or efficacy."""
import argparse
import json
from pathlib import Path
from _static import SCHEMA, emit


def load(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('schema_version') not in {1, 2} or not isinstance(data.get('models'), list):
        raise ValueError('Input must be an analyze_models.py schema_version=1 or 2 report')
    rows = data['models']
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('file', 'class', 'ast_sha256')):
            raise ValueError('Invalid model identity or fingerprint')
        if not isinstance(row.get('assignments'), list) or not isinstance(row.get('methods'), list):
            raise ValueError('Invalid model assignments or methods')
        key = row['file'] + '::' + row['class']
        if key in indexed:
            raise ValueError('Ambiguous duplicate class key: ' + key)
        indexed[key] = row
    return data, indexed


def compare(old, new):
    x = {item['target'] + ' = ' + str(item['expression']) for item in old['assignments']}
    y = {item['target'] + ' = ' + str(item['expression']) for item in new['assignments']}
    before, after = old.get('dependencies', {}), new.get('dependencies', {})
    a, b = before.get('files', {}), after.get('files', {})
    dep_changes = [key for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key)]
    class_changed = old['ast_sha256'] != new['ast_sha256']
    unverified = (not before or not after or before.get('scan_incomplete') or after.get('scan_incomplete')
                  or before.get('unverified_imports') or after.get('unverified_imports'))
    status = ('class_source_changed' if class_changed else 'dependency_source_changed' if dep_changes
              else 'dependencies_unverified' if unverified else 'no_change_in_scanned_sources')
    return {'left_model': old['file'] + '::' + old['class'],
            'right_model': new['file'] + '::' + new['class'], 'status': status,
            'class_source_changed': class_changed, 'dependency_files_changed': dep_changes,
            'dependency_coverage': 'unverified' if unverified else 'local_static_only',
            'unverified_imports': sorted(set(before.get('unverified_imports', []) + after.get('unverified_imports', []))),
            'assignments_removed': sorted(x-y), 'assignments_added': sorted(y-x),
            'assignment_scope': 'class_body_only; inherited components are not expanded or proven removed',
            'left_bases': old.get('bases', []), 'right_bases': new.get('bases', []),
            'left_inheritance': old.get('inheritance', {'status': 'not_available'}),
            'right_inheritance': new.get('inheritance', {'status': 'not_available'}),
            'effective_component_evidence': {'left': old.get('effective_assignments', old['assignments']),
                                             'right': new.get('effective_assignments', new['assignments'])},
            'assignments_shared': sorted(x & y), 'left_methods': old['methods'], 'right_methods': new['methods'],
            'architecture_evidence': {'left': architecture_evidence(old), 'right': architecture_evidence(new)},
            'training_protocol': 'not established by model source; compare experiment manifests',
            'runtime_equivalence_verified': False}


def architecture_evidence(model):
    """Keyword routing only; preserve expressions/lines instead of inferring a graph."""
    terms = {'input_representation': ('fft', 'stft', 'patch', 'embed', 'stem', 'token'),
             'backbone': ('mamba', 'transformer', 'conv', 'lstm', 'gru', 'backbone'),
             'branches_fusion': ('branch', 'fusion', 'cat(', 'concat', 'gate', 'attention'),
             'normalization': ('norm',), 'classifier': ('classifier', 'head', 'prototype', 'linear'),
             'loss': ('loss', 'criterion', 'cross_entropy')}
    evidence = [{'line': item['line'], 'expression': item['target'] + ' = ' + str(item['expression'])}
                for item in model.get('effective_assignments', model['assignments'])]
    for method in model.get('effective_methods', model['methods']):
        evidence.extend({'line': call['line'], 'expression': call['call']}
                        for call in method.get('calls_in_source_order', []))
    return {kind: {'status': 'keyword_hints_require_source_review',
                   'evidence': [item for item in evidence if any(term in item['expression'].lower() for term in words)]}
            for kind, words in terms.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path, nargs='?', help='Defaults to before for peer-model comparison')
    p.add_argument('--left-model', help='Exact file.py::Class selector')
    p.add_argument('--right-model', help='Exact file.py::Class selector')
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        left, a = load(args.before)
        right, b = load(args.after or args.before)
        if bool(args.left_model) != bool(args.right_model):
            raise ValueError('Both --left-model and --right-model are required together')
        if args.left_model and (args.left_model not in a or args.right_model not in b):
            raise ValueError('Selected model was not found')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))
    pairs = [(args.left_model, args.right_model)] if args.left_model else [(key, key) for key in sorted(a.keys() & b.keys())]
    try:
        comparisons = [compare(a[left_key], b[right_key]) for left_key, right_key in pairs]
    except (KeyError, TypeError, AttributeError) as exc:
        p.error('Malformed model report: ' + str(exc))
    emit({'schema_version': SCHEMA, 'added': sorted(b.keys()-a.keys()),
          'removed': sorted(a.keys()-b.keys()), 'mode': 'peer_models' if args.left_model else 'snapshots',
          'comparisons': comparisons,
          'class_source_unchanged': [r['left_model'] for r in comparisons if not r['class_source_changed']],
          'input_errors': {'before': left.get('errors', []), 'after': right.get('errors', [])},
          'input_skipped': {'before': left.get('skipped', []), 'after': right.get('skipped', [])},
          'limitations': ['Without explicit selectors, renamed models appear added/removed.',
                          'Import graph is conservative; whole-file changes may be unrelated to a particular class.',
                          'External/dynamic imports and runtime configuration remain unverified.',
                          'Source changes do not establish novelty, execution or performance.']}, args.out)


if __name__ == '__main__':
    main()
