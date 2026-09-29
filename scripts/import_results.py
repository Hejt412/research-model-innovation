"""Pair user-supplied observations; never run training or infer missing results."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import statistics
from _records import fingerprint, manifest, read_json
from _static import emit
from experiment_manifest import audit


def summarize(csv_path, control, experiment, audit_record):
    # Recompute the audit instead of trusting a hand-edited status field.
    expected = audit(control, experiment, audit_record['factor'],
                     audit_record['declared_config_paths'], audit_record['declared_files'])
    if audit_record != expected:
        raise ValueError('Audit does not match the supplied manifests/declaration')
    config_incomplete = any(expected['unresolved_config_paths'].values())
    ids = {control['experiment_id']: control, experiment['experiment_id']: experiment}
    seed_plans = {}
    for exp_id, record in ids.items():
        seeds = record['config'].get('training', {}).get('seeds')
        seed_plans[exp_id] = {str(int(s)) for s in seeds} if isinstance(seeds, list) and seeds else None
    rows, units = {}, {}
    with csv_path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'experiment_id', 'seed', 'task', 'metric', 'value', 'unit', 'manifest_sha256'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV missing required columns: ' + ', '.join(sorted(required)))
        for number, row in enumerate(reader, 2):
            if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
                raise ValueError(f'Blank or malformed required CSV value at line {number}')
            row = {key: row[key].strip() for key in required}
            exp = row['experiment_id']
            if exp not in ids:
                raise ValueError(f'Unknown experiment ID at line {number}: {exp}')
            if row['manifest_sha256'] != ids[exp]['manifest_sha256']:
                raise ValueError(f'CSV/manifest fingerprint mismatch at line {number}')
            seed = str(int(row['seed']))
            if seed_plans[exp] is not None and seed not in seed_plans[exp]:
                raise ValueError('Observed seed is outside the frozen seed plan: ' + seed)
            value = float(row['value'])
            if not math.isfinite(value):
                raise ValueError('Non-finite observation')
            if row['unit'] == 'fraction' and not 0 <= value <= 1:
                raise ValueError('fraction values must be within [0, 1]')
            if row['unit'] == 'percent' and not 0 <= value <= 100:
                raise ValueError('percent values must be within [0, 100]')
            group = (row['task'], row['metric'])
            if group in units and units[group] != row['unit']:
                raise ValueError('Unit mismatch within a task/metric')
            units[group] = row['unit']
            key = (exp, *group, seed)
            if key in rows:
                raise ValueError('Duplicate experiment/task/metric/seed observation: ' + str(key))
            rows[key] = value
    if not rows:
        raise ValueError('CSV contains no observations')
    output, complete = [], all(plan is not None for plan in seed_plans.values())
    for task, metric in sorted(units):
        a = {k[3]: v for k, v in rows.items() if k[:3] == (control['experiment_id'], task, metric)}
        b = {k[3]: v for k, v in rows.items() if k[:3] == (experiment['experiment_id'], task, metric)}
        paired = sorted(a.keys() & b.keys(), key=int)
        expected_seeds = set(a) | set(b) | (seed_plans[control['experiment_id']] or set()) | (seed_plans[experiment['experiment_id']] or set())
        missing_a, missing_b = sorted(expected_seeds-a.keys(), key=int), sorted(expected_seeds-b.keys(), key=int)
        complete = complete and not missing_a and not missing_b
        deltas = [b[seed]-a[seed] for seed in paired]
        output.append({'task': task, 'metric': metric, 'unit': units[(task, metric)],
                       'paired_seed_count': len(paired),
                       'pairs': [{'seed': seed, 'control': a[seed], 'experiment': b[seed],
                                  'delta_experiment_minus_control': b[seed]-a[seed]} for seed in paired],
                       'missing_control_seeds': missing_a, 'missing_experiment_seeds': missing_b,
                       'mean_control_paired': statistics.mean(a[s] for s in paired) if paired else None,
                       'mean_experiment_paired': statistics.mean(b[s] for s in paired) if paired else None,
                       'mean_delta': statistics.mean(deltas) if deltas else None,
                       'sample_sd_delta': statistics.stdev(deltas) if len(deltas) > 1 else None,
                       'ci': None, 'decision': 'interpret_against_predeclared_metric_direction_and_threshold'})
    return {'schema_version': 1, 'kind': 'observed_result_summary',
            'control_id': control['experiment_id'], 'experiment_id': experiment['experiment_id'],
            'control_sha256': control['manifest_sha256'], 'experiment_sha256': experiment['manifest_sha256'],
            'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            'audit': expected, 'pairing_complete': bool(complete), 'groups': output,
            'seed_plan_verified_against_declared_config': all(plan is not None for plan in seed_plans.values()),
            'interpretation_status': 'review_required' if complete and not config_incomplete and expected['status'] == 'within_declared_scope'
                                     else 'incomplete_or_confounded',
            'evidence_status': 'user_supplied_observations_not_independently_reproduced',
            'mechanism_benefit_proven': False}


def append_history(path, report):
    key = fingerprint(report)
    marker = '<!-- result-import:' + key + ' -->'
    content = path.read_text(encoding='utf-8') if path.exists() else '# 研究历史\n'
    if marker in content:
        return False
    date = datetime.now(timezone.utc).isoformat()
    lines = ['\n' + marker, f'\n## {report["experiment_id"]} — 结果导入 {date}',
             '\n- 状态：evaluated（用户提供观测；不代表独立复现或机制有效）',
             '- 对照：' + report['control_id'], '- CSV SHA-256：' + report['csv_sha256'],
             '- 实验 manifest SHA-256：' + report['experiment_sha256'],
             '- 审查状态：' + report['interpretation_status'],
             '- 唯一因素声明：' + report['audit']['factor']]
    for group in report['groups']:
        lines.append('- ' + json_line(group))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        if not path.stat().st_size:
            handle.write(content)
        handle.write('\n'.join(lines) + '\n')
    return True


def json_line(value):
    import json
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--experiment', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--history', type=Path, help='Append an idempotent entry to project research_history.md')
    args = p.parse_args()
    try:
        report = summarize(args.csv, manifest(args.control), manifest(args.experiment), read_json(args.audit))
        emit(report, args.out)
        if args.history:
            append_history(args.history, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
