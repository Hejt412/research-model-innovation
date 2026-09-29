"""Validate declared sample splits and exact support/query episode plans without loading data."""
import argparse
from collections import defaultdict
from pathlib import Path
from _records import fingerprint, read_json
from _static import emit
from _few_shot import inspect_few_shot

FIELDS = {'sample_id', 'record_id', 'device_id'}


def inspect_plan(plan):
    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise ValueError('Expected data plan schema_version=1')
    if any(key in plan for key in ('n_way', 'k_shot', 'query_per_class', 'episodes_per_seed')):
        raise ValueError('Place few-shot cardinalities in few_shot[task], not at the top level')
    if not isinstance(plan.get('samples'), list) or not plan['samples']:
        raise ValueError('samples must be a nonempty list')
    if not isinstance(plan.get('episodes'), list):
        raise ValueError('episodes must be a list; use [] only for a non-episodic protocol')
    if plan.get('mode') not in ('episodic', 'fixed_split'):
        raise ValueError('mode must be explicitly episodic or fixed_split')
    if plan['mode'] == 'episodic' and not plan['episodes']:
        raise ValueError('An episodic plan must contain episodes')
    if plan['mode'] == 'fixed_split' and plan['episodes']:
        raise ValueError('A fixed_split plan must not contain episodes')
    policy = plan.get('policy', {})
    if not isinstance(policy, dict):
        raise ValueError('policy must be an object')
    disjoint = policy.get('split_disjoint_by', ['sample_id', 'record_id'])
    pair_disjoint = policy.get('support_query_disjoint_by', ['sample_id', 'record_id'])
    for values in (disjoint, pair_disjoint):
        if not isinstance(values, list) or not values or any(v not in FIELDS for v in values) or len(values) != len(set(values)):
            raise ValueError('Disjoint fields must be distinct sample_id/record_id/device_id values')
    task_splits = policy.get('task_splits')
    if not isinstance(task_splits, dict):
        raise ValueError('policy.task_splits must map each episodic task to allowed support/query split names')
    samples, issues = {}, []
    for sample in plan['samples']:
        if not isinstance(sample, dict) or any(not isinstance(sample.get(k), str) or not sample[k].strip() for k in (*FIELDS, 'split')):
            raise ValueError('Each sample requires nonempty sample_id/record_id/device_id/split strings')
        key = sample['sample_id']
        if key in samples:
            raise ValueError('Duplicate sample_id: ' + key)
        samples[key] = sample
    for field in disjoint:
        groups = defaultdict(set)
        for sample in samples.values():
            groups[sample[field]].add(sample['split'])
        for group, splits in sorted(groups.items()):
            if len(splits) > 1:
                issues.append({'kind': 'cross_split_overlap', 'field': field, 'group': group, 'splits': sorted(splits)})
    episode_ids, task_seed_counts = set(), defaultdict(int)
    for episode in plan['episodes']:
        if not isinstance(episode, dict) or any(not isinstance(episode.get(k), str) or not episode[k].strip() for k in ('task', 'episode_id')):
            raise ValueError('Episode requires task and episode_id strings')
        if type(episode.get('seed')) is not int or episode['seed'] < 0:
            raise ValueError('Episode seed must be a nonnegative integer')
        identity = (episode['task'], episode['seed'], episode['episode_id'])
        if identity in episode_ids:
            raise ValueError('Duplicate episode identity: ' + str(identity))
        episode_ids.add(identity)
        task_seed_counts[(episode['task'], str(episode['seed']))] += 1
        allowed = task_splits.get(episode['task'])
        if not isinstance(allowed, dict):
            raise ValueError('Missing task_splits policy for ' + episode['task'])
        for role in ('support', 'query'):
            ids = episode.get(role)
            if not isinstance(ids, list) or not ids or not all(isinstance(v, str) for v in ids) or len(set(ids)) != len(ids):
                raise ValueError('support/query must be nonempty distinct sample ID lists')
            if not isinstance(allowed.get(role), list) or not allowed[role] or not all(isinstance(v, str) and v for v in allowed[role]):
                raise ValueError('Task policy must declare allowed support/query splits')
            for sample_id in ids:
                if sample_id not in samples:
                    raise ValueError('Unknown episode sample: ' + sample_id)
                if samples[sample_id]['split'] not in allowed[role]:
                    issues.append({'kind': 'episode_split_violation', 'episode': list(identity), 'role': role, 'sample_id': sample_id})
        for field in pair_disjoint:
            left = {samples[key][field] for key in episode['support']}
            right = {samples[key][field] for key in episode['query']}
            if left & right:
                issues.append({'kind': 'support_query_overlap', 'field': field, 'episode': list(identity), 'groups': sorted(left & right)})
    few_shot = inspect_few_shot(plan, samples)
    issues.extend(few_shot['issues'])
    normalized = {'schema_version': 1, 'mode': plan['mode'], 'samples': sorted(plan['samples'], key=lambda s: s['sample_id']),
                  'episodes': plan['episodes'], 'policy': {**policy, 'split_disjoint_by': disjoint,
                                                         'support_query_disjoint_by': pair_disjoint},
                  'few_shot': plan.get('few_shot')}
    return {'schema_version': 1, 'kind': 'data_protocol_report', 'mode': plan['mode'], 'plan_sha256': fingerprint(normalized),
            'split_sha256': fingerprint(normalized['samples']), 'episodes_sha256': fingerprint(plan['episodes']),
            'policy_sha256': fingerprint(normalized['policy']), 'issues': issues,
            'few_shot': few_shot, 'few_shot_sha256': fingerprint(normalized['few_shot']),
            'status': ('protocol_conflicts' if issues else 'incomplete_specification' if few_shot['status'].startswith('unverified') else 'declared_plan_consistent'),
            'sample_count': len(samples), 'episode_count': len(plan['episodes']),
            'task_seed_counts': [{'task': task, 'seed': seed, 'count': count} for (task, seed), count in sorted(task_seed_counts.items())],
            'verified_data_bytes': False,
            'limitations': ['Only supplied identities/roles are checked; mislabeled aliases and actual loader behavior remain unverified.',
                            'Episode order and support/query order are included in the fingerprint.',
                            'No labels are inferred and no dataset arrays are loaded.']}


def compare_plans(left, right):
    a, b = inspect_plan(left), inspect_plan(right)
    fields = ('split_sha256', 'episodes_sha256', 'policy_sha256', 'few_shot_sha256')
    return {'schema_version': 1, 'kind': 'data_protocol_comparison',
            'equal_declared_plan': a['plan_sha256'] == b['plan_sha256'],
            'changed_components': [key for key in fields if a[key] != b[key]],
            'control': a, 'experiment': b, 'actual_sampling_verified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check')
    check.add_argument('plan', type=Path)
    compare = sub.add_parser('compare')
    compare.add_argument('control', type=Path)
    compare.add_argument('experiment', type=Path)
    for parser in (check, compare):
        parser.add_argument('--out', type=Path)
    args = p.parse_args()
    try:
        result = inspect_plan(read_json(args.plan)) if args.command == 'check' else compare_plans(read_json(args.control), read_json(args.experiment))
        emit(result, args.out)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        p.error(str(exc))
    conflict = result.get('issues') or result.get('status') == 'incomplete_specification' or (args.command == 'compare' and
                (not result['equal_declared_plan'] or any(r['status'] != 'declared_plan_consistent' for r in (result['control'], result['experiment']))))
    if conflict:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
