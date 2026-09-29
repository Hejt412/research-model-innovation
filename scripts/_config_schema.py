"""Dependency-free validation of the normalized research config contract."""
import math

UNKNOWN = {'state': 'unknown'}
NULLABLE = {'/training/scheduler', '/training/augmentation', '/data/episode_plan_sha256'}
REQUIRED = ('/model/baseline', '/data/dataset_id', '/protocol/split',
            '/protocol/target_label_access', '/training/seeds', '/evaluation/tasks', '/evaluation/metrics', '/evaluation/sampling')


def get_path(value, pointer):
    for key in pointer.strip('/').split('/'):
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def string(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value):
    return isinstance(value, list) and bool(value) and all(string(v) for v in value) and len(set(value)) == len(value)


def seeds(value):
    return isinstance(value, list) and bool(value) and all(type(v) is int and v >= 0 for v in value) and len(set(value)) == len(value)


def validate_config(config):
    result = {'schema_version': 1, 'missing': [], 'unknown': [], 'invalid': [], 'disabled': []}
    if not isinstance(config, dict):
        result['invalid'].append({'path': '/', 'reason': 'config must be an object'})
        result['complete'] = False
        return result

    def invalid(path, reason):
        result['invalid'].append({'path': path, 'reason': reason})

    def visit(value, path=''):
        if value == UNKNOWN:
            result['unknown'].append(path)
        elif value is None:
            result['disabled' if path in NULLABLE else 'unknown'].append(path)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(item, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, path + '/' + str(i))
    visit(config)
    for section in ('model', 'data', 'protocol', 'training', 'evaluation', 'environment'):
        if section in config and config[section] != UNKNOWN and not isinstance(config[section], dict):
            invalid('/' + section, 'section must be an object or explicit unknown')
    for path in REQUIRED:
        present, value = get_path(config, path)
        if not present:
            result['missing'].append(path)
        elif value is None or value == UNKNOWN:
            continue
        elif path == '/training/seeds':
            if not seeds(value):
                invalid(path, 'nonempty distinct nonnegative integer seeds required; bool/float are not seeds')
        elif path == '/evaluation/tasks':
            if not strings(value):
                invalid(path, 'nonempty distinct task names required')
        elif path == '/evaluation/sampling':
            if value not in ('episodic', 'fixed_split'):
                invalid(path, 'use episodic or fixed_split')
        elif path == '/evaluation/metrics':
            if not isinstance(value, list) or not value:
                invalid(path, 'nonempty metric object list required')
                continue
            names, primary = [], 0
            for i, metric in enumerate(value):
                where = path + '/' + str(i)
                if not isinstance(metric, dict) or metric == UNKNOWN:
                    invalid(where, 'metric requires name/unit/direction/role/required')
                    continue
                for key in ('name', 'unit', 'direction', 'role', 'required'):
                    if key not in metric:
                        result['missing'].append(where + '/' + key)
                if not string(metric.get('name')) or not string(metric.get('unit')):
                    invalid(where, 'metric name and unit must be nonempty strings')
                else:
                    names.append(metric['name'])
                if metric.get('direction') not in ('higher', 'lower'):
                    invalid(where + '/direction', 'use higher or lower')
                if metric.get('role') not in ('primary', 'secondary'):
                    invalid(where + '/role', 'use primary or secondary')
                if type(metric.get('required')) is not bool:
                    invalid(where + '/required', 'boolean required')
                if metric.get('role') == 'primary':
                    primary += 1
                    if metric.get('required') is not True:
                        invalid(where, 'primary metrics must be required')
            if len(names) != len(set(names)):
                invalid(path, 'metric names must be unique')
            if not primary:
                invalid(path, 'at least one primary metric required')
        elif not string(value):
            invalid(path, 'nonempty string required')
    for path in ('/training/lr', '/training/epochs', '/training/batch_size'):
        present, value = get_path(config, path)
        if present and value is not None and value != UNKNOWN:
            good = type(value) in (int, float) and math.isfinite(value) and value > 0
            if path != '/training/lr':
                good = good and type(value) is int
            if not good:
                invalid(path, 'positive finite number required; epochs/batch_size must be integers')
    result['complete'] = not (result['missing'] or result['unknown'] or result['invalid'])
    return result


def evaluation_plan(config):
    """Extract declared names even from an incomplete config; never infer a plan from observed rows."""
    evaluation = config.get('evaluation', {})
    training = config.get('training', {})
    if not isinstance(evaluation, dict) or not isinstance(training, dict):
        return {'tasks': [], 'metrics': {}, 'seeds': [], 'declared': False}
    tasks = evaluation.get('tasks', [])
    values = evaluation.get('metrics', [])
    seed_values = training.get('seeds', [])
    metrics = {m['name']: m for m in values if isinstance(m, dict) and string(m.get('name'))} if isinstance(values, list) else {}
    declared = strings(tasks) and bool(metrics) and seeds(seed_values)
    return {'tasks': tasks if strings(tasks) else [], 'metrics': metrics,
            'seeds': [str(s) for s in seed_values] if seeds(seed_values) else [], 'declared': bool(declared)}
