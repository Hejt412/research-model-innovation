"""USER-RUN ONLY: import a reviewed factory and record attributes, without forward or training.

Imports and constructors can have side effects. Review the selected factory first.
Codex must not run this script against the user's ML project.
"""
import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import platform


def read_attribute(instance, path):
    current = instance
    for part in path.split('.'):
        if not part or part.startswith('_'):
            raise ValueError('Use public attribute names or numeric indices')
        current = current[int(part)] if part.isdigit() else getattr(current, part)
    if current is None or type(current) in (bool, int, float, str):
        return current
    return {'type': type(current).__module__ + '.' + type(current).__qualname__, 'value': 'not_serialized'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--factory', required=True, help='Reviewed module:function, called with JSON keyword arguments')
    p.add_argument('--kwargs', type=Path, required=True)
    p.add_argument('--attribute', action='append', default=[])
    p.add_argument('--source-file', type=Path, action='append', default=[], help='Additional reviewed dependency to fingerprint')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--execute-reviewed-factory', action='store_true')
    args = p.parse_args()
    if not args.execute_reviewed_factory:
        p.error('Factory was not imported. Review its side effects, then explicitly use --execute-reviewed-factory in your environment.')
    module, name = args.factory.split(':', 1)
    kwargs_bytes = args.kwargs.read_bytes()
    kwargs = json.loads(kwargs_bytes.decode('utf-8-sig'))
    if not isinstance(kwargs, dict):
        p.error('kwargs must be a JSON object')
    loaded_module = importlib.import_module(module)
    factory = getattr(loaded_module, name)
    instance = factory(**kwargs)
    attributes = {}
    for path in args.attribute:
        try:
            attributes[path] = {'status': 'observed', 'value': read_attribute(instance, path)}
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            attributes[path] = {'status': 'unresolved', 'reason': str(exc)}
    paths = list(args.source_file)
    for obj in (factory, type(instance)):
        try:
            source = inspect.getsourcefile(obj)
            if source:
                paths.append(Path(source))
        except TypeError:
            pass
    source_hashes = {}
    for path in paths:
        try:
            source_hashes[str(path.resolve())] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        except OSError as exc:
            source_hashes[str(path)] = {'status': 'unreadable', 'reason': str(exc)}
    report = {'kind': 'user_run_instance_observation', 'factory': args.factory, 'python': platform.python_version(),
              'kwargs_sha256': hashlib.sha256(kwargs_bytes).hexdigest(),
              'instance_class': type(instance).__module__ + '.' + type(instance).__qualname__, 'attributes': attributes,
              'source_files': source_hashes, 'dependency_closure_verified': False,
              'script_called_forward_or_training': False,
              'limitation': 'Factory/import/property side effects and source provenance require independent review.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
