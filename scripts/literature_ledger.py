"""Merge evidence records and plan rechecks; no network or novelty certification."""
import argparse
from copy import deepcopy
from datetime import date
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from _records import fingerprint, read_json
from _static import emit
from _literature_identity import combine_aliases, identity_audit, resolve, retain


def doi(value):
    if not value:
        return None
    value = unquote(value.strip()).lower()
    value = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', value)
    if not re.fullmatch(r'10\.\d{4,9}/\S+', value):
        raise ValueError('Malformed DOI (syntax check only): ' + value)
    return value


def web_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Expected a direct http(s) source URL')
    return value


def validate(data):
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Expected literature ledger schema_version=1')
    result = deepcopy(data)
    for kind in ('papers', 'claims', 'searches'):
        if not isinstance(result.get(kind), list):
            raise ValueError(kind + ' must be a list')
    aliases = result.get('aliases', {})
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                                               for k, v in aliases.items()):
        raise ValueError('aliases must map nonempty IDs to nonempty IDs')
    conflicts = result.get('conflicts', [])
    if not isinstance(conflicts, list):
        raise ValueError('conflicts must be a list')
    for conflict in conflicts:
        if not isinstance(conflict, dict) or not isinstance(conflict.get('reason'), str):
            raise ValueError('Each conflict requires a reason')
        if conflict['reason'] in ('identity_or_metadata_conflict', 'claim_id_conflict'):
            if not isinstance(conflict.get('incoming'), dict) or not isinstance(conflict['incoming'].get('id'), str):
                raise ValueError('Identity/claim conflict requires incoming ID')
        if conflict['reason'] == 'identity_or_metadata_conflict':
            if not isinstance(conflict.get('existing_ids', []), list) or not all(isinstance(v, str) for v in conflict.get('existing_ids', [])):
                raise ValueError('existing_ids must be a list of IDs')
        if conflict['reason'] == 'alias_target_conflict':
            if (not isinstance(conflict.get('alias'), str) or not conflict['alias']
                    or not isinstance(conflict.get('targets'), list) or len(conflict['targets']) < 2
                    or not all(isinstance(v, str) and v for v in conflict['targets'])):
                raise ValueError('Alias conflict requires alias and competing targets')
    seen = set()
    for paper in result['papers']:
        for key in ('id', 'title', 'url', 'version', 'access', 'checked_at'):
            if not isinstance(paper.get(key), str) or not paper[key].strip():
                raise ValueError('Paper requires nonempty ' + key)
        if paper['id'] in seen:
            raise ValueError('Duplicate paper ID: ' + paper['id'])
        seen.add(paper['id'])
        if not isinstance(paper.get('authors'), list) or not paper['authors'] or not all(isinstance(a, str) and a.strip() for a in paper['authors']):
            raise ValueError('Paper authors must be a nonempty string list')
        paper['doi'] = doi(paper.get('doi'))
        web_url(paper['url'])
        date.fromisoformat(paper['checked_at'])
        if paper['access'] not in {'full_text', 'methods', 'abstract_only', 'metadata_only'}:
            raise ValueError('Unsupported access level')
        if paper.get('work_id') and not paper.get('relation_evidence'):
            raise ValueError('Explicit version grouping requires relation_evidence URL')
        if paper.get('relation_evidence'):
            web_url(paper['relation_evidence'])
    for search in result['searches']:
        if search.get('stage') not in {'cross_domain', 'same_domain'}:
            raise ValueError('Search stage must be cross_domain or same_domain')
        if not all(isinstance(search.get(k), str) and search[k].strip() for k in ('query', 'source', 'date')):
            raise ValueError('Search requires query/source/date')
        date.fromisoformat(search['date'])
    claim_ids = set()
    for claim in result['claims']:
        if not all(isinstance(claim.get(k), str) and claim[k].strip() for k in ('id', 'text', 'paper_id', 'locator')):
            raise ValueError('Claim requires id/text/paper_id/locator')
        if claim.get('kind') not in {'mechanism', 'metadata'}:
            raise ValueError('Claim kind must be mechanism or metadata')
        if claim['id'] in claim_ids:
            raise ValueError('Duplicate claim ID: ' + claim['id'])
        claim_ids.add(claim['id'])
        if 'source_paper_id' in claim and (not isinstance(claim['source_paper_id'], str) or not claim['source_paper_id'].strip()):
            raise ValueError('source_paper_id must be a nonempty ID')
    return result


