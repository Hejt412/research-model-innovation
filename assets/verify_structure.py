"""USER-RUN ONLY: check outputs exported by a reviewed project's inference adapter.

Never run against the user's project from Codex. Adapter calls can have side
effects; explicit opt-in is not a sandbox or proof that no training occurred.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import platform

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
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique, parse_constant=constant)


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


def validate_spec(spec):
    if not isinstance(spec, dict) or type(spec.get('schema_version')) is not int or spec['schema_version'] != 1:
        raise ValueError('Expected structure probe spec schema_version=1')
    if not isinstance(spec.get('probe_kwargs'), dict):
        raise ValueError('probe_kwargs must be an object')
    comparison = spec.get('comparison')
    if not isinstance(comparison, dict) or any(not finite(comparison.get(k)) or comparison[k] < 0
                                              for k in ('atol', 'rtol')):
        raise ValueError('Declare finite nonnegative atol and rtol before comparison')
    cases = spec.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Declare nonempty cases')
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'].strip():
            raise ValueError('Each case needs a nonempty id')
        if case['id'] in seen:
            raise ValueError('Duplicate case id: ' + case['id'])
        seen.add(case['id'])
        if not shapes(case.get('input_shapes')) or not shapes(case.get('expected_outputs')):
            raise ValueError('Replace unknown input/output shapes with named integer shapes')
    return spec


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
    rows = []
    for identity, case in planned.items():
        observed = by_id.get(identity)
        row = {'id': identity, 'checks': [], 'disabled_baseline_equivalence': 'not_assessed'}
        rows.append(row)
        if observed is None:
            issues.append({'case': identity, 'reason': 'missing_case'})
            continue
        inputs = observed.get('inputs')
        if not isinstance(inputs, dict) or set(inputs) != set(case['input_shapes']):
            issues.append({'case': identity, 'reason': 'input_coverage_mismatch'})
        else:
            for name, expected in case['input_shapes'].items():
                item = inputs[name]
                digest = item.get('sha256') if isinstance(item, dict) else None
                if (not isinstance(item, dict) or not shape(item.get('shape')) or item['shape'] != expected
                        or not isinstance(digest, str) or len(digest) != 64
                        or any(c not in '0123456789abcdef' for c in digest)):
                    issues.append({'case': identity, 'input': name, 'reason': 'invalid_input_descriptor'})
        values = {}
        for variant in VARIANTS:
            outputs = observed.get(variant)
            if not isinstance(outputs, dict) or set(outputs) != set(case['expected_outputs']):
                issues.append({'case': identity, 'variant': variant, 'reason': 'output_coverage_mismatch'})
                continue
            for name, expected in case['expected_outputs'].items():
                item = outputs[name]
                raw = item.get('values') if isinstance(item, dict) else None
                valid = (isinstance(item, dict) and shape(item.get('shape')) and item['shape'] == expected
                         and isinstance(raw, list) and len(raw) == math.prod(expected)
                         and all(finite(v) for v in raw))
                row['checks'].append({'variant': variant, 'output': name, 'shape_and_finite': valid})
                if not valid:
                    issues.append({'case': identity, 'variant': variant, 'output': name, 'reason': 'invalid_output_descriptor'})
                else:
                    values[(variant, name)] = raw
        compared = []
        for name in case['expected_outputs']:
            baseline, disabled = values.get(('baseline', name)), values.get(('disabled', name))
            if baseline is None or disabled is None:
                continue
            atol, rtol = spec['comparison']['atol'], spec['comparison']['rtol']
            equal = all(abs(b-a) <= atol + rtol*abs(a) for a, b in zip(baseline, disabled))
            compared.append(equal)
            row['checks'].append({'output': name, 'disabled_within_tolerance': equal})
            if not equal:
                issues.append({'case': identity, 'output': name, 'reason': 'disabled_baseline_difference'})
        if len(compared) == len(case['expected_outputs']):
            row['disabled_baseline_equivalence'] = 'within_tolerance' if all(compared) else 'different'
    return {'kind': 'user_run_structure_observation', 'schema_version': 1,
            'status': 'passed_sampled_checks' if not issues else 'failed_or_unconfirmed',
            'cases': rows, 'issues': issues, 'comparison': spec['comparison'],
            'setup_declarations': setup, 'setup_verified': False,
            'training_absence_verified': False, 'dependency_closure_verified': False,
            'performance_improvement_verified': False,
            'limitations': ['Only exported outputs for these cases are checked; no universal or training-state equivalence.',
                            'Input/weight/RNG setup is adapter-declared and requires source review.',
                            'Adapter imports/forward may have side effects; no execution sandbox is provided.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', required=True, help='Reviewed module:collect accepting the complete spec')
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--source-file', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute-reviewed-probe', action='store_true')
    args = parser.parse_args()
    if not args.execute_reviewed_probe:
        parser.error('Adapter was not imported. Review it, then opt in from your own environment.')
    try:
        spec_bytes = args.spec.read_bytes()
        spec = validate_spec(load_json(args.spec))
        module, name = args.adapter.split(':', 1)
        adapter = getattr(importlib.import_module(module), name)
        observation = adapter(deepcopy(spec))
        report = check_outputs(spec, observation)
        paths = list(args.source_file)
        source = inspect.getsourcefile(adapter)
        if source:
            paths.append(Path(source))
        source_hashes = {}
        for path in paths:
            try:
                source_hashes[str(path.resolve())] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            except OSError as exc:
                source_hashes[str(path)] = {'status': 'unreadable', 'reason': str(exc)}
        report.update(adapter=args.adapter, python=platform.python_version(), source_files=source_hashes,
                      inputs={case['id']: case.get('inputs') for case in observation['cases']},
                      probe_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      spec_sha256=hashlib.sha256(spec_bytes).hexdigest())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        return 0 if report['status'] == 'passed_sampled_checks' else 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
