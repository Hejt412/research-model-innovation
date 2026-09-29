"""Bind inert AST argument descriptions with Python's signature rules, never a target callable."""
import ast
from dataclasses import dataclass
import inspect


@dataclass
class Input:
    expression: str
    origin: str
    node: object = None
    literal: object = None
    materialized: bool = False


def bind_constructor(init, call, evaluate):
    positional = [*init.args.posonlyargs, *init.args.args]
    default_nodes = dict(zip([p.arg for p in positional][len(positional)-len(init.args.defaults):], init.args.defaults))
    default_nodes.update({p.arg: node for p, node in zip(init.args.kwonlyargs, init.args.kw_defaults) if node is not None})
    defaults = {name: Input(ast.unparse(node), 'constructor_default', node=node) for name, node in default_nodes.items()}
    parameters = []
    for arg in init.args.posonlyargs:
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_ONLY, default=defaults.get(arg.arg, inspect.Parameter.empty)))
    for arg in init.args.args:
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=defaults.get(arg.arg, inspect.Parameter.empty)))
    if init.args.vararg:
        parameters.append(inspect.Parameter(init.args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg in init.args.kwonlyargs:
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY, default=defaults.get(arg.arg, inspect.Parameter.empty)))
    if init.args.kwarg:
        parameters.append(inspect.Parameter(init.args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    signature = inspect.Signature(parameters)
    arguments, keywords, issues, unknown_unpack = [], {}, [], False
    for node in call.args:
        if isinstance(node, ast.Starred):
            try:
                values = evaluate(node.value)
                if not isinstance(values, (tuple, list)):
                    raise ValueError('star arguments are not a known list/tuple')
                arguments.extend(Input(ast.unparse(node), 'forwarded', literal=v, materialized=True) for v in values)
            except (ValueError, TypeError, KeyError):
                unknown_unpack = True
        else:
            arguments.append(Input(ast.unparse(node), 'forwarded', node=node))

    def add_keyword(name, item):
        if name in keywords:
            issues.append('duplicate_keyword:' + name)
        keywords[name] = item

    for keyword in call.keywords:
        if keyword.arg is not None:
            add_keyword(keyword.arg, Input(ast.unparse(keyword.value), 'forwarded', node=keyword.value))
        else:
            try:
                values = evaluate(keyword.value)
                if not isinstance(values, dict) or not all(isinstance(k, str) for k in values):
                    raise ValueError('keyword unpacking is not a known string-keyed mapping')
                for name, item in values.items():
                    add_keyword(name, Input('**' + ast.unparse(keyword.value), 'forwarded', literal=item, materialized=True))
            except (ValueError, TypeError, KeyError):
                unknown_unpack = True
    if not init.args.kwarg:
        accepted = {p.name for p in parameters if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
        positional_only = {p.arg for p in init.args.posonlyargs}
        issues.extend(('positional_only_as_keyword:' if name in positional_only else 'unexpected_keyword:') + name
                      for name in keywords.keys() - accepted)
    bound_values = {}
    instance = object()
    if not unknown_unpack and not issues:
        try:
            # Supplying an inert instance marker also catches duplicate self,
            # required arguments, and constructors without an instance slot.
            # Positional-only names belong to **kwargs, including when the
            # positional slot uses a default. Separate them before bind for
            # consistent behavior across supported inspect versions.
            positional_only = {p.arg for p in init.args.posonlyargs}
            extra_only = {name: item for name, item in keywords.items()
                          if init.args.kwarg and name in positional_only}
            bound = signature.bind(instance, *arguments,
                                   **{name: item for name, item in keywords.items() if name not in extra_only})
            bound.apply_defaults()
            if extra_only:
                bound.arguments[init.args.kwarg.arg].update(extra_only)
            bound_values = bound.arguments
        except TypeError as exc:
            issues.append('invalid_call:' + str(exc))
    instance_name = positional[0].arg if positional else None
    names = [p.arg for p in positional[1:]] + [p.arg for p in init.args.kwonlyargs]
    named = {name: bound_values.get(name, defaults.get(name)) for name in names}
    extra = bound_values.get(init.args.kwarg.arg, {}) if init.args.kwarg else {}
    variadic = bound_values.get(init.args.vararg.arg, ()) if init.args.vararg else ()
    return {'named': named, 'extra_keywords': extra,
            'variadic_positional': [item for item in variadic if item is not instance],
            'binding_issues': sorted(set(issues)), 'unknown_unpack': unknown_unpack,
            'instance_parameter': instance_name}
