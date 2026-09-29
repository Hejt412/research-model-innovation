"""Index PyTorch module candidates, assignments and methods using Python AST."""
from _static import emit, parser, read_models


def main():
    p = parser(__doc__)
    p.add_argument('--import-root', action='append', help='Relative source root, e.g. src; repeat for multiple roots')
    args = p.parse_args()
    try:
        result = read_models(args.root, args.max_bytes, args.exclude_dir, args.import_root)
    except ValueError as exc:
        p.error(str(exc))
    emit(result, args.out)


if __name__ == '__main__':
    main()
