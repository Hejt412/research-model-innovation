"""Inventory research files without executing the project."""
from _static import SCHEMA, emit, inventory, parser


def main():
    p = parser(__doc__)
    args = p.parse_args()
    try:
        root, files, skipped, errors = inventory(args.root, args.max_bytes, args.exclude_dir)
    except ValueError as exc:
        p.error(str(exc))
    hints = {'model': ('model', 'network', 'backbone', 'mamba', 'transformer'),
             'training': ('train', 'finetune'), 'data': ('dataset', 'loader', 'preprocess'),
             'loss': ('loss', 'criterion'), 'evaluation': ('eval', 'test', 'metric'),
             'research_context': ('readme', 'agents.md', 'research_profile', 'research_history')}
    rows = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        labels = [role for role, words in hints.items() if any(word in rel.lower() for word in words)]
        if path.suffix.lower() in {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg'}:
            labels.append('configuration')
        rows.append({'path': rel, 'role_hints': labels})
    emit({'schema_version': SCHEMA, 'root': str(root), 'mode': 'static_no_project_execution',
          'files': rows, 'skipped': skipped, 'errors': errors,
          'limitations': ['Roles are path-based hints; inspect source.',
                          'Gitignore is not interpreted; use --exclude-dir as needed.']}, args.out)


if __name__ == '__main__':
    main()
