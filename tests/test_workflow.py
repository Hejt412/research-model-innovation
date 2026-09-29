"""CLI workflow acceptance on authored fixtures, never executing project code."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        shutil.copytree(REPO / 'evals' / 'fixtures' / 'mini_project', self.project)

    def cli(self, script, *args, code=0):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(REPO / 'scripts' / script), *map(str, args)],
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def dump(self, name, data):
        path = self.base / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_fixture_scan_and_peer_model_evidence(self):
        inventory = json.loads(self.cli('analyze_models.py', self.project).stdout)
        self.assertEqual({r['class'] for r in inventory['models']}, {'Baseline', 'Candidate'})
        report = self.dump('models.json', inventory)
        compared = json.loads(self.cli('compare_models.py', report, '--left-model', 'model.py::Baseline',
                                      '--right-model', 'model.py::Candidate').stdout)
        row = compared['comparisons'][0]
        self.assertTrue(any('gate' in x for x in row['assignments_added']))
        self.assertTrue(row['architecture_evidence']['left']['input_representation']['evidence'])

    def test_end_to_end_confounded_result_is_archived_without_validation(self):
        config = {'model': {'name': 'Baseline'}, 'training': {'lr': .001, 'loss': 'ce', 'seeds': [11, 22]},
                  'protocol': {'target_query_labels': False}}
        config_path = self.dump('effective.json', config)
        control_path, experiment_path, audit_path = [self.base / x for x in ('e0.json', 'e1.json', 'audit.json')]
        self.cli('experiment_manifest.py', 'snapshot', self.project, '--config', config_path,
                 '--experiment-id', 'E0', '--out', control_path)
        config['model']['name'] = 'Candidate'
        config['training']['lr'] = .01
        config['protocol']['target_query_labels'] = True
        self.dump('effective.json', config)
        self.cli('experiment_manifest.py', 'snapshot', self.project, '--config', config_path,
                 '--experiment-id', 'E1', '--control-id', 'E0', '--out', experiment_path)
        self.cli('experiment_manifest.py', 'check', control_path, experiment_path, '--factor', 'candidate model',
                 '--allow-config', '/model/name', '--out', audit_path, code=2)
        audit = json.loads(audit_path.read_text())
        self.assertEqual({x['path'] for x in audit['unexpected_config_changes']}, {'/training/lr', '/protocol/target_query_labels'})
        records = [json.loads(p.read_text()) for p in (control_path, experiment_path)]
        result_csv = self.base / 'results.csv'
        with result_csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['experiment_id', 'seed', 'task', 'metric', 'value', 'unit', 'manifest_sha256'])
            for record in records:
                for seed in [11, 22]:
                    writer.writerow([record['experiment_id'], seed, 'fixture', 'accuracy', .75, 'fraction', record['manifest_sha256']])
        summary, history = self.base / 'summary.json', self.base / 'history.md'
        self.cli('import_results.py', result_csv, '--control', control_path, '--experiment', experiment_path,
                 '--audit', audit_path, '--out', summary, '--history', history)
        result = json.loads(summary.read_text())
        self.assertEqual(result['interpretation_status'], 'incomplete_or_confounded')
        self.assertFalse(result['mechanism_benefit_proven'])
        self.assertIn('incomplete_or_confounded', history.read_text(encoding='utf-8'))

    def test_manifest_cannot_include_its_own_output(self):
        config = self.dump('config.json', {'training': {'seeds': [1]}})
        self.cli('experiment_manifest.py', 'snapshot', self.project, '--config', config,
                 '--experiment-id', 'E0', '--out', self.project / 'manifest.json', code=2)
        self.assertFalse((self.project / 'manifest.json').exists())

    def test_ledger_commands_preserve_abstract_limit(self):
        blank = {'schema_version': 1, 'papers': [], 'claims': [], 'searches': []}
        original = self.dump('empty.json', blank)
        data = {'schema_version': 1,
                'papers': [{'id': 'fixture', 'title': 'Synthetic fixture only', 'authors': ['Fixture author'],
                            'url': 'https://example.org/fixture', 'version': 'fixture', 'access': 'abstract_only', 'checked_at': '2026-01-01'}],
                'claims': [{'id': 'C1', 'paper_id': 'fixture', 'text': 'Synthetic mechanism claim', 'kind': 'mechanism', 'locator': 'abstract'}],
                'searches': [{'date': '2026-01-01', 'source': 'fixture', 'stage': 'same_domain', 'query': 'prototype correction'}]}
        incoming = self.dump('incoming.json', data)
        output = self.base / 'merged.json'
        self.cli('literature_ledger.py', 'merge', original, incoming, '--out', output)
        self.assertEqual(json.loads(output.read_text())['claim_audit'][0]['status'], 'insufficient_method_access')
        plan = json.loads(self.cli('literature_ledger.py', 'plan', output, '--as-of', '2026-09-29').stdout)
        self.assertIsNone(plan['incremental_queries'][0]['date_lower_bound'])


if __name__ == '__main__':
    unittest.main()
