"""Separate record shape, review rules and the actual installed tool source."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess

RULES_VERSION = '2.2'
KNOWN_RULES = ('2.0', '2.1', RULES_VERSION)
FORMATS = {'experiment_manifest': 2, 'experiment_audit': 2, 'observed_result_summary': 2,
           'run_ledger': 1, 'config_flow_evidence': 1}


def scripts_digest():
    root = Path(__file__).resolve().parent
    files = {p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sorted(root.glob('*.py'))}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def producer():
    root = Path(__file__).resolve().parents[1]
    result = {'name': 'research-model-innovation', 'scripts_sha256': scripts_digest(),
              'tool_commit': None, 'working_tree_dirty': None, 'commit_source': 'unavailable'}
    if (root / '.git').exists():
        try:
            commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, check=True, timeout=5).stdout.decode().strip()
            dirty = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, check=True, timeout=5).stdout
            result.update(tool_commit=commit, working_tree_dirty=bool(dirty), commit_source='local_git')
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            stamp = json.loads((root / '.tool-release.json').read_text(encoding='utf-8'))
            commit = stamp.get('tool_commit')
            if stamp.get('scripts_sha256') == result['scripts_sha256'] and isinstance(commit, str) and len(commit) == 40 and all(c in '0123456789abcdef' for c in commit):
                result.update(tool_commit=commit, working_tree_dirty=False, commit_source='matching_packaged_stamp')
        except (OSError, ValueError, AttributeError):
            pass
    return result


def annotate(record):
    return {**record, 'rules_version': RULES_VERSION, 'producer': dict(producer())}


def compatibility(record):
    if not isinstance(record, dict):
        return {'status': 'invalid_record', 'reason': 'object required'}
    kind, version = record.get('kind'), record.get('schema_version')
    supported = FORMATS.get(kind) if isinstance(kind, str) else None
    if supported is None or type(version) is not int or version < 1 or version > supported:
        status = 'unsupported_format'
    elif 'rules_version' in record and record['rules_version'] not in KNOWN_RULES:
        status = 'unsupported_rules'
    elif version < supported or record.get('rules_version') != RULES_VERSION:
        status = 'legacy_recheck_required'
    elif (not isinstance(record.get('producer'), dict) or not isinstance(record['producer'].get('scripts_sha256'), str)
          or len(record['producer']['scripts_sha256']) != 64
          or any(c not in '0123456789abcdef' for c in record['producer']['scripts_sha256'])):
        status = 'unverified_producer'
    else:
        status = 'supported_current'
    return {'status': status, 'kind': kind, 'record_format_version': version,
            'supported_format_version': supported, 'record_rules_version': record.get('rules_version'),
            'current_rules_version': RULES_VERSION, 'producer': record.get('producer'),
            'limitation': 'Metadata identifies declared provenance, not an authenticated signature or proof of prior execution.'}


def require_readable(record):
    result = compatibility(record)
    if result['status'] in ('unsupported_format', 'unsupported_rules', 'invalid_record'):
        raise ValueError('Unsupported record version; use record_versions.py check: ' + result['status'])
    return result
