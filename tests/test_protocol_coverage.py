from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _config_schema import UNKNOWN, validate_config
from data_protocol import compare_plans, inspect_plan
from experiment_manifest import audit, snapshot
from import_results import summarize


def config():
    return {'model': {'baseline': 'Fixture', 'adapter': False}, 'data': {'dataset_id': 'fixture'},
            'protocol': {'split': 'device_holdout', 'target_label_access': 'support_only'},
            'training': {'seeds': [1, 2], 'lr': .001, 'scheduler': None, 'augmentation': None},
            'evaluation': {'sampling': 'episodic', 'tasks': ['A-to-B', 'A-to-C'], 'metrics': [
                {'name': 'accuracy', 'unit': 'fraction', 'direction': 'higher', 'role': 'primary', 'required': True},
                {'name': 'macro_f1', 'unit': 'fraction', 'direction': 'higher', 'role': 'secondary', 'required': True}]}}


def data_plan():
    return {'schema_version': 1, 'mode': 'episodic', 'samples': [
        {'sample_id': 's1', 'record_id': 'r1', 'device_id': 'd1', 'split': 'train'},
        {'sample_id': 's2', 'record_id': 'r2', 'device_id': 'd2', 'split': 'test', 'class_id': 'c1'},
        {'sample_id': 's3', 'record_id': 'r3', 'device_id': 'd2', 'split': 'test', 'class_id': 'c1'},
        {'sample_id': 's4', 'record_id': 'r4', 'device_id': 'd2', 'split': 'test', 'class_id': 'c1'}],
        'few_shot': {task: {'n_way': 1, 'k_shot': 1, 'query_per_class': 2, 'episodes_per_seed': 1} for task in ['A-to-B', 'A-to-C']},
        'policy': {'split_disjoint_by': ['sample_id', 'record_id', 'device_id'],
                   'support_query_disjoint_by': ['sample_id', 'record_id'],
                   'task_splits': {task: {'support': ['test'], 'query': ['test']} for task in ['A-to-B', 'A-to-C']}},
        'episodes': [{'task': task, 'seed': seed, 'episode_id': '0', 'support': ['s2'], 'query': ['s3', 's4']}
                     for task in ['A-to-B', 'A-to-C'] for seed in [1, 2]]}


class ConfigTests(unittest.TestCase):
    def test_valid_disabled_scheduler_is_not_unknown(self):
        result = validate_config(config())
        self.assertTrue(result['complete'])
        self.assertIn('/training/scheduler', result['disabled'])
        self.assertEqual(result['unknown'], [])

    def test_missing_required_fields_and_explicit_unknown_are_distinct(self):
        cfg = config()
        del cfg['data']
        cfg['protocol']['split'] = UNKNOWN
        result = validate_config(cfg)
        self.assertIn('/data/dataset_id', result['missing'])
        self.assertIn('/protocol/split', result['unknown'])
        self.assertFalse(result['complete'])

    def test_invalid_types_ranges_and_duplicate_seeds(self):
        for value in ([True], [1.5], [-1], [1, 1], []):
            cfg = config()
            cfg['training']['seeds'] = value
            self.assertTrue(validate_config(cfg)['invalid'])
        for key, value in [('lr', -1), ('lr', True), ('lr', float('inf')), ('epochs', 1.5)]:
            cfg = config()
            cfg['training'][key] = value
            self.assertTrue(validate_config(cfg)['invalid'])

    def test_bad_metric_or_duplicate_tasks_are_rejected(self):
        cfg = config()
        cfg['evaluation']['tasks'] = ['A', 'A']
        self.assertTrue(validate_config(cfg)['invalid'])
        cfg = config()
        cfg['evaluation']['metrics'][0]['required'] = False
        self.assertTrue(validate_config(cfg)['invalid'])
        cfg = config()
        cfg['evaluation']['metrics'] = ['accuracy']
        self.assertTrue(validate_config(cfg)['invalid'])

    def test_malformed_training_section_does_not_crash(self):
        cfg = config()
        cfg['training'] = []
        self.assertTrue(validate_config(cfg)['invalid'])


