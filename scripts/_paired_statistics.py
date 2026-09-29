"""Optional paired, seed-level bootstrap; never treat episodes as training replicates."""
import math
import random
import statistics


def validate_statistics(spec):
    if not isinstance(spec, dict):
        return ['statistics must be an object']
    errors = []
    if spec.get('method') != 'paired_bootstrap_basic':
        errors.append('method must be paired_bootstrap_basic')
    if spec.get('independent_unit') != 'training_seed':
        errors.append('only training_seed aggregation is supported; episode/query rows are not independent runs')
    if spec.get('comparison_scope') != 'per_task_metric_unadjusted':
        errors.append('comparison_scope must explicitly acknowledge per_task_metric_unadjusted')
    level = spec.get('confidence_level')
    if type(level) not in (int, float) or not math.isfinite(level) or not 0.5 < level < 1:
        errors.append('confidence_level must be finite and between 0.5 and 1')
    for key, lower, upper in (('resamples', 1000, 50000), ('min_pairs', 5, 10000), ('random_seed', 0, 2**63-1)):
        if type(spec.get(key)) is not int or not lower <= spec[key] <= upper:
            errors.append(f'{key} must be an integer in [{lower}, {upper}]')
    return errors


def quantile(sorted_values, p):
    index = (len(sorted_values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return sorted_values[lo] + (index-lo) * (sorted_values[hi] - sorted_values[lo])


def assess(deltas, metric, spec, eligible):
    report = {'status': 'not_predeclared', 'ci': None, 'decision': 'not_assessed',
              'independent_unit': 'training_seed', 'paired_count': len(deltas),
              'preregistration_time_verified': False, 'mechanism_benefit_proven': False}
    if spec is None:
        return report
    if validate_statistics(spec):
        raise ValueError('Invalid statistics declaration')
    report.update({'declaration': spec, 'metric_direction': metric['direction'],
                   'min_improvement': metric.get('min_improvement'),
                   'limitations': ['Per-task/metric intervals are exploratory, with no multiplicity correction.',
                                  'Independence and preregistration timing are declared, not established from CSV.',
                                  'Small samples can yield unstable bootstrap intervals; no mechanism causality is inferred.']})
    if not eligible:
        report['status'] = 'blocked_incomplete_or_confounded'
        return report
    if len(deltas) < spec['min_pairs']:
        report['status'] = 'insufficient_independent_pairs'
        return report
    if len(deltas) * spec['resamples'] > 5_000_000:
        report['status'] = 'resampling_budget_exceeded'
        return report
    gains = [d if metric['direction'] == 'higher' else -d for d in deltas]
    mean = statistics.mean(gains)
    report['mean_direction_adjusted_gain'] = mean
    if min(gains) == max(gains):
        report['status'] = 'degenerate_observed_differences'
        return report
    rng = random.Random(spec['random_seed'])
    distribution = sorted(statistics.mean(gains[rng.randrange(len(gains))] for _ in gains) for _ in range(spec['resamples']))
    alpha = (1 - spec['confidence_level']) / 2
    low, high = 2*mean - quantile(distribution, 1-alpha), 2*mean - quantile(distribution, alpha)
    report.update({'status': 'exploratory_interval',
                   'ci': {'low': low, 'high': high, 'confidence_level': spec['confidence_level'],
                          'method': spec['method'], 'quantity': 'mean_direction_adjusted_paired_gain',
                          'unit': metric['unit']}})
    threshold = metric.get('min_improvement')
    if threshold is not None:
        report['decision'] = ('threshold_supported_exploratory' if low > threshold else
                              'below_predeclared_threshold' if high < threshold else 'inconclusive')
    return report
