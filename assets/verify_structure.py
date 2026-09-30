"""Check exported inference observations; project adapters are USER-RUN ONLY.

Offline mode never imports an adapter. Explicit execution opt-in is not a sandbox
or proof that no training occurred. Codex must not run this against a user model.
"""
import argparse
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import importlib
from importlib.machinery import PathFinder
import inspect
import json
import math
from pathlib import Path
import platform
import re
import sys

SETUP = ('eval_mode', 'inference_mode', 'shared_input', 'baseline_state_matched', 'rng_reset')
VARIANTS = ('baseline', 'disabled', 'enabled')


def load_json(path):
    def unique(pairs):
        result = {}
        for name, item in pairs:
            if name in result:
                raise ValueError('Duplicate JSON key: ' + name)
            result[name] = item
        return result
    def constant(item):
        raise ValueError('Non-finite JSON constant: ' + item)
    def real(item):
        value = float(item)
        if not math.isfinite(value):
            raise ValueError('JSON number exceeds finite float range: ' + item)
        return value
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique, parse_constant=constant, parse_float=real)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_metadata(value):
    try:
        canonical(value)
        return deepcopy(value)
    except (TypeError, ValueError, OverflowError):
        return {'status': 'unavailable_non_json_or_nonfinite_data'}


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def shape(value):
    return isinstance(value, list) and all(type(n) is int and n > 0 for n in value)


def shapes(mapping):
    return (isinstance(mapping, dict) and bool(mapping)
            and all(isinstance(k, str) and k.strip() and shape(v) for k, v in mapping.items()))


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def comparison(value):
    return isinstance(value, dict) and all(finite(value.get(k)) and value[k] >= 0 for k in ('atol', 'rtol'))


def named(value):
    return isinstance(value, str) and bool(value.strip())


def selector_size(selector, planned):
    if not isinstance(selector, dict) or selector.get('case') not in planned or selector.get('variant') not in VARIANTS:
        raise ValueError('Relation selector requires a planned case and a known variant')
    outputs = planned[selector['case']]['expected_outputs']
    if selector.get('output') not in outputs:
        raise ValueError('Relation selector requires a planned output')
    size = math.prod(outputs[selector['output']])
    indices = selector.get('indices')
    if 'indices' not in selector:
        return size
    if (not isinstance(indices, list) or not indices or
            any(type(n) is not int or n < 0 or n >= size for n in indices) or len(set(indices)) != len(indices)):
        raise ValueError('Relation indices must be nonempty, unique and within the output')
    return len(indices)