class DataProtocolTests(unittest.TestCase):
    def test_same_plan_and_catalogue_order(self):
        a, b = data_plan(), data_plan()
        b['samples'].reverse()
        result = compare_plans(a, b)
        self.assertTrue(result['equal_declared_plan'])
        self.assertFalse(result['actual_sampling_verified'])

    def test_same_seed_different_episode_order_is_detected(self):
        a, b = data_plan(), data_plan()
        b['episodes'][0]['query'].reverse()
        self.assertIn('episodes_sha256', compare_plans(a, b)['changed_components'])

    def test_record_and_device_overlap_across_splits(self):
        data = data_plan()
        data['samples'][1]['record_id'] = 'r1'
        data['samples'][1]['device_id'] = 'd1'
        fields = {row['field'] for row in inspect_plan(data)['issues'] if row['kind'] == 'cross_split_overlap'}
        self.assertEqual(fields, {'record_id', 'device_id'})

    def test_support_query_overlap(self):
        data = data_plan()
        data['episodes'][0]['query'] = ['s2']
        self.assertTrue(any(row['kind'] == 'support_query_overlap' for row in inspect_plan(data)['issues']))

    def test_wrong_split_and_unknown_sample(self):
        data = data_plan()
        data['episodes'][0]['support'] = ['s1']
        self.assertTrue(any(row['kind'] == 'episode_split_violation' for row in inspect_plan(data)['issues']))
        data['episodes'][0]['support'] = ['absent']
        with self.assertRaises(ValueError):
            inspect_plan(data)

    def test_duplicate_ids_and_episode_identity(self):
        data = data_plan()
        data['samples'].append(data['samples'][0])
        with self.assertRaises(ValueError):
            inspect_plan(data)
        data = data_plan()
        data['episodes'].append(data['episodes'][0])
        with self.assertRaises(ValueError):
            inspect_plan(data)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'model.py').write_text('value = 1\n')
        self.csv = self.root / 'results.csv'
        self.cfg = config()
        self.plan = data_plan()
        self.freeze()

    def freeze(self):
        cfg_path, data_path = self.root / 'cfg.json', self.root / 'data.json'
        data_path.write_text(json.dumps(self.plan))
        self.cfg['model']['adapter'] = False
        cfg_path.write_text(json.dumps(self.cfg))
        self.a = snapshot(self.project, cfg_path, 'E0', data_plan=data_path)
        self.cfg['model']['adapter'] = True
        cfg_path.write_text(json.dumps(self.cfg))
        self.b = snapshot(self.project, cfg_path, 'E1', 'E0', data_path)
        self.check = audit(self.a, self.b, 'adapter', ['/model/adapter'], [])

    def rows(self):
        return [{'experiment_id': exp['experiment_id'], 'seed': seed, 'task': task, 'metric': metric['name'],
                 'unit': metric['unit'], 'value': .75, 'manifest_sha256': exp['manifest_sha256']}
                for exp in (self.a, self.b) for task in self.cfg['evaluation']['tasks']
                for metric in self.cfg['evaluation']['metrics'] for seed in (1, 2)]

    def result(self, rows):
        with self.csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.rows()[0]))
            writer.writeheader()
            writer.writerows(rows)
        return summarize(self.csv, self.a, self.b, self.check)

    def test_complete_evaluation_and_data_plan(self):
        result = self.result(self.rows())
        self.assertTrue(result['pairing_complete'])
        self.assertTrue(result['coverage']['task_metric_groups_complete'])
        self.assertEqual(result['interpretation_status'], 'review_required')

    def test_entire_task_and_metric_absent_from_both_experiments(self):
        result = self.result([r for r in self.rows() if r['task'] == 'A-to-B' and r['metric'] == 'accuracy'])
        self.assertFalse(result['pairing_complete'])
        self.assertFalse(result['coverage']['tasks_complete'])
        self.assertFalse(result['coverage']['required_metrics_complete'])
        self.assertEqual(result['coverage']['missing_tasks']['E0'], ['A-to-C'])
        self.assertEqual(result['coverage']['missing_metrics']['E1'], ['macro_f1'])
        self.assertEqual(len(result['groups']), 4)

    def test_each_task_and_metric_present_but_one_combination_absent(self):
        result = self.result([r for r in self.rows() if (r['task'], r['metric']) != ('A-to-C', 'macro_f1')])
        self.assertTrue(result['coverage']['tasks_complete'])
        self.assertTrue(result['coverage']['required_metrics_complete'])
        self.assertFalse(result['coverage']['task_metric_groups_complete'])

    def test_optional_metric_can_be_absent(self):
        self.cfg['evaluation']['metrics'][1]['required'] = False
        self.freeze()
        result = self.result([r for r in self.rows() if r['metric'] == 'accuracy'])
        self.assertTrue(result['pairing_complete'])

    def test_unplanned_task_metric_or_unit_is_rejected(self):
        for key, value in [('task', 'unknown'), ('metric', 'unknown'), ('unit', 'percent')]:
            rows = self.rows()
            rows[0][key] = value
            with self.assertRaises(ValueError):
                self.result(rows)

    def test_different_sampling_prevents_protocol_confirmation(self):
        self.b['data_protocol'] = inspect_plan({**self.plan, 'episodes': list(reversed(self.plan['episodes']))})
        self.check = audit(self.a, self.b, 'adapter', ['/model/adapter'], [])
        result = self.result(self.rows())
        self.assertEqual(result['data_protocol_status'], 'declared_plan_changed')
        self.assertEqual(result['interpretation_status'], 'incomplete_or_confounded')

    def test_episode_plan_must_cover_all_declared_task_seeds(self):
        self.plan['episodes'] = self.plan['episodes'][:-1]
        self.freeze()
        result = self.result(self.rows())
        self.assertEqual(result['data_protocol_status'], 'protocol_conflicts')
        self.assertTrue(any(i['kind'] == 'missing_task_seed_episodes' for i in self.a['data_protocol']['issues']))


if __name__ == '__main__':
    unittest.main()
