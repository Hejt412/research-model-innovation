"""Conservative local Python import graph; no target modules are imported."""
import ast
import hashlib
from pathlib import PurePosixPath


def digest(tree):
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def module_index(trees, import_roots=('.',)):
    modules, names = {}, {}
    for file in trees:
        for root in import_roots:
            try:
                relative = PurePosixPath(file).relative_to(PurePosixPath(root))
            except ValueError:
                continue
            parts = str(relative).removesuffix('.py').split('/')
            if parts[-1] == '__init__':
                parts.pop()
            name = '.'.join(parts)
            modules.setdefault(name, set()).add(file)
            names.setdefault(file, []).append(name)
    return modules, names


def import_base(node, file, names):
    module = (names.get(file) or [file.removesuffix('.py').replace('/', '.')])[0]
    package = module.split('.') if file.endswith('/__init__.py') else module.split('.')[:-1]
    if node.level:
        if node.level > len(package):
            return None
        prefix = package[:len(package)-node.level+1]
        return '.'.join(prefix + ([node.module] if node.module else []))
    return node.module or ''


def build_graph(trees, import_roots=('.',)):
    modules, names = module_index(trees, import_roots)
    graph, unknown = {}, {}
    for file, tree in trees.items():
        graph[file], unknown[file] = set(), set()

        def add_module(name):
            found = False
            # Include parent package initializers as they can affect imports.
            for end in range(1, len(name.split('.')) + 1):
                prefix = '.'.join(name.split('.')[:end])
                candidates = modules.get(prefix, set())
                if len(candidates) > 1:
                    unknown[file].add('ambiguous_import:' + prefix)
                    continue
                for target in candidates:
                    if prefix == name or target.endswith('/__init__.py'):
                        graph[file].add(target)
                        if prefix == name:
                            found = True
            return found

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    if not add_module(item.name):
                        unknown[file].add(item.name)
            elif isinstance(node, ast.ImportFrom):
                base = import_base(node, file, names)
                if base is None:
                    unknown[file].add('relative_import_beyond_root')
                    continue
                base_found = add_module(base)
                child_found = False
                for item in node.names:
                    child_found = add_module('.'.join(p for p in (base, item.name) if p)) or child_found
                    if item.name == '*':
                        unknown[file].add('wildcard:' + base)
                if not base_found and not child_found:
                    unknown[file].add(base or 'unresolved_relative_import')
            elif isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if func in {'__import__', 'eval', 'exec'} or func.endswith('.import_module'):
                    unknown[file].add('dynamic:' + func)
    return graph, unknown


def dependencies(file, trees, graph, unknown):
    todo, seen, unresolved = [file], set(), set()
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        unresolved.update(unknown.get(current, set()))
        todo.extend(graph.get(current, set()) - seen)
    return {'strategy': 'conservative_transitive_imports_and_whole_source_files',
            'files': {key: digest(trees[key]) for key in sorted(seen)},
            'unverified_imports': sorted(unresolved),
            'runtime_equivalence_verified': False}
