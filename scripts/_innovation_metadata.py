"""Validate declared mechanism identity; no semantic equivalence or benefit inference."""
import hashlib
import json
from pathlib import Path
from _records import fingerprint, loads_json


FIELDS = {'schema_version', 'kind', 'research_id', 'innovation_id', 'gap_ids',
          'paper_ids', 'history_id', 'source_card_path', 'mechanism_fingerprint',
          'control', 'experiment'}
LITERATURE_STATUSES = {'references_declared', 'pending_search', 'unknown'}
HISTORY_EVIDENCE_VERSION = 1
FINGERPRINT_FIELDS = {'location', 'transformation', 'data_dependencies', 'objective'}
LIMITATIONS = [
    'IDs and the source card are supplied association declarations requiring human review.',
    'Content hashes detect exact recorded content, not mathematical or conceptual equivalence.',
    'Mechanism identity linkage does not verify novelty, mechanism causality or performance benefit.'
]


def text(value, field, *, identity=False, reject_unknown=False):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (identity and any(c.isspace() for c in value))
            or (reject_unknown and value.casefold() == 'unknown')):
        raise ValueError('Innovation metadata requires a nonempty string for ' + field)
    return value


def strings(value, field, *, allow_empty=False, reject_unknown=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError('Innovation metadata requires a nonempty list for ' + field)
    for item in value:
        text(item, field, identity=field.endswith('_ids'), reject_unknown=reject_unknown)
    if len(value) != len(set(value)):
        raise ValueError('Duplicate innovation metadata values for ' + field)


def exact_object(value, fields, field):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('Innovation metadata fields differ for ' + field + ': expected ' + ', '.join(sorted(fields)))


def validate(record, control, experiment):
    if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
            or record['schema_version'] not in (1, 2) or record.get('kind') != 'innovation_metadata'):
        raise ValueError('Expected innovation_metadata schema_version=1 or 2')
    version = record['schema_version']
    exact_object(record, FIELDS | ({'literature_status'} if version == 2 else set()), 'root')
    for field in ('research_id', 'innovation_id', 'history_id'):
        text(record[field], field, identity=True, reject_unknown=version == 2)
    strings(record['gap_ids'], 'gap_ids', reject_unknown=version == 2)
    strings(record['paper_ids'], 'paper_ids', allow_empty=version == 2, reject_unknown=version == 2)
    if version == 2:
        status = record['literature_status']
        if not isinstance(status, str) or status not in LITERATURE_STATUSES:
            raise ValueError('Unsupported innovation literature_status')
        if bool(record['paper_ids']) != (status == 'references_declared'):
            raise ValueError('references_declared requires paper IDs; pending_search/unknown require paper_ids=[]')
    text(record['source_card_path'], 'source_card_path')
    mechanism = record['mechanism_fingerprint']
    exact_object(mechanism, FINGERPRINT_FIELDS, 'mechanism_fingerprint')
    for field in ('location', 'transformation', 'objective'):
        text(mechanism[field], 'mechanism_fingerprint.' + field)
    strings(mechanism['data_dependencies'], 'mechanism_fingerprint.data_dependencies')
    for role, manifest in (('control', control), ('experiment', experiment)):
        link = record[role]
        exact_object(link, {'experiment_id', 'manifest_sha256'}, role)
        text(link['experiment_id'], role + '.experiment_id', identity=True, reject_unknown=version == 2)
        digest = link['manifest_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Innovation metadata requires lowercase manifest SHA-256 for ' + role)
        if link['experiment_id'] != manifest['experiment_id'] or digest != manifest['manifest_sha256']:
            raise ValueError('Innovation metadata ' + role + ' identity does not match the supplied manifest')


def metadata_history_evidence(raw, record):
    """Omit only the root card locator value; preserve all other original bytes.

    A JSON reformat, BOM/newline change, or edit to any other declared content
    still changes this hash. The strict record has already been validated.
    """
    source = raw.decode('utf-8')
    decoder = json.JSONDecoder()

    def space(index):
        while index < len(source) and source[index] in ' \t\r\n':
            index += 1
        return index

    index = space(1 if source.startswith('\ufeff') else 0) + 1  # Root opening brace.
    while source[space(index)] != '}':
        key, end = decoder.raw_decode(source, space(index))
        start = space(space(end) + 1)  # Colon, then value.
        _, end = decoder.raw_decode(source, start)
        if key == 'source_card_path':
            normalized = source[:start] + '"<source_card_locator>"' + source[end:]
            return {'version': HISTORY_EVIDENCE_VERSION,
                    'metadata_file_without_card_locator_sha256': hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
                    'metadata_record_without_card_locator_sha256': fingerprint({k: v for k, v in record.items() if k != key})}
        index = space(end) + 1  # Comma.
    raise ValueError('Missing source_card_path in validated metadata')


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
    references_declared = bool(record['paper_ids'])
    return {'status': ('linked_declared_metadata_review_required' if references_declared
                       else 'partially_linked_declared_metadata_review_required'),
            'association_completeness': 'complete_declared' if references_declared else 'partial_declared',
            'literature_status': record.get('literature_status', 'references_declared'),
            'literature_verification': 'not_verified_by_tool',
            'metadata_path': str(path.resolve()),
            'metadata_file_sha256': hashlib.sha256(raw).hexdigest(),
            'metadata_record_sha256': fingerprint(record),
            'history_evidence': metadata_history_evidence(raw, record),
            'metadata': record,
            'source_card': {'path': str(card), 'sha256': hashlib.sha256(card_bytes).hexdigest()},
            'mechanism_fingerprint_sha256': fingerprint(record['mechanism_fingerprint']),
            'mathematical_equivalence_verified': False,
            'limitations': list(LIMITATIONS)}