def validate_spec(spec):
    if not isinstance(spec, dict) or type(spec.get('schema_version')) is not int or spec['schema_version'] not in (1, 2):
        raise ValueError('Expected structure probe spec schema_version=1 or 2')
    if not isinstance(spec.get('probe_kwargs'), dict):
        raise ValueError('probe_kwargs must be an object')
    if not comparison(spec.get('comparison')):
        raise ValueError('Declare finite nonnegative atol and rtol before comparison')
    cases = spec.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Declare nonempty cases')
    planned = {}
    for case in cases:
        if not isinstance(case, dict) or not named(case.get('id')):
            raise ValueError('Each case needs a nonempty id')
        if case['id'] in planned:
            raise ValueError('Duplicate case id: ' + case['id'])
        planned[case['id']] = case
        if not shapes(case.get('input_shapes')) or not shapes(case.get('expected_outputs')):
            raise ValueError('Replace unknown input/output shapes with named integer shapes')
    if spec['schema_version'] == 1:
        if any(k in spec for k in ('context', 'mechanism_checks', 'relations')):
            raise ValueError('Use schema_version=2 for context or behavioral checks')
        return spec
    context = spec.get('context')
    if context is not None:
        if not isinstance(context, dict):
            raise ValueError('context must declare baseline and experiment manifest links')
        for key in ('baseline', 'experiment'):
            item = context.get(key)
            if not isinstance(item, dict) or not named(item.get('experiment_id')) or not sha(item.get('manifest_sha256')):
                raise ValueError('Each context link needs experiment_id and manifest_sha256')
        if context['baseline']['experiment_id'] == context['experiment']['experiment_id']:
            raise ValueError('Baseline and experiment identities must differ')
    for section in ('mechanism_checks', 'relations'):
        checks = spec.get(section, [])
        if not isinstance(checks, list):
            raise ValueError(section + ' must be a list')
        seen = set()
        for check in checks:
            if not isinstance(check, dict) or not named(check.get('id')) or not named(check.get('intent')):
                raise ValueError('Each behavioral check needs an id and project-specific intent')
            if check['id'] in seen:
                raise ValueError('Duplicate check id: ' + check['id'])
            seen.add(check['id'])
            if section == 'relations':
                if check.get('kind') not in ('close', 'different') or not comparison(check.get('comparison')):
                    raise ValueError('Relations need close/different and predeclared comparison')
                if selector_size(check.get('left'), planned) != selector_size(check.get('right'), planned):
                    raise ValueError('Relation selections must have the same number of elements')
            else:
                if check.get('case') not in planned or not named(check.get('observable')):
                    raise ValueError('Mechanism check needs a planned case and observable name')
                kind = check.get('kind')
                if kind == 'executed':
                    if type(check.get('min_calls')) is not int or check['min_calls'] < 1:
                        raise ValueError('executed requires min_calls >= 1')
                elif kind in ('range', 'nonzero'):
                    if not shape(check.get('shape')):
                        raise ValueError('Numeric observable requires its expected shape')
                    if kind == 'nonzero':
                        if not finite(check.get('atol')) or check['atol'] < 0:
                            raise ValueError('nonzero requires finite nonnegative atol')
                    elif (not finite(check.get('min')) or not finite(check.get('max')) or check['min'] > check['max']):
                        raise ValueError('range requires finite min <= max')
                else:
                    raise ValueError('Unknown mechanism check kind')
    return spec


def display_number(value):
    """Keep report JSON finite, including errors larger than the float range."""
    try:
        result = float(value)
        if math.isfinite(result) and (result != 0 or value == 0):
            return result
    except OverflowError:
        pass
    with localcontext() as ctx:
        ctx.prec = 20
        return format(Decimal(value.numerator) / Decimal(value.denominator), '.12E')


def coordinate(index, dimensions):
    result = []
    for size in reversed(dimensions):
        result.append(index % size)
        index //= size
    return list(reversed(result))


def compare_values(left, right, tolerance, dimensions=None):
    """Exact rational arithmetic on exported finite numbers avoids overflow."""
    if len(left) != len(right) or not left:
        raise ValueError('Comparison requires nonempty equally sized selections')
    atol, rtol = Fraction(tolerance['atol']), Fraction(tolerance['rtol'])
    failures, max_error, max_relative, worst, zero_nonzero = [], Fraction(0), Fraction(0), 0, 0
    for index, (a, b) in enumerate(zip(left, right)):
        a, b = Fraction(a), Fraction(b)
        error = abs(b - a)
        limit = atol + rtol * abs(a)
        if error > max_error:
            max_error, worst = error, index
        if a:
            max_relative = max(max_relative, error / abs(a))
        elif error:
            zero_nonzero += 1
        if error > limit:
            failures.append(index)
    result = {'within_tolerance': not failures, 'elements': len(left), 'failure_count': len(failures),
              'failed_indices_sample': failures[:8], 'max_abs_error': display_number(max_error),
              'max_relative_error_nonzero_baseline': display_number(max_relative),
              'zero_baseline_nonzero_difference_count': zero_nonzero, 'worst_flat_index': worst,
              'first_failure_flat_index': failures[0] if failures else None}
    if dimensions is not None:
        result['worst_coordinate'] = coordinate(worst, dimensions)
        result['first_failure_coordinate'] = coordinate(failures[0], dimensions) if failures else None
    return result


def output_values(item, expected):
    raw = item.get('values') if isinstance(item, dict) else None
    if (isinstance(item, dict) and shape(item.get('shape')) and item['shape'] == expected
            and isinstance(raw, list) and len(raw) == math.prod(expected) and all(finite(v) for v in raw)):
        return raw
    return None