def merge(existing, incoming):
    base, addition = validate(existing), validate(incoming)
    papers, conflicts = deepcopy(base['papers']), deepcopy(base.get('conflicts', []))
    for conflict in addition.get('conflicts', []):
        retain(conflicts, conflict)
    aliases = combine_aliases(base.get('aliases', {}), addition.get('aliases', {}), conflicts)
    for candidate in addition['papers']:
        resolved_id, alias_path = resolve(candidate['id'], aliases)
        matches = [p for p in papers if p['id'] in (candidate['id'], resolved_id) or
                   (p.get('doi') and p['doi'] == candidate.get('doi')) or p['url'] == candidate['url']]
        if candidate['id'] in aliases and (resolved_id is None or not any(p['id'] == resolved_id for p in matches)):
            retain(conflicts, {'reason': 'identity_or_metadata_conflict', 'incoming': candidate,
                              'existing_ids': sorted(set(alias_path + ([resolved_id] if resolved_id else [])))})
            continue
        if not matches:
            papers.append(candidate)
            continue
        target = matches[0]
        critical = ('title', 'authors', 'doi', 'version', 'work_id')
        if len(matches) != 1 or any(target.get(k) != candidate.get(k) for k in critical):
            conflict = {'reason': 'identity_or_metadata_conflict', 'incoming': candidate,
                        'existing_ids': [p['id'] for p in matches]}
            retain(conflicts, conflict)
            continue
        if candidate['id'] != target['id']:
            # A compatible existing chain already identifies this paper.
            if candidate['id'] not in aliases:
                aliases = combine_aliases(aliases, {candidate['id']: target['id']}, conflicts)
        if candidate['checked_at'] >= target['checked_at']:
            target['checked_at'] = candidate['checked_at']
            target['access'] = candidate['access']
    alias_audit, blocked = identity_audit(papers, aliases, conflicts)
    claims = []
    for candidate in [*base['claims'], *addition['claims']]:
        candidate = deepcopy(candidate)
        original_id = candidate.get('source_paper_id', candidate['paper_id'])
        target_id, _ = resolve(original_id, aliases)
        if original_id not in blocked and candidate['paper_id'] not in blocked and target_id is not None:
            if candidate['paper_id'] != target_id:
                candidate['source_paper_id'] = original_id
                candidate['paper_id'] = target_id
        same = [c for c in claims if c['id'] == candidate['id']]
        if same and same[0] != candidate:
            conflict = {'reason': 'claim_id_conflict', 'incoming': candidate}
            retain(conflicts, conflict)
        elif not same:
            claims.append(candidate)
    searches = list(base['searches'])
    for row in addition['searches']:
        if row not in searches:
            searches.append(row)
    possible_duplicates = []
    for i, left in enumerate(papers):
        for right in papers[i+1:]:
            normalize = lambda text: re.sub(r'\W+', '', text.casefold())
            if normalize(left['title']) == normalize(right['title']) and left.get('work_id') != right.get('work_id'):
                possible_duplicates.append([left['id'], right['id']])
            elif normalize(left['title']) == normalize(right['title']) and not left.get('work_id'):
                possible_duplicates.append([left['id'], right['id']])
    works = {}
    for paper in papers:
        if paper.get('work_id'):
            group = works.setdefault(paper['work_id'], {'version_ids': [], 'relation_evidence': []})
            group['version_ids'].append(paper['id'])
            if paper['relation_evidence'] not in group['relation_evidence']:
                group['relation_evidence'].append(paper['relation_evidence'])
    result = {'schema_version': 1, 'papers': papers, 'claims': claims, 'searches': searches, 'works': works,
              'aliases': aliases, 'alias_audit': alias_audit, 'conflicts': conflicts, 'possible_version_pairs_to_review': possible_duplicates,
              'verification': 'Metadata/access/relation evidence are user-declared, not network-verified'}
    result['claim_audit'] = claim_audit(result)
    return result


def claim_audit(data):
    papers = {p['id']: p for p in data['papers']}
    _, blocked = identity_audit(data['papers'], data.get('aliases', {}), data.get('conflicts', []))
    claim_conflicts = {c['incoming']['id'] for c in data.get('conflicts', []) if c['reason'] == 'claim_id_conflict'}
    result = []
    for claim in data['claims']:
        original_id = claim.get('source_paper_id', claim['paper_id'])
        paper_id, _ = resolve(original_id, data.get('aliases', {}))
        paper = papers.get(paper_id)
        status = ('claim_identity_conflict' if claim['id'] in claim_conflicts else
                  'paper_identity_conflict' if original_id in blocked or claim['paper_id'] in blocked else
                  'missing_paper' if not paper else
                  'insufficient_method_access' if claim['kind'] == 'mechanism' and paper['access'] not in {'full_text', 'methods'}
                  else 'source_linked_human_verification_required')
        conflicted = status in ('claim_identity_conflict', 'paper_identity_conflict')
        result.append({'claim_id': claim['id'], 'paper_id': None if conflicted else paper_id,
                       'source_paper_id': original_id, 'status': status,
                       'locator': claim['locator'], 'url': paper['url'] if paper and not conflicted else None})
    return result


def plan(data, as_of, age_days):
    if age_days < 0:
        raise ValueError('max-age-days must be nonnegative')
    data = validate(data)
    if any(date.fromisoformat(p['checked_at']) > as_of for p in data['papers']):
        raise ValueError('Paper checked_at is later than as-of')
    latest = {}
    for row in data['searches']:
        when = date.fromisoformat(row['date'])
        if when > as_of:
            raise ValueError('Search date is later than as-of')
        key = (row['stage'], row['source'], row['query'])
        if key not in latest or row['date'] > latest[key]['date']:
            latest[key] = row
    return {'as_of': as_of.isoformat(), 'recheck_papers': [p['id'] for p in data['papers']
              if (as_of-date.fromisoformat(p['checked_at'])).days >= age_days],
            'incremental_queries': [{**row, 'last_searched': row['date'], 'search_through': as_of.isoformat(),
                                     'date_lower_bound': None if row['stage'] == 'same_domain' else row['date'],
                                     'note': 'Same-domain prior art keeps historical coverage; also revisit terminology.'}
                                    for row in latest.values()],
            'ledger_sha256': fingerprint(data), 'network_search_executed': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    combine = sub.add_parser('merge')
    combine.add_argument('existing', type=Path)
    combine.add_argument('incoming', type=Path)
    refresh = sub.add_parser('plan')
    refresh.add_argument('ledger', type=Path)
    refresh.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    refresh.add_argument('--max-age-days', type=int, default=90)
    for command in (combine, refresh):
        command.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        result = (merge(read_json(args.existing), read_json(args.incoming)) if args.command == 'merge'
                  else plan(read_json(args.ledger), args.as_of, args.max_age_days))
        emit(result, args.out)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
