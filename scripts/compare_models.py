"""Compare two static model inventories, without assuming ancestry or efficacy."""
import argparse
import json
from pathlib import Path
from _static import SCHEMA, emit


def load(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA or not isinstance(data.get('models'), list):
        raise ValueError('Input must be an analyze_models.py schema_version=1 report')
    rows = data['models']
    indexed = {}
    for row in rows:
        key = row['file'] + '::' + row['class']
        if key in indexed:
            raise ValueError('Ambiguous duplicate class key: ' + key)
        indexed[key] = row
    return data, indexed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        left, a = load(args.before)
        right, b = load(args.after)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))
    changed, unchanged = [], []
    for key in sorted(a.keys() & b.keys()):
        old, new = a[key], b[key]
        if old['ast_sha256'] == new['ast_sha256']:
            unchanged.append(key)
        else:
            def assigned(row):
                return {item['target'] + ' = ' + str(item['expression']) for item in row['assignments']}
            x, y = assigned(old), assigned(new)
            changed.append({'model': key, 'assignments_removed': sorted(x-y),
                            'assignments_added': sorted(y-x),
                            'before_line': old['line'], 'after_line': new['line'],
                            'before_methods': old['methods'], 'after_methods': new['methods']})
    emit({'schema_version': SCHEMA, 'added': sorted(b.keys()-a.keys()),
          'removed': sorted(a.keys()-b.keys()), 'changed': changed, 'unchanged': unchanged,
          'input_errors': {'before': left.get('errors', []), 'after': right.get('errors', [])},
          'input_skipped': {'before': left.get('skipped', []), 'after': right.get('skipped', [])},
          'limitations': ['File/class keys only; renamed models appear added/removed.',
                          'Source changes do not establish novelty, execution or performance.']}, args.out)


if __name__ == '__main__':
    main()
