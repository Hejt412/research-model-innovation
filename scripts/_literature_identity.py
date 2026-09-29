"""Conservative alias resolution for local literature records."""
from copy import deepcopy


def retain(rows, item):
    if item not in rows:
        rows.append(deepcopy(item))


def resolve(identity, aliases):
    path = []
    while identity in aliases:
        if identity in path:
            return None, path
        path.append(identity)
        identity = aliases[identity]
    return identity, path


def combine_aliases(left, right, conflicts):
    aliases = dict(left)
    for identity, target in right.items():
        if identity in aliases and aliases[identity] != target:
            # Keep both assertions in a conflict; never silently overwrite.
            targets = sorted({aliases[identity], target})
            retain(conflicts, {'reason': 'alias_target_conflict', 'alias': identity, 'targets': targets})
        else:
            aliases[identity] = target
    return aliases


def identity_audit(papers, aliases, conflicts):
    paper_ids = {paper['id'] for paper in papers}
    blocked = set()
    disputed_aliases = set()
    edges = [(name, target) for name, target in aliases.items()]
    for conflict in conflicts:
        reason = conflict['reason']
        if reason == 'identity_or_metadata_conflict':
            blocked.add(conflict['incoming']['id'])
            blocked.update(conflict.get('existing_ids', []))
        elif reason == 'alias_target_conflict':
            disputed_aliases.add(conflict['alias'])
            blocked.add(conflict['alias'])
            blocked.update(conflict['targets'])
            edges.extend((conflict['alias'], target) for target in conflict['targets'])
    rows = []
    for identity in sorted(aliases):
        target, path = resolve(identity, aliases)
        status = ('alias_target_conflict' if identity in disputed_aliases else
                  'paper_id_collision' if identity in paper_ids else
                  'alias_cycle' if target is None else
                  'missing_target' if target not in paper_ids else 'resolved')
        if status != 'resolved':
            blocked.update(path)
            blocked.add(identity)
            if target is not None:
                blocked.add(target)
        rows.append({'alias': identity, 'target': target, 'path': path, 'status': status})
    # Any path through an unresolved identity remains unusable, including
    # claims normalized by an older ledger that no longer retains the alias.
    changed = True
    while changed:
        changed = False
        for left, right in edges:
            if (left in blocked or right in blocked) and not {left, right} <= blocked:
                blocked.update((left, right))
                changed = True
    for row in rows:
        if row['status'] == 'resolved' and row['alias'] in blocked:
            row['status'] = 'identity_conflict'
    return rows, blocked
