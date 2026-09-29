"""Trace one explicitly selected factory call into constructor inputs; never import the project."""
import argparse
import ast
import hashlib
from pathlib import Path
from _records import read_json, fingerprint
from _static import emit, source_tree, scope_nodes
from _versions import annotate
from _call_binding import bind_constructor


class Unresolved(ValueError):
    pass


def value(node, env):
    """Small expression whitelist, not eval: no arbitrary calls/attributes/operators."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.List):
        return [value(n, env) for n in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(value(n, env) for n in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = value(node.operand, env)
        if type(operand) in (int, float):
            return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.Dict) and all(k is not None for k in node.keys):
        return {value(k, env): value(v, env) for k, v in zip(node.keys, node.values)}
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
            if isinstance(items, (list, tuple)) and len(items) <= 512:
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
    side_effects = []
    scope_limitations = [
        {'line': node.lineno, 'kind': type(node).__name__, 'reason': 'unresolved_comprehension_scope'}
        for node in scope_nodes(factory)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        and any(child is call for child in ast.walk(node))]
    uncertain_context = uncertain_context or bool(scope_limitations)

    def possible_effects(expression):
        # Whitelisted cfg.get on a supplied plain JSON mapping is read-only.
        # All other calls, assignment expressions, yields and awaits can affect
        # subsequent argument reads. Do not execute them to find out.
        found = []
        safe_attributes = set()
        for node in ast.walk(expression):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                try:
                    if isinstance(value(node.func.value, env), dict) and not node.keywords and 1 <= len(node.args) <= 2:
                        safe_attributes.add(id(node.func))
                except (Unresolved, TypeError, KeyError):
                    pass
        for node in ast.walk(expression):
            if isinstance(node, ast.Call):
                safe = id(node.func) in safe_attributes
                if not safe:
                    found.append({'line': node.lineno, 'expression': ast.unparse(node), 'reason': 'call_may_mutate_state'})
            elif isinstance(node, (ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom)):
                found.append({'line': node.lineno, 'expression': ast.unparse(node), 'reason': 'stateful_expression'})
            elif isinstance(node, ast.Attribute) and id(node) not in safe_attributes:
                found.append({'line': node.lineno, 'expression': ast.unparse(node), 'reason': 'unverified_attribute_access'})
        return found
    # Only straight-line assignments preceding the containing statement are read.
    containing_statement = None
    for stmt in factory.body:
        # AST body order distinguishes semicolon-separated statements, even
        # when they share a line with the selected call.
        if any(n is call for n in ast.walk(stmt)):
            containing_statement = stmt
            if not isinstance(stmt, (ast.Return, ast.Assign, ast.Expr)):
                uncertain_context = True
            break
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            effects = possible_effects(stmt.value)
            side_effects.extend(effects)
            uncertain_context = uncertain_context or bool(effects)
            name = stmt.targets[0].id
            try:
                env[name] = value(stmt.value, env)
            except (Unresolved, TypeError, KeyError):
                env.pop(name, None)
                uncertain_context = True
        else:
            # Calls/branches can mutate config or rebind factory locals.
            uncertain_context = True
    # Conservatively taint the entire call when any argument can mutate state;
    # this also covers positional expressions and **build_kwargs(cfg).
    for expression in [*call.args, *(kw.value for kw in call.keywords)]:
        effects = possible_effects(expression)
        side_effects.extend(effects)
        uncertain_context = uncertain_context or bool(effects)
    if containing_statement is not None:
        inside_call = {id(n) for n in ast.walk(call)}
        for node in ast.walk(containing_statement):
            if isinstance(node, (ast.Call, ast.NamedExpr, ast.Await)) and id(node) not in inside_call:
                # Enclosing calls, e.g. Model(...).to(device), occur after
                # construction; inspect their siblings without tainting on .to.
                if any(n is call for n in ast.walk(node)):
                    continue
                effects = possible_effects(node)
                side_effects.extend(effects)
                uncertain_context = uncertain_context or bool(effects)
    binding = bind_constructor(init, call, lambda node: value(node, env))
    binding_issues, unknown_unpack = binding['binding_issues'], binding['unknown_unpack']

    def describe(item):
        resolved = False
        result = None
        if item is not None and not unknown_unpack and not uncertain_context and not binding_issues:
            try:
                result = item.literal if item.materialized else value(item.node, env if item.origin == 'forwarded' else {})
                resolved = True
            except (Unresolved, TypeError, KeyError):
                pass
        return {'origin': item.origin if item else 'required_unresolved',
                'expression': item.expression if item else None,
                'constructor_input_status': 'static_value' if resolved else 'unknown', 'constructor_input': result}

    rows = []
    for name, item in binding['named'].items():
        description = describe(item)
        declared = name in config
        result = description['constructor_input']
        rows.append({'parameter': name, **description,
                     'declared_present': declared, 'declared_value': config.get(name),
                     'declared_input_mismatch': declared and description['constructor_input_status'] == 'static_value' and (type(result) is not type(config[name]) or result != config[name]),
                     'factory_line': call.lineno, 'factory_col_offset': call.col_offset, 'constructor_line': init.lineno})
    return annotate({'schema_version': 1, 'kind': 'config_flow_evidence', 'factory': factory_name, 'class': class_name,
            'factory_sha256': hashlib.sha256(factory_path.read_bytes()).hexdigest(),
            'model_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(), 'config_sha256': fingerprint(config),
            'parameters': rows, 'unknown_unpack': unknown_unpack, 'uncertain_factory_context': uncertain_context,
            'binding_issues': binding_issues,
            'extra_keyword_arguments': {name: describe(item) for name, item in binding['extra_keywords'].items()},
            'variadic_positional_arguments': [describe(item) for item in binding['variadic_positional']],
            'possible_side_effects': side_effects,
            'scope_limitations': scope_limitations,
            'unmatched_config_keys': sorted(set(config) - set(binding['named'])),
            'constructor_binding_verified': False, 'runtime_instance_verified': False,
            'limitations': ['The caller selects the factory/class binding; imports, aliases and decorators are not executed.',
                           'Constructor inputs are not final attributes: guards, internal overrides, inheritance and .to() effects need review.',
                           'Config keys may have aliases; unmatched keys do not prove they are unused.']})


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