def check_outputs(spec, observation):
    validate_spec(spec)
    if not isinstance(observation, dict):
        raise ValueError('Adapter must return an object')
    setup = observation.get('setup', {})
    setup_ok = isinstance(setup, dict) and all(setup.get(k) is True for k in SETUP)
    issues = [] if setup_ok else [{'reason': 'setup_unconfirmed', 'required': list(SETUP)}]
    received = observation.get('cases')
    if not isinstance(received, list):
        raise ValueError('Adapter must return cases')
    by_id = {}
    planned = {case['id']: case for case in spec['cases']}
    for case in received:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str):
            raise ValueError('Observed case needs an id')
        if case['id'] in by_id:
            issues.append({'case': case['id'], 'reason': 'duplicate_case'})
        by_id[case['id']] = case
    for identity in sorted(by_id.keys() - planned.keys()):
        issues.append({'case': identity, 'reason': 'unexpected_case'})
    rows, all_values = [], {}
    for identity, case in planned.items():
        observed = by_id.get(identity)
        row = {'id': identity, 'checks': [], 'disabled_baseline_equivalence': 'not_assessed'}
        rows.append(row)
        if observed is None:
            issues.append({'case': identity, 'reason': 'missing_case'})
            continue
        if spec['schema_version'] == 2:
            case_setup = observed.get('setup')
            if not isinstance(case_setup, dict) or not all(case_setup.get(k) is True for k in SETUP):
                issues.append({'case': identity, 'reason': 'case_setup_unconfirmed'})
        inputs = observed.get('inputs')
        if not isinstance(inputs, dict) or set(inputs) != set(case['input_shapes']):
            issues.append({'case': identity, 'reason': 'input_coverage_mismatch'})
        else:
            for name, expected in case['input_shapes'].items():
                item = inputs[name]
                if (not isinstance(item, dict) or not shape(item.get('shape')) or item['shape'] != expected
                        or not sha(item.get('sha256'))):
                    issues.append({'case': identity, 'input': name, 'reason': 'invalid_input_descriptor'})
        values = {}
        for variant in VARIANTS:
            outputs = observed.get(variant)
            if not isinstance(outputs, dict) or set(outputs) != set(case['expected_outputs']):
                issues.append({'case': identity, 'variant': variant, 'reason': 'output_coverage_mismatch'})
                continue
            for name, expected in case['expected_outputs'].items():
                raw = output_values(outputs[name], expected)
                valid = raw is not None
                row['checks'].append({'variant': variant, 'output': name, 'shape_and_finite': valid})
                if not valid:
                    issues.append({'case': identity, 'variant': variant, 'output': name, 'reason': 'invalid_output_descriptor'})
                else:
                    values[(variant, name)] = raw
                    all_values[(identity, variant, name)] = raw
        compared = []
        for name in case['expected_outputs']:
            baseline, disabled = values.get(('baseline', name)), values.get(('disabled', name))
            if baseline is None or disabled is None:
                continue
            diagnostics = compare_values(baseline, disabled, spec['comparison'], case['expected_outputs'][name])
            equal = diagnostics['within_tolerance']
            compared.append(equal)
            row['checks'].append({'output': name, 'disabled_within_tolerance': equal, 'diagnostics': diagnostics})
            if not equal:
                issues.append({'case': identity, 'output': name, 'reason': 'disabled_baseline_difference'})
        if len(compared) == len(case['expected_outputs']):
            row['disabled_baseline_equivalence'] = 'within_tolerance' if all(compared) else 'different'
    mechanism_rows, relation_rows = [], []
    for check in spec.get('mechanism_checks', []):
        observed = by_id.get(check['case'], {}).get('observables', {})
        item = observed.get(check['observable']) if isinstance(observed, dict) else None
        if check['kind'] == 'executed':
            passed = isinstance(item, dict) and type(item.get('calls')) is int and item['calls'] >= check['min_calls']
        else:
            raw = output_values(item, check['shape'])
            passed = raw is not None and (any(abs(v) > check['atol'] for v in raw) if check['kind'] == 'nonzero'
                                          else all(check['min'] <= v <= check['max'] for v in raw))
        mechanism_rows.append({'id': check['id'], 'kind': check['kind'], 'intent': check['intent'], 'passed': passed})
        if not passed:
            issues.append({'check': check['id'], 'reason': 'mechanism_check_failed_or_missing'})
    for check in spec.get('relations', []):
        selected = []
        for side in ('left', 'right'):
            choice = check[side]
            raw = all_values.get((choice['case'], choice['variant'], choice['output']))
            selected.append(None if raw is None else [raw[i] for i in choice['indices']] if 'indices' in choice else raw)
        diagnostics = None if any(v is None for v in selected) else compare_values(*selected, check['comparison'])
        passed = diagnostics is not None and diagnostics['within_tolerance'] == (check['kind'] == 'close')
        relation_rows.append({'id': check['id'], 'kind': check['kind'], 'intent': check['intent'],
                              'passed': passed, 'diagnostics': diagnostics})
        if not passed:
            issues.append({'check': check['id'], 'reason': 'relation_failed_or_unavailable'})
    report = {'kind': 'user_run_structure_observation', 'schema_version': 2, 'spec_schema_version': spec['schema_version'],
              'status': 'passed_sampled_checks' if not issues else 'failed_or_unconfirmed',
              'cases': rows, 'issues': issues, 'comparison': deepcopy(spec['comparison']),
              'context_declarations': deepcopy(spec.get('context')), 'context_verified': False,
              'mechanism_checks': mechanism_rows, 'relations': relation_rows,
              'mechanism_check_status': 'not_declared' if not mechanism_rows else 'passed_declared_checks' if all(r['passed'] for r in mechanism_rows) else 'failed_or_unconfirmed',
              'relation_check_status': 'not_declared' if not relation_rows else 'passed_declared_checks' if all(r['passed'] for r in relation_rows) else 'failed_or_unconfirmed',
              'setup_declarations': safe_metadata(setup), 'setup_verified': False,
              'training_absence_verified': False, 'dependency_closure_verified': False,
              'performance_improvement_verified': False, 'mechanism_causality_verified': False,
              'limitations': ['Only exported observations for declared cases/relations are checked.',
                              'Input/weight/RNG/state setup and instrumentation require source review.',
                              'Digests and manifest links are not authenticated execution evidence.',
                              'Adapter imports/forward may have side effects; no execution sandbox is provided.']}
    try:
        archive_digest = digest(observation)
        report.update(observation=deepcopy(observation), observation_sha256=archive_digest,
                      observation_archive_status='saved_strict_json')
    except (TypeError, ValueError, OverflowError):
        report['observation_archive_status'] = 'unavailable_non_json_or_nonfinite_data'
        report['issues'].append({'reason': 'observation_not_strict_json'})
        report['status'] = 'failed_or_unconfirmed'
    return report


