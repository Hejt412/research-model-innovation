"""Check declared episode cardinality and class identities, without loading data."""
from collections import Counter


def inspect_few_shot(plan, samples):
    if plan['mode'] == 'fixed_split':
        if plan.get('few_shot'):
            raise ValueError('few_shot is only applicable to episodic plans')
        return {'status': 'not_applicable', 'issues': []}
    specs = plan.get('few_shot')
    if specs is None:
        return {'status': 'unverified_missing_specification', 'issues': []}
    if not isinstance(specs, dict) or not specs:
        raise ValueError('few_shot must map task names to episode specifications')
    for task, spec in specs.items():
        if not isinstance(task, str) or not task or not isinstance(spec, dict):
            raise ValueError('Invalid few_shot task specification')
        for key in ('n_way', 'k_shot', 'query_per_class', 'episodes_per_seed'):
            if type(spec.get(key)) is not int or spec[key] <= 0:
                raise ValueError('few_shot requires positive integer ' + key)
    issues, counts = [], Counter()
    for episode in plan['episodes']:
        task, seed = episode['task'], episode['seed']
        counts[(task, seed)] += 1
        where = {'task': task, 'seed': seed, 'episode_id': episode['episode_id']}
        if task not in specs:
            issues.append({**where, 'kind': 'missing_few_shot_task_spec'})
            continue
        spec = specs[task]
        roles = {}
        for role, expected in (('support', spec['k_shot']), ('query', spec['query_per_class'])):
            labels = [samples[s].get('class_id') for s in episode[role]]
            if any(not isinstance(c, str) or not c.strip() for c in labels):
                issues.append({**where, 'kind': 'missing_class_identity', 'role': role})
                continue
            roles[role] = Counter(labels)
            if len(roles[role]) != spec['n_way']:
                issues.append({**where, 'kind': 'wrong_n_way', 'role': role, 'observed': len(roles[role]), 'expected': spec['n_way']})
            if any(count != expected for count in roles[role].values()):
                issues.append({**where, 'kind': 'wrong_samples_per_class', 'role': role,
                               'observed': dict(roles[role]), 'expected': expected})
        if len(roles) == 2 and roles['support'].keys() != roles['query'].keys():
            issues.append({**where, 'kind': 'support_query_class_mismatch'})
    for (task, seed), count in sorted(counts.items()):
        if task in specs and count != specs[task]['episodes_per_seed']:
            issues.append({'kind': 'wrong_episode_count', 'task': task, 'seed': seed,
                           'observed': count, 'expected': specs[task]['episodes_per_seed']})
    for task in sorted(set(specs) - {task for task, _ in counts}):
        issues.append({'kind': 'missing_few_shot_task_episodes', 'task': task})
    return {'status': 'protocol_conflicts' if issues else 'declared_counts_consistent', 'issues': issues}
