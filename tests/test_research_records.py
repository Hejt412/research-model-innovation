import csv
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _records import manifest, read_json
from experiment_manifest import audit, snapshot
from import_results import append_history, summarize
from literature_ledger import merge, plan
from datetime import date


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.model = self.project / 'model.py'
        self.model.write_text('value = 1\n')
        self.config = self.base / 'effective.json'
        self.settings = {'model': {'adapter': False}, 'training': {'lr': 0.001, 'seeds': [1, 2]}, 'protocol': {'split': 'split-v1'}}
        self.config.write_text(json.dumps(self.settings))
        self.control = snapshot(self.project, self.config, 'E0')
        self.settings['model']['adapter'] = True
        self.config.write_text(json.dumps(self.settings))
        self.experiment = snapshot(self.project, self.config, 'E1', 'E0')
        self.audit = audit(self.control, self.experiment, 'adapter switch', ['/model/adapter'], [])
        self.csv = self.base / 'results.csv'

    def observations(self):
        return [{'experiment_id': exp['experiment_id'], 'seed': str(seed), 'task': 'A-to-B',
                 'metric': 'accuracy', 'value': value, 'unit': 'fraction',
                 'manifest_sha256': exp['manifest_sha256']}
                for exp, values in [(self.control, [0.70, 0.72]), (self.experiment, [0.73, 0.77])]
                for seed, value in zip([1, 2], values)]

    def write_results(self, rows):
        with self.csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.observations()[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_single_declared_change(self):
        self.assertEqual(self.audit['status'], 'within_declared_scope')
        self.assertFalse(self.audit['single_factor_causality_verified'])

    def test_extra_lr_and_source_changes(self):
        self.settings['training']['lr'] = 0.01
        self.config.write_text(json.dumps(self.settings))
        self.model.write_text('value = 2\n')
        experiment = snapshot(self.project, self.config, 'E1', 'E0')
        result = audit(self.control, experiment, 'adapter', ['/model/adapter'], [])
        self.assertEqual(result['status'], 'extra_changes_detected')
        self.assertEqual(result['unexpected_config_changes'][0]['path'], '/training/lr')
        self.assertEqual(result['unexpected_file_changes'], ['model.py'])

    def test_manifest_tamper_and_wrong_control(self):
        path = self.base / 'manifest.json'
        tampered = deepcopy(self.control)
        tampered['config']['training']['lr'] = 123
        path.write_text(json.dumps(tampered))
        with self.assertRaises(ValueError):
            manifest(path)
        bad = deepcopy(self.experiment)
        bad['control_id'] = 'wrong'
        with self.assertRaises(ValueError):
            audit(self.control, bad, 'adapter', [], [])

    def test_unresolved_config_is_not_a_complete_protocol(self):
        self.settings['protocol']['split'] = None
        self.config.write_text(json.dumps(self.settings))
        self.experiment = snapshot(self.project, self.config, 'E1', 'E0')
        self.audit = audit(self.control, self.experiment, 'adapter', ['/model/adapter', '/protocol/split'], [])
        self.write_results(self.observations())
        result = summarize(self.csv, self.control, self.experiment, self.audit)
        self.assertEqual(result['interpretation_status'], 'incomplete_or_confounded')
        self.assertIn('/protocol/split', result['audit']['unresolved_config_paths']['experiment'])

    def test_bool_number_difference_and_pointer_escaping(self):
        from _records import changes
        self.assertEqual(changes({'a/b': False}, {'a/b': 0})[0]['path'], '/a~1b')

    def test_paired_results_and_idempotent_history(self):
        self.write_results(self.observations())
        result = summarize(self.csv, self.control, self.experiment, self.audit)
        self.assertTrue(result['pairing_complete'])
        self.assertAlmostEqual(result['groups'][0]['mean_delta'], .04)
        self.assertAlmostEqual(result['groups'][0]['sample_sd_delta'], .0141421356)
        history = self.base / 'research_history.md'
        history.write_text('# Existing history\n\nFailed experiment retained.\n', encoding='utf-8')
        self.assertTrue(append_history(history, result))
        first = history.read_text(encoding='utf-8')
        self.assertFalse(append_history(history, result))
        self.assertEqual(first, history.read_text(encoding='utf-8'))
        self.assertIn('Failed experiment retained.', first)

    def test_missing_seed_is_not_silently_discarded(self):
        self.write_results(self.observations()[:-1])
        result = summarize(self.csv, self.control, self.experiment, self.audit)
        self.assertFalse(result['pairing_complete'])
        self.assertEqual(result['groups'][0]['missing_experiment_seeds'], ['2'])
        self.assertEqual(result['interpretation_status'], 'incomplete_or_confounded')

    def test_seed_missing_from_both_runs_is_reported(self):
        self.write_results([row for row in self.observations() if row['seed'] == '1'])
        result = summarize(self.csv, self.control, self.experiment, self.audit)
        self.assertFalse(result['pairing_complete'])
        self.assertEqual(result['groups'][0]['missing_control_seeds'], ['2'])
        self.assertEqual(result['groups'][0]['missing_experiment_seeds'], ['2'])

    def test_duplicates_units_nonfinite_and_provenance(self):
        good = self.observations()
        invalid_sets = [good + [good[0]],
                        [{**good[0], 'value': 'NaN'}, *good[1:]],
                        [{**good[0], 'unit': 'percent'}, *good[1:]],
                        [{**good[0], 'manifest_sha256': 'wrong'}, *good[1:]],
                        [{**good[0], 'value': 1.5}, *good[1:]]]
        for rows in invalid_sets:
            with self.subTest(rows=rows):
                self.write_results(rows)
                with self.assertRaises(ValueError):
                    summarize(self.csv, self.control, self.experiment, self.audit)

    def test_edited_audit_cannot_hide_confounding(self):
        self.write_results(self.observations())
        wrong = deepcopy(self.audit)
        wrong['status'] = 'proven_effective'
        with self.assertRaises(ValueError):
            summarize(self.csv, self.control, self.experiment, wrong)

    def test_duplicate_json_keys_rejected(self):
        self.config.write_text('{"seed": 1, "seed": 2}')
        with self.assertRaises(ValueError):
            read_json(self.config)


class LiteratureTests(unittest.TestCase):
    def empty(self):
        return {'schema_version': 1, 'papers': [], 'claims': [], 'searches': []}

    def paper(self, **updates):
        # Synthetic metadata for software tests, not real literature.
        return {'id': 'P-test', 'title': 'Synthetic mechanism fixture', 'authors': ['Test Author'],
                'doi': '10.0000/test-fixture', 'url': 'https://example.org/test-fixture',
                'version': 'fixture', 'access': 'methods', 'checked_at': '2026-01-01', **updates}

    def test_doi_dedup_and_claim_alias(self):
        left, right = self.empty(), self.empty()
        left['papers'] = [self.paper()]
        right['papers'] = [self.paper(id='P-alias', doi='https://doi.org/10.0000/TEST-FIXTURE')]
        right['claims'] = [{'id': 'C1', 'text': 'Synthetic claim', 'paper_id': 'P-alias', 'kind': 'mechanism', 'locator': 'fixture section 1'}]
        value = merge(left, right)
        self.assertEqual(len(value['papers']), 1)
        self.assertEqual(value['claims'][0]['paper_id'], 'P-test')
        self.assertEqual(merge(value, right), value)

    def test_conflicts_are_retained(self):
        left, right = self.empty(), self.empty()
        left['papers'] = [self.paper()]
        right['papers'] = [self.paper(title='Different synthetic title')]
        value = merge(left, right)
        self.assertEqual(value['papers'][0]['title'], 'Synthetic mechanism fixture')
        self.assertEqual(len(value['conflicts']), 1)

    def test_abstract_does_not_support_mechanism(self):
        incoming = self.empty()
        incoming['papers'] = [self.paper(access='abstract_only')]
        incoming['claims'] = [{'id': 'C1', 'text': 'Synthetic method claim', 'paper_id': 'P-test', 'kind': 'mechanism', 'locator': 'abstract'}]
        value = merge(self.empty(), incoming)
        self.assertEqual(value['claim_audit'][0]['status'], 'insufficient_method_access')

    def test_title_similarity_never_automatically_merges_versions(self):
        incoming = self.empty()
        incoming['papers'] = [self.paper(), self.paper(id='P-other', doi=None, url='https://example.org/other')]
        value = merge(self.empty(), incoming)
        self.assertEqual(len(value['papers']), 2)
        self.assertEqual(value['possible_version_pairs_to_review'], [['P-test', 'P-other']])

    def test_explicit_version_group_requires_evidence(self):
        incoming = self.empty()
        incoming['papers'] = [self.paper(work_id='W1')]
        with self.assertRaises(ValueError):
            merge(self.empty(), incoming)
        incoming['papers'] = [self.paper(work_id='W1', relation_evidence='https://example.org/version-link'),
                              self.paper(id='P-v2', doi=None, version='fixture-v2', url='https://example.org/v2',
                                         work_id='W1', relation_evidence='https://example.org/version-link')]
        result = merge(self.empty(), incoming)
        self.assertEqual(len(result['papers']), 2)
        self.assertEqual(result['works']['W1']['version_ids'], ['P-test', 'P-v2'])

    def test_duplicate_claim_ids_are_rejected(self):
        data = self.empty()
        claim = {'id': 'C1', 'text': 'fixture', 'paper_id': 'missing', 'kind': 'mechanism', 'locator': 'fixture'}
        data['claims'] = [claim, claim]
        with self.assertRaises(ValueError):
            merge(self.empty(), data)

    def test_refresh_preserves_older_prior_art(self):
        data = self.empty()
        data['papers'] = [self.paper()]
        data['searches'] = [{'date': '2026-01-01', 'stage': 'same_domain', 'source': 'fixture', 'query': 'prototype calibration'}]
        result = plan(data, date(2026, 9, 29), 90)
        self.assertEqual(result['recheck_papers'], ['P-test'])
        self.assertIsNone(result['incremental_queries'][0]['date_lower_bound'])
        self.assertFalse(result['network_search_executed'])


if __name__ == '__main__':
    unittest.main()
