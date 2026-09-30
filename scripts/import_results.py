"""Pair user-supplied observations; never run training or infer missing results."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import statistics
from _records import fingerprint, manifest, read_json
from _static import emit
from experiment_manifest import audit
from _config_schema import evaluation_plan, validate_config
from _paired_statistics import assess
from _versions import annotate, require_readable
from run_records import ARTIFACTS, verify as verify_runs
from _innovation_metadata import link as link_innovation


def summarize(csv_path, control, experiment, audit_record, run_records=None, innovation_metadata=None):
    audit_version = require_readable(audit_record)
    # Recompute the audit instead of trusting a hand-edited status field.
    expected = audit(control, experiment, audit_record['factor'],
                     audit_record['declared_config_paths'], audit_record['declared_files'])
    # Producer identity can differ across clean checkouts/installations running
    # identical rules. Recompute all substantive fields, not the producer stamp.
    if {k: v for k, v in audit_record.items() if k != 'producer'} != {k: v for k, v in expected.items() if k != 'producer'}:
        raise ValueError('Audit does not match the supplied manifests/declaration')
    innovation_link = link_innovation(innovation_metadata, control, experiment)
    config_incomplete = any(expected['unresolved_config_paths'].values())
    ids = {control['experiment_id']: control, experiment['experiment_id']: experiment}
    plans = {key: evaluation_plan(record['config']) for key, record in ids.items()}
    seed_plans = {}
    for exp_id, record in ids.items():
        invalid = validate_config(record['config'])['invalid']
        if invalid:
            raise ValueError('Invalid declared configuration: ' + str(invalid))
        seed_plans[exp_id] = set(plans[exp_id]['seeds']) or None
    rows, units, source_rows = {}, {}, []
    with csv_path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'experiment_id', 'seed', 'task', 'metric', 'value', 'unit', 'manifest_sha256'}
        if reader.fieldnames and len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('Duplicate CSV column names')
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV missing required columns: ' + ', '.join(sorted(required)))
        for number, row in enumerate(reader, 2):
            if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
                raise ValueError(f'Blank or malformed required CSV value at line {number}')
            run_id = row.get('run_id')
            row = {key: row[key].strip() for key in required}
            if isinstance(run_id, str) and run_id.strip():
                row['run_id'] = run_id.strip()
            exp = row['experiment_id']
            if exp not in ids:
                raise ValueError(f'Unknown experiment ID at line {number}: {exp}')
            if row['manifest_sha256'] != ids[exp]['manifest_sha256']:
                raise ValueError(f'CSV/manifest fingerprint mismatch at line {number}')
            plan = plans[exp]
            if plan['tasks'] and row['task'] not in plan['tasks']:
                raise ValueError('Observed task is outside declared plan: ' + row['task'])
            if plan['metrics']:
                if row['metric'] not in plan['metrics']:
                    raise ValueError('Observed metric is outside declared plan: ' + row['metric'])
                if row['unit'] != plan['metrics'][row['metric']]['unit']:
                    raise ValueError('Observed unit differs from the metric plan')
            seed = str(int(row['seed']))
            if int(seed) < 0:
                raise ValueError('Observed seed must be nonnegative')
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
            source_rows.append({**row, 'seed': seed})
    if not rows:
        raise ValueError('CSV contains no observations')
    required_groups = {(task, name) for plan in plans.values() for task in plan['tasks']
                       for name, metric in plan['metrics'].items() if metric.get('required') is True}
    output, complete = [], all(plan['declared'] for plan in plans.values())
    missing_tasks, missing_metrics, missing_groups = {}, {}, {}
    for exp_id, plan in plans.items():
        observed_groups = {(key[1], key[2]) for key in rows if key[0] == exp_id}
        missing_tasks[exp_id] = sorted(set(plan['tasks']) - {task for task, _ in observed_groups})
        missing_metrics[exp_id] = sorted({name for name, metric in plan['metrics'].items() if metric.get('required') is True}
                                         - {name for _, name in observed_groups})
        missing_groups[exp_id] = [list(group) for group in sorted(required_groups - observed_groups)]
    for task, metric in sorted(set(units) | required_groups):
        a = {k[3]: v for k, v in rows.items() if k[:3] == (control['experiment_id'], task, metric)}
        b = {k[3]: v for k, v in rows.items() if k[:3] == (experiment['experiment_id'], task, metric)}
        paired = sorted(a.keys() & b.keys(), key=int)
        expected_seeds = set(a) | set(b) | (seed_plans[control['experiment_id']] or set()) | (seed_plans[experiment['experiment_id']] or set())
        missing_a, missing_b = sorted(expected_seeds-a.keys(), key=int), sorted(expected_seeds-b.keys(), key=int)
        complete = complete and not missing_a and not missing_b
        deltas = [b[seed]-a[seed] for seed in paired]
        unit = units.get((task, metric)) or next(p['metrics'][metric]['unit'] for p in plans.values() if metric in p['metrics'])
        output.append({'task': task, 'metric': metric, 'unit': unit,
                       'paired_seed_count': len(paired),
                       'pairs': [{'seed': seed, 'control': a[seed], 'experiment': b[seed],
                                  'delta_experiment_minus_control': b[seed]-a[seed]} for seed in paired],
                       'missing_control_seeds': missing_a, 'missing_experiment_seeds': missing_b,
                       'mean_control_paired': statistics.mean(a[s] for s in paired) if paired else None,
                       'mean_experiment_paired': statistics.mean(b[s] for s in paired) if paired else None,
                       'mean_delta': statistics.mean(deltas) if deltas else None,
                       'sample_sd_delta': statistics.stdev(deltas) if len(deltas) > 1 else None,
                       'ci': None, 'decision': 'interpret_against_predeclared_metric_direction_and_threshold'})
    eligible = bool(complete and not config_incomplete and expected['status'] == 'within_declared_scope'
                    and expected['data_protocol_status'] == 'same_declared_plan'
                    and expected['source_coverage']['status'] == 'complete_in_declared_scope'
                    and audit_version['status'] == 'supported_current'
                    and all(v['status'] == 'supported_current' for v in expected['input_versions'].values()))
    run_provenance = verify_runs(run_records, ids, source_rows)
    stats_a = control['config'].get('evaluation', {}).get('statistics')
    stats_b = experiment['config'].get('evaluation', {}).get('statistics')
    for group in output:
        name = group['metric']
        metric_a = plans[control['experiment_id']]['metrics'].get(name, {})
        metric_b = plans[experiment['experiment_id']]['metrics'].get(name, {})
        declaration_equal = stats_a == stats_b and metric_a == metric_b
        if stats_a == {'state': 'unknown'} or stats_b == {'state': 'unknown'}:
            stats = None
        else:
            stats = stats_a or stats_b
        assessment = assess([pair['delta_experiment_minus_control'] for pair in group['pairs']], metric_a or metric_b,
                            stats, eligible and declaration_equal and run_provenance['statistical_use_allowed'])
        group.update({'statistics': assessment, 'ci': assessment['ci'], 'decision': assessment['decision'],
                      'direction': metric_a.get('direction'), 'min_improvement': metric_a.get('min_improvement')})
    return annotate({'schema_version': 2, 'kind': 'observed_result_summary',
            'control_id': control['experiment_id'], 'experiment_id': experiment['experiment_id'],
            'control_sha256': control['manifest_sha256'], 'experiment_sha256': experiment['manifest_sha256'],
            'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            'audit': expected, 'pairing_complete': bool(complete), 'groups': output,
            'supplied_audit_producer': audit_record.get('producer'),
            'run_provenance': run_provenance,
            'innovation_link': innovation_link,
            'coverage': {'plan_declared': all(p['declared'] for p in plans.values()),
                         'tasks_complete': all(p['declared'] for p in plans.values()) and not any(missing_tasks.values()),
                         'required_metrics_complete': all(p['declared'] for p in plans.values()) and not any(missing_metrics.values()),
                         'task_metric_groups_complete': all(p['declared'] for p in plans.values()) and not any(missing_groups.values()),
                         'missing_tasks': missing_tasks, 'missing_metrics': missing_metrics, 'missing_task_metric_groups': missing_groups},
            'seed_plan_verified_against_declared_config': all(plan is not None for plan in seed_plans.values()),
            'data_protocol_status': expected['data_protocol_status'],
            'interpretation_status': 'review_required' if eligible
                                     else 'incomplete_or_confounded',
            'evidence_status': 'user_supplied_observations_not_independently_reproduced',
            'mechanism_benefit_proven': False})


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
             '- 对照 manifest SHA-256：' + report['control_sha256'],
             '- 实验 manifest SHA-256：' + report['experiment_sha256'],
             '- 审查状态：' + report['interpretation_status'],
             '- 唯一因素声明：' + report['audit']['factor']]
    association = report.get('innovation_link', {})
    if association.get('status') == 'linked_declared_metadata_review_required':
        metadata = association['metadata']
        history_marker = '<!-- innovation-history:' + fingerprint({k: metadata[k] for k in ('research_id', 'history_id')}) + ' -->'
        lines[1] = f'\n## {metadata["history_id"]} — {metadata["innovation_id"]} — {report["experiment_id"]} — 结果导入 {date}'
        lines.extend([history_marker,
                      '- 机制身份：已关联用户元数据，待人工核对证据内容',
                      '- 研究 ID：' + metadata['research_id'],
                      '- I/G/P/H 关联：' + json_line({k: metadata[k] for k in ('innovation_id', 'gap_ids', 'paper_ids', 'history_id')}),
                      '- 机制指纹（位置+变换+数据依赖+目标）：' + json_line(metadata['mechanism_fingerprint']),
                      '- 机制指纹 SHA-256（仅精确内容比较）：' + association['mechanism_fingerprint_sha256'],
                      '- 创新元数据原文件/内容 SHA-256：' + association['metadata_file_sha256'] + ' / ' + association['metadata_record_sha256'],
                      '- 创新元数据路径：' + association['metadata_path'],
                      '- 来源创新卡：' + json_line(association['source_card']),
                      '- 指纹摘要不能判断数学/概念等价；关联不证明新颖性、机制因果或收益。'])
        if history_marker in content:
            lines.append('- 同研究/H-ID 的追加记录或修订：保留既有条目，本次不覆盖旧结论。')
    else:
        lines.append('- 机制身份：未关联；G/P/I/H、研究 ID、机制指纹及来源卡待人工补齐，未生成任何研究身份。')
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


def reject_output_aliases(outputs, inputs):
    """Reject resolved paths and existing hard links before any result/history write."""
    outputs = [Path(path) for path in outputs if path is not None]
    inputs = [Path(path) for path in inputs if path is not None]
    for index, output in enumerate(outputs):
        for original in inputs + outputs[:index]:
            same_path = os.path.normcase(str(output.resolve())) == os.path.normcase(str(original.resolve()))
            same_file = output.exists() and original.exists() and os.path.samefile(output, original)
            if same_path or same_file:
                raise ValueError('Output/history must not overwrite an input or share a target: ' + str(output))


def run_artifact_paths(ledger_path):
    if ledger_path is None:
        return []
    from record_versions import unwrap
    ledger = unwrap(read_json(ledger_path))
    return [ledger_path.parent / run['artifacts'][kind]['path'] for run in ledger['runs']
            for kind in ARTIFACTS]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--experiment', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--history', type=Path, help='Append an idempotent entry to project research_history.md')
    p.add_argument('--run-records', type=Path, help='Completed-run ledger; missing/conflicting provenance blocks statistical decisions')
    p.add_argument('--innovation-metadata', type=Path, help='Explicit research/mechanism and G/P/I/H links; never infer them from filenames')
    args = p.parse_args()
    try:
        from record_versions import unwrap
        inputs = [args.csv, args.control, args.experiment, args.audit, args.run_records, args.innovation_metadata]
        outputs = [args.out, args.history]
        reject_output_aliases(outputs, inputs)
        report = summarize(args.csv, manifest(args.control), manifest(args.experiment), unwrap(read_json(args.audit)),
                           args.run_records, args.innovation_metadata)
        inputs.extend(run_artifact_paths(args.run_records))
        if args.innovation_metadata is not None:
            inputs.append(report['innovation_link']['source_card']['path'])
        reject_output_aliases(outputs, inputs)
        emit(report, args.out)
        if args.history:
            append_history(args.history, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
