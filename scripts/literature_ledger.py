"""Merge evidence records and plan rechecks; no network or novelty certification."""
import argparse
from copy import deepcopy
from datetime import date
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from _records import fingerprint, read_json
from _static import emit


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
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Expected literature ledger schema_version=1')
    result = deepcopy(data)
    for kind in ('papers', 'claims', 'searches'):
        if not isinstance(result.get(kind), list):
            raise ValueError(kind + ' must be a list')
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
    return result


def merge(existing, incoming):
    base, addition = validate(existing), validate(incoming)
    papers, aliases, conflicts = deepcopy(base['papers']), dict(base.get('aliases', {})), list(base.get('conflicts', []))
    for candidate in addition['papers']:
        matches = [p for p in papers if p['id'] == candidate['id'] or
                   (p.get('doi') and p['doi'] == candidate.get('doi')) or p['url'] == candidate['url']]
        if not matches:
            papers.append(candidate)
            continue
        target = matches[0]
        critical = ('title', 'authors', 'doi', 'version', 'work_id')
        if len(matches) != 1 or any(target.get(k) != candidate.get(k) for k in critical):
            conflict = {'reason': 'identity_or_metadata_conflict', 'incoming': candidate,
                        'existing_ids': [p['id'] for p in matches]}
            if conflict not in conflicts:
                conflicts.append(conflict)
            continue
        if candidate['id'] != target['id']:
            aliases[candidate['id']] = target['id']
        if candidate['checked_at'] >= target['checked_at']:
            target['checked_at'] = candidate['checked_at']
            target['access'] = candidate['access']
    claims = deepcopy(base['claims'])
    for candidate in addition['claims']:
        candidate = deepcopy(candidate)
        candidate['paper_id'] = aliases.get(candidate['paper_id'], candidate['paper_id'])
        same = [c for c in claims if c['id'] == candidate['id']]
        if same and same[0] != candidate:
            conflict = {'reason': 'claim_id_conflict', 'incoming': candidate}
            if conflict not in conflicts:
                conflicts.append(conflict)
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
              'aliases': aliases, 'conflicts': conflicts, 'possible_version_pairs_to_review': possible_duplicates,
              'verification': 'Metadata/access/relation evidence are user-declared, not network-verified'}
    result['claim_audit'] = claim_audit(result)
    return result


def claim_audit(data):
    papers = {p['id']: p for p in data['papers']}
    blocked = {c['incoming']['id'] for c in data.get('conflicts', [])
               if c['reason'] == 'identity_or_metadata_conflict'}
    result = []
    for claim in data['claims']:
        paper_id = data.get('aliases', {}).get(claim['paper_id'], claim['paper_id'])
        paper = papers.get(paper_id)
        status = ('paper_identity_conflict' if claim['paper_id'] in blocked else
                  'missing_paper' if not paper else
                  'insufficient_method_access' if claim['kind'] == 'mechanism' and paper['access'] not in {'full_text', 'methods'}
                  else 'source_linked_human_verification_required')
        result.append({'claim_id': claim['id'], 'paper_id': paper_id, 'status': status,
                       'locator': claim['locator'], 'url': paper['url'] if paper else None})
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
