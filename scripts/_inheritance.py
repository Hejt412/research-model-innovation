"""Expand unambiguous local single inheritance as source evidence, never runtime proof."""
import ast
from _dependencies import import_base, module_index


def enrich(rows, trees, import_roots):
    modules, names = module_index(trees, import_roots)
    index = {}
    nodes = {}
    for row in rows:
        index.setdefault((row['file'], row['class']), []).append(row)
    for file, tree in trees.items():
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                nodes[(file, node.name)] = node

    def parent_keys(row):
        file = row['file']
        node = nodes.get((file, row['class']))
        if node is None:
            return [], ['nested_or_ambiguous_class_scope']
        aliases = {}
        for item in trees[file].body:
            if isinstance(item, ast.Import):
                for name in item.names:
                    aliases[name.asname or name.name.split('.')[0]] = name.name if name.asname else name.name.split('.')[0]
            elif isinstance(item, ast.ImportFrom):
                base = import_base(item, file, names)
                if base is not None:
                    for name in item.names:
                        aliases[name.asname or name.name] = '.'.join(p for p in (base, name.name) if p)
        keys, unknown = [], []
        for base in node.bases:
            raw = ast.unparse(base)
            if (file, raw) in index:
                candidates = [(file, raw)]
            else:
                head, dot, tail = raw.partition('.')
                resolved = aliases.get(head, head) + (dot + tail if dot else '')
                module, _, symbol = resolved.rpartition('.')
                candidates = [(source, symbol) for source in modules.get(module, set()) if (source, symbol) in index]
            if len(candidates) == 1 and len(index[candidates[0]]) == 1:
                keys.append(candidates[0])
            else:
                unknown.append(raw)
        return keys, unknown

    active, done = set(), set()
    def expand(row):
        key = (row['file'], row['class'])
        if key in done:
            return
        if key in active:
            row['inheritance'] = {'status': 'unverified_cycle', 'ancestors': [], 'unresolved_bases': row['bases']}
            return
        active.add(key)
        parents, unknown = parent_keys(row)
        ancestors, inherited_assignments, inherited_methods = [], [], []
        status = 'local_single_inheritance_source_evidence'
        if len(row['bases']) > 1:
            status = 'unverified_multiple_inheritance'
        elif len(parents) == 1:
            parent = index[parents[0]][0]
            expand(parent)
            ancestors = [parents[0][0] + '::' + parents[0][1]] + parent.get('inheritance', {}).get('ancestors', [])
            inherited_assignments = parent.get('effective_assignments', parent['assignments'])
            inherited_methods = parent.get('effective_methods', parent['methods'])
            if parent.get('inheritance', {}).get('status', '').startswith('unverified'):
                status = 'unverified_parent_chain'
        elif row['bases']:
            status = 'unverified_external_or_unresolved_base'
        own_init = next((m for m in row['methods'] if m['name'] == '__init__'), None)
        if own_init and inherited_assignments:
            # A textual super call is only evidence; conditional calls/deletions remain unknown.
            has_super = any('super(' in c['call'] and '.__init__(' in c['call'] for c in own_init['calls_in_source_order'])
            if not has_super:
                inherited_assignments = []
                status = 'unverified_constructor_without_super'
        assignments = {a['target']: {**a, 'origin': a.get('origin', ancestors[0] if ancestors else '')}
                       for a in inherited_assignments}
        assignments.update({a['target']: {**a, 'origin': row['file'] + '::' + row['class']} for a in row['assignments']})
        methods = {m['name']: m for m in inherited_methods}
        methods.update({m['name']: {**m, 'origin': row['file'] + '::' + row['class']} for m in row['methods']})
        row['effective_assignments'] = list(assignments.values())
        row['effective_methods'] = list(methods.values())
        row['inheritance'] = {'status': status, 'ancestors': list(dict.fromkeys(ancestors)), 'unresolved_bases': unknown,
                              'limitation': 'Textual inheritance evidence only; dynamic construction, deletion and conditional super calls are not executed.'}
        active.remove(key)
        done.add(key)
    for row in rows:
        expand(row)
