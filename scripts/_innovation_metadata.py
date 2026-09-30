"""Validate declared mechanism identity; no semantic equivalence or benefit inference."""
import hashlib
from pathlib import Path
from _records import fingerprint, loads_json


FIELDS = {'schema_version', 'kind', 'research_id', 'innovation_id', 'gap_ids',
          'paper_ids', 'history_id', 'source_card_path', 'mechanism_fingerprint',
          'control', 'experiment'}
FINGERPRINT_FIELDS = {'location', 'transformation', 'data_dependencies', 'objective'}
LIMITATIONS = [
    'IDs and the source card are supplied association declarations requiring human review.',
    'Content hashes detect exact recorded content, not mathematical or conceptual equivalence.',
    'Mechanism identity linkage does not verify novelty, mechanism causality or performance benefit.'
]


def text(value, field, *, identity=False):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (identity and any(c.isspace() for c in value))):
        raise ValueError('Innovation metadata requires a nonempty string for ' + field)
    return value


def strings(value, field):
    if not isinstance(value, list) or not value:
        raise ValueError('Innovation metadata requires a nonempty list for ' + field)
    for item in value:
        text(item, field, identity=field.endswith('_ids'))
    if len(value) != len(set(value)):
        raise ValueError('Duplicate innovation metadata values for ' + field)


def exact_object(value, fields, field):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('Innovation metadata fields differ for ' + field + ': expected ' + ', '.join(sorted(fields)))


def validate(record, control, experiment):
    exact_object(record, FIELDS, 'root')
    if type(record['schema_version']) is not int or record['schema_version'] != 1 or record['kind'] != 'innovation_metadata':
        raise ValueError('Expected innovation_metadata schema_version=1')
    for field in ('research_id', 'innovation_id', 'history_id'):
        text(record[field], field, identity=True)
    for field in ('gap_ids', 'paper_ids'):
        strings(record[field], field)
    text(record['source_card_path'], 'source_card_path')
    mechanism = record['mechanism_fingerprint']
    exact_object(mechanism, FINGERPRINT_FIELDS, 'mechanism_fingerprint')
    for field in ('location', 'transformation', 'objective'):
        text(mechanism[field], 'mechanism_fingerprint.' + field)
    strings(mechanism['data_dependencies'], 'mechanism_fingerprint.data_dependencies')
    for role, manifest in (('control', control), ('experiment', experiment)):
        link = record[role]
        exact_object(link, {'experiment_id', 'manifest_sha256'}, role)
        text(link['experiment_id'], role + '.experiment_id', identity=True)
        digest = link['manifest_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Innovation metadata requires lowercase manifest SHA-256 for ' + role)
        if link['experiment_id'] != manifest['experiment_id'] or digest != manifest['manifest_sha256']:
            raise ValueError('Innovation metadata ' + role + ' identity does not match the supplied manifest')


def link(path, control, experiment):
    if path is None:
        return {'status': 'not_linked_manual_completion_required',
                'reason': 'Mechanism identity was not supplied; do not infer IDs from filenames or observations.',
                'mathematical_equivalence_verified': False}
    path = Path(path)
    raw = path.read_bytes()
    record = loads_json(raw.decode('utf-8-sig'))
    validate(record, control, experiment)
    card = (path.parent / record['source_card_path']).resolve()
    if not card.is_file():
        raise ValueError('Innovation source_card_path must identify an existing regular file')
    card_bytes = card.read_bytes()
    if not card_bytes:
        raise ValueError('Innovation source card must not be empty')
    return {'status': 'linked_declared_metadata_review_required',
            'metadata_path': str(path.resolve()),
            'metadata_file_sha256': hashlib.sha256(raw).hexdigest(),
            'metadata_record_sha256': fingerprint(record),
            'metadata': record,
            'source_card': {'path': str(card), 'sha256': hashlib.sha256(card_bytes).hexdigest()},
            'mechanism_fingerprint_sha256': fingerprint(record['mechanism_fingerprint']),
            'mathematical_equivalence_verified': False,
            'limitations': list(LIMITATIONS)}
