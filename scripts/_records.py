"""Strict JSON records, fingerprints and structural differences."""
import hashlib
import json
from pathlib import Path


def read_json(path):
    return loads_json(Path(path).read_text(encoding='utf-8-sig'))


def loads_json(text):
    def reject_constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(text, parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def seal(record):
    return {**record, 'manifest_sha256': fingerprint(record)}


def manifest(path):
    from record_versions import unwrap
    from _versions import require_readable
    value = unwrap(read_json(path))
    if not isinstance(value, dict):
        raise ValueError('Manifest must be an object')
    content = {key: item for key, item in value.items() if key != 'manifest_sha256'}
    if value.get('manifest_sha256') != fingerprint(content):
        raise ValueError('Manifest fingerprint mismatch')
    if value.get('kind') != 'experiment_manifest':
        raise ValueError('Unsupported experiment manifest')
    require_readable(value)
    if not isinstance(value.get('config'), dict) or not isinstance(value.get('files'), dict):
        raise ValueError('Manifest config/files must be objects')
    return value


def changes(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        rows = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in before:
                rows.append({'path': pointer, 'kind': 'added', 'after': after[key]})
            elif key not in after:
                rows.append({'path': pointer, 'kind': 'removed', 'before': before[key]})
            else:
                rows.extend(changes(before[key], after[key], pointer))
        return rows
    # Keep lists atomic: order and length may have protocol meaning.
    if type(before) is type(after) and before == after:
        return []
    return [{'path': path or '/', 'kind': 'changed', 'before': before, 'after': after}]
