"""Trace one explicitly selected factory call into constructor inputs; never import the project."""
import argparse
import ast
import hashlib
from pathlib import Path
from _records import read_json, fingerprint
from _static import emit, source_tree, scope_nodes


class Unresolved(ValueError):
    pass


def value(node, env):
    """Small expression whitelist, not eval: no arbitrary calls/attributes/operators."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [value(n, env) for n in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = value(node.operand, env)
        if type(operand) in (int, float):
            return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.Dict) and all(k is not None for k in node.keys):
        return {value(k, env): value(v, env) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Attribute):
        base = value(node.value, env)
        if isinstance(base, dict) and node.attr in base:
            return base[node.attr]
    if isinstance(node, ast.Subscript):
        base, key = value(node.value, env), value(node.slice, env)
        if isinstance(base, dict) and key in base:
            return base[key]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get' and not node.keywords and 1 <= len(node.args) <= 2:
        base = value(node.func.value, env)
        if isinstance(base, dict):
            return base.get(value(node.args[0], env), value(node.args[1], env) if len(node.args) == 2 else None)
    if isinstance(node, ast.DictComp) and len(node.generators) == 1:
        gen = node.generators[0]
        if isinstance(gen.target, ast.Name) and not gen.ifs and not gen.is_async:
            items = value(gen.iter, env)
            if isinstance(items, list) and len(items) <= 512:
                return {value(node.key, {**env, gen.target.id: item}): value(node.value, {**env, gen.target.id: item}) for item in items}
    raise Unresolved('dynamic or unsupported expression')


def trace(factory_path, factory_name, model_path, class_name, config, config_param='cfg', constructor_name=None):
    if not isinstance(config, dict):
        raise ValueError('Provide a flat factory configuration object')
    _, ftree = source_tree(factory_path)
    _, mtree = source_tree(model_path)
    factories = [n for n in ftree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == factory_name]
    classes = [n for n in mtree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
    if len(factories) != 1 or len(classes) != 1:
        raise ValueError('Selected factory and class must each occur once at module scope')
    factory, cls = factories[0], classes[0]
    constructors = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
    if len(constructors) != 1:
        raise ValueError('Selected class needs an explicit, unambiguous __init__; inherited constructors remain unknown')
    call_name = constructor_name or class_name
    calls = [n for n in scope_nodes(factory) if isinstance(n, ast.Call) and ast.unparse(n.func) == call_name]
    if len(calls) != 1:
        raise ValueError('Select a factory with exactly one matching constructor call; use --constructor-name for an import alias')
    call, init = calls[0], constructors[0]
    env = {config_param: config}
    uncertain_context = bool(factory.decorator_list or cls.decorator_list or init.decorator_list or isinstance(factory, ast.AsyncFunctionDef))
    # Only straight-line assignments preceding the containing statement are read.
    for stmt in factory.body:
        if stmt.lineno >= call.lineno or any(n is call for n in ast.walk(stmt)):
            if not isinstance(stmt, (ast.Return, ast.Assign, ast.Expr)):
                uncertain_context = True
            break
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name = stmt.targets[0].id
            try:
                env[name] = value(stmt.value, env)
            except (Unresolved, TypeError, KeyError):
                env.pop(name, None)
        else:
            # Calls/branches can mutate config or rebind factory locals.
            uncertain_context = True
    positional = list(init.args.posonlyargs) + list(init.args.args)
    defaults = dict(zip([p.arg for p in positional][-len(init.args.defaults):], init.args.defaults)) if init.args.defaults else {}
    defaults.update({p.arg: d for p, d in zip(init.args.kwonlyargs, init.args.kw_defaults) if d is not None})
    params = [p.arg for p in positional[1:]] + [p.arg for p in init.args.kwonlyargs]
    passed, expressions, unknown_unpack = {}, {}, False
    for index, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred) or index >= len(positional) - 1:
            unknown_unpack = True
            break
        name = positional[index + 1].arg
        passed[name] = arg
        expressions[name] = ast.unparse(arg)
    for kw in call.keywords:
        if kw.arg is None:
            try:
                expanded = value(kw.value, env)
                if not isinstance(expanded, dict) or not all(isinstance(k, str) for k in expanded):
                    raise Unresolved()
                for name, item in expanded.items():
                    if name in passed:
                        unknown_unpack = True
                    passed[name] = ast.Constant(value=item)
                    expressions[name] = '**' + ast.unparse(kw.value)
            except (Unresolved, TypeError, KeyError):
                unknown_unpack = True
        else:
            if kw.arg in passed:
                unknown_unpack = True
            passed[kw.arg], expressions[kw.arg] = kw.value, ast.unparse(kw.value)
    binding_issues = []
    if not init.args.kwarg:
        binding_issues.extend('unexpected_keyword:' + name for name in sorted(set(passed) - set(params)))
    positional_only = {p.arg for p in init.args.posonlyargs[1:]}
    binding_issues.extend('positional_only_as_keyword:' + kw.arg for kw in call.keywords if kw.arg in positional_only)
    rows = []
    for name in params:
        node = passed.get(name, defaults.get(name))
        origin = 'forwarded' if name in passed else 'constructor_default' if name in defaults else 'required_unresolved'
        resolved = False
        result = None
        if node is not None and not unknown_unpack and not uncertain_context and not binding_issues:
            try:
                result = value(node, env if name in passed else {})
                resolved = True
            except (Unresolved, TypeError, KeyError):
                pass
        declared = name in config
        rows.append({'parameter': name, 'origin': origin, 'expression': expressions.get(name, ast.unparse(node) if node else None),
                     'declared_present': declared, 'declared_value': config.get(name),
                     'constructor_input_status': 'static_value' if resolved else 'unknown',
                     'constructor_input': result, 'declared_input_mismatch': declared and resolved and (type(result) is not type(config[name]) or result != config[name]),
                     'factory_line': call.lineno, 'constructor_line': init.lineno})
    return {'schema_version': 1, 'kind': 'config_flow_evidence', 'factory': factory_name, 'class': class_name,
            'factory_sha256': hashlib.sha256(factory_path.read_bytes()).hexdigest(),
            'model_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(), 'config_sha256': fingerprint(config),
            'parameters': rows, 'unknown_unpack': unknown_unpack, 'uncertain_factory_context': uncertain_context,
            'binding_issues': binding_issues,
            'unmatched_config_keys': sorted(set(config) - set(params)),
            'constructor_binding_verified': False, 'runtime_instance_verified': False,
            'limitations': ['The caller selects the factory/class binding; imports, aliases and decorators are not executed.',
                           'Constructor inputs are not final attributes: guards, internal overrides, inheritance and .to() effects need review.',
                           'Config keys may have aliases; unmatched keys do not prove they are unused.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--factory-file', type=Path, required=True)
    p.add_argument('--factory', required=True)
    p.add_argument('--model-file', type=Path, required=True)
    p.add_argument('--class-name', required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--config-param', default='cfg')
    p.add_argument('--constructor-name')
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        emit(trace(args.factory_file, args.factory, args.model_file, args.class_name, read_json(args.config), args.config_param, args.constructor_name), args.out)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
