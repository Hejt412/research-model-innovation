"""Extract Python config evidence and declarative config locations, not runtime values."""
import ast
import re
from _static import SCHEMA, emit, expr, inventory, parser, source_tree

KEY = re.compile(r'(?i)(seed|shot|way|query|episode|epoch|batch|learning.?rate|\blr\b|optimizer|scheduler|weight.?decay|split|window|stride|domain|dataset|augment|loss|metric|checkpoint)')


def main():
    p = parser(__doc__)
    args = p.parse_args()
    try:
        root, files, skipped, errors = inventory(args.root, args.max_bytes, args.exclude_dir)
    except ValueError as exc:
        p.error(str(exc))
    evidence, configs = [], []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            if path.suffix.lower() == '.py':
                _, tree = source_tree(path)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        target = ', '.join(expr(t) for t in targets)
                        expression = expr(node.value)
                        if KEY.search(target + ' ' + (expression or '')):
                            evidence.append({'file': rel, 'line': node.lineno, 'kind': 'assignment',
                                             'target': target, 'expression': expression})
                    elif isinstance(node, ast.Call):
                        function = expr(node.func)
                        if function.endswith('.add_argument') or KEY.search(function):
                            evidence.append({'file': rel, 'line': node.lineno, 'kind': 'call',
                                             'expression': expr(node)})
            elif path.suffix.lower() in {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg'}:
                configs.append(rel)
                for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                    if KEY.search(line):
                        evidence.append({'file': rel, 'line': number, 'kind': 'config_text',
                                         'expression': line})
        except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
            errors.append({'path': rel, 'error': str(exc)})
    evidence.sort(key=lambda row: (row['file'], row['line'], row['kind']))
    emit({'schema_version': SCHEMA, 'root': str(root), 'mode': 'static_no_project_execution',
          'config_files': configs, 'evidence': evidence, 'skipped': skipped, 'errors': errors,
          'limitations': ['Expressions are unevaluated; CLI/env/config composition may override them.',
                          'Declarative config is indexed as text, not flattened or resolved.',
                          'Keyword matching can miss abbreviations; review training/data/evaluation source.']}, args.out)


if __name__ == '__main__':
    main()
