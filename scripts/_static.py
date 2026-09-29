"""Read-only source analysis. Never import or evaluate target project code."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tokenize
from _dependencies import build_graph, dependencies

SCHEMA = 2
SKIP = {'.git', '.hg', '.svn', '.venv', 'venv', 'env', '__pycache__',
        'node_modules', 'site-packages', 'checkpoints', 'wandb', 'outputs',
        'dist', 'build', '.mypy_cache', '.pytest_cache'}
SUFFIXES = {'.py', '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.md'}


def parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('root', type=Path)
    p.add_argument('--out', type=Path, help='Optional JSON output, otherwise stdout')
    p.add_argument('--max-bytes', type=int, default=2_000_000)
    p.add_argument('--exclude-dir', action='append', default=[])
    return p


def emit(data, out=None):
    content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding='utf-8')
    else:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(content, end='')


def inventory(root, max_bytes=2_000_000, exclude_dirs=()):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('root must be an existing project directory')
    if max_bytes <= 0:
        raise ValueError('max-bytes must be positive')
    files, skipped, errors = [], [], []
    excluded = SKIP | set(exclude_dirs)

    def walk_error(error):
        errors.append({'path': str(error.filename), 'error': str(error)})

    for base, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        kept = []
        for name in sorted(dirs):
            path = Path(base) / name
            if name in excluded or path.is_symlink() or path.is_junction():
                skipped.append({'path': path.relative_to(root).as_posix(),
                                'reason': 'excluded_directory_or_link'})
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = Path(base) / name
            if path.suffix.lower() not in SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            try:
                if path.is_symlink():
                    skipped.append({'path': relative, 'reason': 'symlink'})
                elif path.stat().st_size > max_bytes:
                    skipped.append({'path': relative, 'reason': 'size_limit'})
                else:
                    files.append(path)
            except OSError as exc:
                errors.append({'path': relative, 'error': str(exc)})
    return root, sorted(files), skipped, errors


def source_tree(path):
    with tokenize.open(path) as handle:
        source = handle.read()
    return source, ast.parse(source, filename=str(path))


def expr(node):
    return ast.unparse(node) if node is not None else None


def scope_nodes(root):
    """Visit one lexical body without attributing nested functions/classes to it."""
    pending = list(reversed(list(ast.iter_child_nodes(root))))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(reversed(list(ast.iter_child_nodes(node))))


def alias_map(tree):
    aliases = {}
    for node in scope_nodes(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = (
                    item.name if item.asname else item.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = '.'.join(
                    part for part in [node.module, item.name] if part)
    return aliases


def resolved(node, aliases):
    value = expr(node)
    first, dot, rest = value.partition('.')
    return aliases.get(first, first) + (dot + rest if dot else '')


def models(path, relative=None):
    source, tree = source_tree(path)
    aliases = alias_map(tree)
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    # Same-file inheritance is a hint; scope shadowing/cross-file inheritance
    # cannot be proven by this deliberately bounded static scan.
    detected = {n.name for n in classes if any(
        resolved(base, aliases) in {'torch.nn.Module', 'torch.nn.modules.module.Module'}
        for base in n.bases)}
    changed = True
    while changed:
        before = set(detected)
        for node in classes:
            if any(expr(base) in detected for base in node.bases):
                detected.add(node.name)
        changed = before != detected
    result = []
    for node in classes:
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        has_forward = any(n.name == 'forward' for n in methods)
        if node.name not in detected and not has_forward:
            continue
        method_rows, assignments = [], []
        for method in methods:
            calls = sorted((n for n in scope_nodes(method) if isinstance(n, ast.Call)),
                           key=lambda n: (n.lineno, n.col_offset))
            method_rows.append({
                'name': method.name, 'line': method.lineno,
                'end_line': method.end_lineno, 'arguments': expr(method.args),
                'calls_in_source_order': [{'line': n.lineno, 'call': expr(n)} for n in calls],
                'returns': [{'line': n.lineno, 'expression': expr(n.value)}
                            for n in scope_nodes(method) if isinstance(n, ast.Return)]})
            for item in scope_nodes(method):
                targets = item.targets if isinstance(item, ast.Assign) else (
                    [item.target] if isinstance(item, ast.AnnAssign) else [])
                for target in targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                        assignments.append({'line': item.lineno, 'target': expr(target),
                                            'expression': expr(item.value)})
        normalized = ast.dump(node, include_attributes=False)
        result.append({'file': relative or str(path), 'class': node.name,
                       'line': node.lineno, 'end_line': node.end_lineno,
                       'bases': [resolved(b, aliases) for b in node.bases],
                       'detection': 'module_or_same_file_subclass_hint' if node.name in detected else 'forward_method_candidate',
                       'assignments': assignments, 'methods': method_rows,
                       'ast_sha256': hashlib.sha256(normalized.encode()).hexdigest(),
                       'parameters_total': None, 'parameters_trainable': None})
    return result


def read_models(root, max_bytes, exclude_dirs):
    root, files, skipped, errors = inventory(root, max_bytes, exclude_dirs)
    rows, trees = [], {}
    for path in files:
        if path.suffix.lower() != '.py':
            continue
        try:
            _, trees[path.relative_to(root).as_posix()] = source_tree(path)
            rows.extend(models(path, path.relative_to(root).as_posix()))
        except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
            errors.append({'path': path.relative_to(root).as_posix(), 'error': str(exc)})
    graph, unknown = build_graph(trees)
    for row in rows:
        row['dependencies'] = dependencies(row['file'], trees, graph, unknown)
        row['dependencies']['scan_incomplete'] = bool(errors or skipped)
    source_files = {key: {'imports': sorted(graph[key]), 'unverified_imports': sorted(unknown[key])}
                    for key in sorted(trees)}
    return {'schema_version': SCHEMA, 'root': str(root), 'mode': 'static_no_project_execution',
            'limitations': ['Candidate detection, not complete runtime architecture.',
                            'Calls are source order, not execution flow.',
                            'Shapes, parameters and FLOPs are not measured.',
                            'Gitignore is not interpreted; exclusions and skipped files are reported.'],
            'models': rows, 'source_files': source_files, 'skipped': skipped, 'errors': errors}
