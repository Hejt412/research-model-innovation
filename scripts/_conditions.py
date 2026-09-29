"""Preserve lexical branch guards without evaluating target expressions."""
import ast


def guarded_nodes(root):
    def walk(node, guards):
        yield node, guards
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.If):
            for branch, body in (('then', node.body), ('else', node.orelse)):
                guard = {'kind': 'if', 'line': node.lineno, 'test': ast.unparse(node.test), 'branch': branch}
                for child in body:
                    yield from walk(child, guards + [guard])
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.TryStar, ast.Match)):
            # Context records alternatives, not a guessed executable predicate.
            for field, value in ast.iter_fields(node):
                if field in ('body', 'orelse', 'finalbody', 'handlers', 'cases'):
                    for child in value:
                        yield from walk(child, guards + [{'kind': type(node).__name__, 'line': node.lineno, 'branch': field}])
        else:
            for child in ast.iter_child_nodes(node):
                yield from walk(child, guards)
    for child in root.body:
        yield from walk(child, [])