def source_snapshot(paths):
    result = {}
    for path in paths:
        path = Path(path).resolve()
        try:
            result[str(path)] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        except OSError as exc:
            result[str(path)] = {'status': 'unreadable', 'reason': str(exc)}
    return result


def adapter_source(module):
    """Resolve normal filesystem modules without importing package initializers."""
    locations, parts = sys.path, module.split('.')
    found = None
    for index in range(len(parts)):
        found = PathFinder.find_spec('.'.join(parts[:index + 1]), locations)
        if found is None:
            return None
        locations = found.submodule_search_locations
        if index < len(parts) - 1 and locations is None:
            return None
    return Path(found.origin).resolve() if found.origin and Path(found.origin).is_file() else None


def offline_observation(path, spec_sha256):
    data = load_json(path)
    original = None
    if isinstance(data, dict) and data.get('kind') == 'user_run_structure_observation':
        if type(data.get('schema_version')) is not int or data['schema_version'] != 2:
            raise ValueError('Legacy/future report has no supported raw archive; supply the original exported observation')
        if 'observation' not in data or not sha(data.get('observation_sha256')) or digest(data['observation']) != data['observation_sha256']:
            raise ValueError('Archived observation is unavailable or its digest does not match')
        original = {'report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'spec_matches': data.get('spec_sha256') == spec_sha256,
                    'source_consistency': deepcopy(data.get('source_consistency')),
                    'context_declarations': deepcopy(data.get('context_declarations')),
                    'prior_execution_mode': data.get('execution_mode'),
                    'source_before': deepcopy(data.get('source_before')),
                    'source_after': deepcopy(data.get('source_after')),
                    'provenance_issues': deepcopy(data.get('provenance_issues', []))}
        data = data['observation']
    return data, original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--adapter', help='USER-RUN ONLY: reviewed module:collect accepting the complete spec')
    mode.add_argument('--observation', type=Path, help='Offline raw exported JSON or v2 archived report; never imports adapters')
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--source-file', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute-reviewed-probe', action='store_true')
    args = parser.parse_args()
    if args.adapter and not args.execute_reviewed_probe:
        parser.error('Adapter was not imported. Review it, then opt in from your own environment.')
    if args.observation and (args.execute_reviewed_probe or args.source_file):
        parser.error('Offline mode does not execute adapters or resnapshot current project sources.')
    try:
        spec_bytes = args.spec.read_bytes()
        spec_sha256 = hashlib.sha256(spec_bytes).hexdigest()
        spec = validate_spec(load_json(args.spec))
        protected = [args.spec, *args.source_file]
        if args.observation:
            protected.append(args.observation)
            observation, original = offline_observation(args.observation, spec_sha256)
            report = check_outputs(spec, observation)
            report.update(execution_mode='offline_recheck', observation_file_sha256=hashlib.sha256(args.observation.read_bytes()).hexdigest(),
                          original_report=original, source_consistency={'status': 'not_assessed_offline', 'loaded_code_authenticated': False},
                          provenance_issues=[])
            if original:
                inherited = original['provenance_issues']
                if not isinstance(inherited, list) or any(not isinstance(item, dict) or not named(item.get('reason')) for item in inherited):
                    raise ValueError('Invalid archived provenance issues')
                report['provenance_issues'].extend(inherited)
                if not original['spec_matches'] or original['context_declarations'] != spec.get('context'):
                    report['provenance_issues'].append({'reason': 'original_spec_or_context_mismatch'})
                consistency = original['source_consistency']
                source_status = consistency.get('status') if isinstance(consistency, dict) else None
                before, after = original['source_before'], original['source_after']
                if source_status == 'unchanged_in_declared_scope':
                    if (not isinstance(before, dict) or not before or before != after or
                            any(not isinstance(v, dict) or not sha(v.get('sha256')) for v in before.values())):
                        report['provenance_issues'].append({'reason': 'original_source_snapshot_inconsistent'})
                elif source_status != 'not_assessed_offline':
                    report['provenance_issues'].append({'reason': 'original_source_unconfirmed'})
                report['source_consistency'] = original['source_consistency']
                report['source_before'], report['source_after'] = before, after
        else:
            if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', args.adapter):
                raise ValueError('Adapter must be a module:callable name')
            module, name = args.adapter.split(':', 1)
            source = adapter_source(module)
            paths = [Path(__file__).resolve(), *args.source_file, *([source] if source else [])]
            protected.extend(paths)
            if args.out.resolve() in {p.resolve() for p in protected}:
                raise ValueError('Output must not overwrite probe inputs or declared source files')
            before = source_snapshot(paths)
            adapter = getattr(importlib.import_module(module), name)
            observation = adapter(deepcopy(spec))
            after = source_snapshot(paths)
            report = check_outputs(spec, observation)
            actual = inspect.getsourcefile(adapter)
            confirmed = (source is not None and actual is not None and source == Path(actual).resolve()
                         and before == after and all(sha(v.get('sha256')) for v in before.values()))
            report.update(adapter=args.adapter, execution_mode='user_run_adapter', source_files=after,
                          source_before=before, source_after=after,
                          provenance_issues=[],
                          source_consistency={'status': 'unchanged_in_declared_scope' if confirmed else 'changed_or_unconfirmed',
                                              'loaded_code_authenticated': False})
            if not confirmed:
                report['provenance_issues'].append({'reason': 'source_changed_or_unconfirmed'})
        if args.out.resolve() in {p.resolve() for p in protected}:
            raise ValueError('Output must not overwrite probe inputs or declared source files')
        report['issues'].extend(report['provenance_issues'])
        if report['issues']:
            report['status'] = 'failed_or_unconfirmed'
        report.update(python=platform.python_version(), inputs=safe_metadata({case['id']: case.get('inputs') for case in observation['cases']}),
                      probe_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), spec_sha256=spec_sha256)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        return 0 if report['status'] == 'passed_sampled_checks' else 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
