import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _static import read_models
from _config_schema import validate_config
from _paired_statistics import assess, quantile, validate_statistics
from data_protocol import inspect_plan, compare_plans
from experiment_manifest import snapshot, audit
from trace_config import trace
from test_protocol_coverage import config, data_plan
import test_protocol_coverage


def statistics_plan():
    return {'method': 'paired_bootstrap_basic', 'independent_unit': 'training_seed',
            'comparison_scope': 'per_task_metric_unadjusted', 'confidence_level': .95,
            'resamples': 1000, 'min_pairs': 5, 'random_seed': 17}


class StaticEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def scan(self, source):
        (self.root / 'model.py').write_text(source, encoding='utf-8')
        return {r['class']: r for r in read_models(self.root, 2000000, [])['models']}

    def test_if_else_retains_both_values_and_opposite_guards(self):
        rows = self.scan('class Model:\n def __init__(self, enabled):\n  if enabled:\n   self.block = Attention()\n  else:\n   self.block = None\n def forward(self,x): return x\n')
        assignments = rows['Model']['effective_assignments']
        self.assertEqual([a['expression'] for a in assignments], ['Attention()', 'None'])
        self.assertEqual([a['guards'][0]['branch'] for a in assignments], ['then', 'else'])
        self.assertTrue(all(a['guards'][0]['test'] == 'enabled' for a in assignments))

    def test_parent_and_child_mutations_keep_origins_and_methods(self):
        rows = self.scan('class Parent:\n def __init__(self): self.block = Stem()\n def forward(self,x): return x\nclass Child(Parent):\n def __init__(self,flag):\n  super().__init__()\n  if flag: self.block = Adapter()\n def reset(self): self.block = None\n')
        assignments = rows['Child']['effective_assignments']
        self.assertEqual(len(assignments), 3)
        self.assertEqual(assignments[0]['origin'], 'model.py::Parent')
        self.assertEqual(assignments[-1]['method'], 'reset')

    def test_nested_guard_and_nested_function_scope(self):
        rows = self.scan('class Model:\n def __init__(self,a,b):\n  if a:\n   if b: self.x = 1\n  def helper(): self.hidden = 2\n def forward(self,x): return x\n')
        evidence = rows['Model']['effective_assignments']
        self.assertEqual(len(evidence), 1)
        self.assertEqual([g['test'] for g in evidence[0]['guards']], ['a', 'b'])

    def make_manifests(self, **kwargs):
        cfg = config()
        path = self.root / 'cfg.json'
        project = self.root / 'project'
        project.mkdir(exist_ok=True)
        (project / 'small.py').write_text('x=1\n')
        path.write_text(json.dumps(cfg))
        a = snapshot(project, path, 'E0', **kwargs)
        cfg['model']['adapter'] = True
        path.write_text(json.dumps(cfg))
        b = snapshot(project, path, 'E1', 'E0', **kwargs)
        return audit(a, b, 'adapter', ['/model/adapter'], [])

    def test_large_critical_source_does_not_confirm_freeze(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'large.py').write_text('#' + 'a'*1000)
        report = self.make_manifests(required_files=['large.py'], max_bytes=100)
        self.assertEqual(report['status'], 'within_declared_scope')
        self.assertEqual(report['source_coverage']['status'], 'incomplete_or_unverified')
        self.assertEqual(report['source_coverage']['control']['missing_required_files'], ['large.py'])

    def test_excluded_required_dependency_is_incomplete(self):
        project = self.root / 'project' / 'vendor'
        project.mkdir(parents=True)
        (project / 'core.py').write_text('x=1')
        report = self.make_manifests(required_files=['vendor/core.py'], exclude_dirs=['vendor'])
        self.assertEqual(report['source_coverage']['status'], 'incomplete_or_unverified')

    def test_scoped_freeze_and_outside_required_path(self):
        report = self.make_manifests(required_files=['small.py'])
        self.assertEqual(report['source_coverage']['status'], 'complete_in_declared_scope')
        with self.assertRaises(ValueError):
            self.make_manifests(required_files=['../outside.py'])

    def test_snapshot_cli_emits_draft_but_returns_nonzero_on_gap(self):
        self.make_manifests()
        out = self.root / 'manifest.json'
        proc = subprocess.run([sys.executable, str(ROOT/'scripts/experiment_manifest.py'), 'snapshot', str(self.root/'project'),
                               '--config', str(self.root/'cfg.json'), '--experiment-id', 'E0', '--required-file', 'missing.py', '--out', str(out)], capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(out.read_text())['source_coverage']['status'], 'incomplete')


class FewShotTests(unittest.TestCase):
    def test_valid_counts_and_no_spec_downgrade(self):
        plan = data_plan()
        self.assertEqual(inspect_plan(plan)['few_shot']['status'], 'declared_counts_consistent')
        del plan['few_shot']
        self.assertEqual(inspect_plan(plan)['few_shot']['status'], 'unverified_missing_specification')

    def test_wrong_way_shot_query_and_episode_count(self):
        for key, new_value, kind in [('n_way', 5, 'wrong_n_way'), ('k_shot', 5, 'wrong_samples_per_class'),
                                    ('query_per_class', 8, 'wrong_samples_per_class'), ('episodes_per_seed', 2, 'wrong_episode_count')]:
            with self.subTest(key=key):
                plan = data_plan()
                plan['few_shot']['A-to-B'][key] = new_value
                self.assertIn(kind, {i['kind'] for i in inspect_plan(plan)['issues']})

    def test_support_query_class_mismatch_and_missing_label(self):
        plan = data_plan()
        plan['samples'][1]['class_id'] = 'different'
        self.assertIn('support_query_class_mismatch', {i['kind'] for i in inspect_plan(plan)['issues']})
        del plan['samples'][1]['class_id']
        self.assertIn('missing_class_identity', {i['kind'] for i in inspect_plan(plan)['issues']})

    def test_spec_changes_affect_fingerprint_and_misplaced_fields_rejected(self):
        a, b = data_plan(), data_plan()
        b['few_shot']['A-to-B']['n_way'] = 3
        self.assertIn('few_shot_sha256', compare_plans(a, b)['changed_components'])
        a['n_way'] = 5
        with self.assertRaises(ValueError):
            inspect_plan(a)

    def test_malformed_cardinality(self):
        for bad in (True, 0, -1, 1.5):
            plan = data_plan()
            plan['few_shot']['A-to-B']['k_shot'] = bad
            with self.assertRaises(ValueError):
                inspect_plan(plan)


class ConfigFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.factory = self.root / 'factory.py'
        self.model = self.root / 'model.py'
        # These files would fail if imported. Only their AST may be read.
        self.model.write_text('raise RuntimeError("do not import")\nclass Model:\n def __init__(self, width=64, top_k=1, fast=False): pass\n')

    def run_trace(self, source):
        self.factory.write_text('raise RuntimeError("do not import")\n' + source)
        return trace(self.factory, 'factory', self.model, 'Model', {'width': 32, 'top_k': 0})

    def test_whitelisted_kwargs_comprehension_and_unforwarded_default(self):
        result = self.run_trace('def factory(cfg):\n keys=("width",)\n return Model(**{k: cfg[k] for k in keys}, fast=cfg.get("fast",False))\n')
        rows = {r['parameter']: r for r in result['parameters']}
        self.assertEqual(rows['width']['constructor_input'], 32)
        self.assertEqual(rows['top_k']['constructor_input'], 1)
        self.assertTrue(rows['top_k']['declared_input_mismatch'])
        self.assertEqual(rows['top_k']['origin'], 'constructor_default')
        self.assertFalse(result['runtime_instance_verified'])

    def test_dynamic_unpack_does_not_guess_defaults(self):
        result = self.run_trace('def factory(cfg):\n return Model(**build_kwargs(cfg))\n')
        self.assertTrue(result['unknown_unpack'])
        self.assertTrue(all(r['constructor_input_status'] == 'unknown' for r in result['parameters']))

    def test_branch_or_mutation_before_call_remains_unknown(self):
        for source in ('def factory(cfg):\n cfg.update(other)\n return Model(width=cfg["width"])\n',
                       'def factory(cfg):\n if enabled:\n  return Model(width=cfg["width"])\n'):
            result = self.run_trace(source)
            self.assertTrue(result['uncertain_factory_context'])
            self.assertTrue(all(r['constructor_input_status'] == 'unknown' for r in result['parameters']))

    def test_positional_binding(self):
        rows = self.run_trace('def factory(cfg):\n return Model(cfg["width"],cfg["top_k"])\n')['parameters']
        self.assertEqual([r['constructor_input'] for r in rows], [32, 0, False])

    def test_probe_without_opt_in_does_not_import(self):
        kwargs = self.root / 'kwargs.json'
        kwargs.write_text('{}')
        result = subprocess.run([sys.executable, str(ROOT/'assets/verify_instance.py'), '--factory', 'nonexistent:factory',
                                 '--kwargs', str(kwargs), '--out', str(self.root/'out.json')], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b'ModuleNotFoundError', result.stderr)
        self.assertFalse((self.root/'out.json').exists())

    def test_bad_binding_and_docstring(self):
        bad = self.run_trace('def factory(cfg):\n return Model(unknown=1)\n')
        self.assertIn('unexpected_keyword:unknown', bad['binding_issues'])
        self.assertTrue(all(r['constructor_input_status'] == 'unknown' for r in bad['parameters']))
        good = self.run_trace('def factory(cfg):\n "Build model."\n return Model(width=cfg["width"])\n')
        self.assertFalse(good['uncertain_factory_context'])


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.metric = {'direction': 'higher', 'unit': 'fraction', 'min_improvement': .01}

    def test_reproducible_interval_and_direction_symmetry(self):
        deltas = [.02, .04, .03, .025, .035]
        a = assess(deltas, self.metric, statistics_plan(), True)
        b = assess(deltas, self.metric, statistics_plan(), True)
        c = assess([-d for d in deltas], {**self.metric, 'direction': 'lower'}, statistics_plan(), True)
        self.assertEqual(a, b)
        self.assertEqual(a['ci'], c['ci'])
        self.assertEqual(a['decision'], 'threshold_supported_exploratory')
        self.assertLess(a['ci']['low'], .03)
        self.assertGreater(a['ci']['high'], .03)

    def test_uncertainty_overlap_is_inconclusive(self):
        result = assess([-.2, .2, 0, -.1, .1], self.metric, statistics_plan(), True)
        self.assertEqual(result['decision'], 'inconclusive')
        self.assertLess(result['ci']['low'], 0)
        self.assertGreater(result['ci']['high'], 0)

    def test_threshold_not_reached(self):
        result = assess([-.01, -.03, -.02, -.025, -.015], self.metric, statistics_plan(), True)
        self.assertEqual(result['decision'], 'below_predeclared_threshold')

    def test_missing_small_degenerate_and_confounded_stay_unassessed(self):
        cases = [([.1]*5, None, True, 'not_predeclared'), ([.1,.2], statistics_plan(), True, 'insufficient_independent_pairs'),
                 ([.1]*5, statistics_plan(), True, 'degenerate_observed_differences'),
                 ([.1,.2,.3,.4,.5], statistics_plan(), False, 'blocked_incomplete_or_confounded')]
        for deltas, spec, allowed, status in cases:
            result = assess(deltas, self.metric, spec, allowed)
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['ci'])
            self.assertEqual(result['decision'], 'not_assessed')

    def test_independent_unit_and_required_threshold(self):
        spec = statistics_plan()
        spec['independent_unit'] = 'query'
        self.assertTrue(validate_statistics(spec))
        cfg = config()
        cfg['evaluation']['statistics'] = statistics_plan()
        self.assertIn('/evaluation/metrics/0/min_improvement', validate_config(cfg)['missing'])
        cfg['evaluation']['metrics'][0]['min_improvement'] = -1
        self.assertTrue(validate_config(cfg)['invalid'])

    def test_quantile_linear_interpolation(self):
        self.assertEqual(quantile([0, 10, 20], .25), 5)

    def test_basic_interval_matches_known_binomial_bootstrap_quantiles(self):
        # Five observations with one 1: bootstrap means have Binomial(5,.2)/5 distribution.
        # The exact .025/.975 quantiles are 0 and .6, so the basic CI is [-.2,.4].
        spec = {**statistics_plan(), 'resamples': 10000}
        result = assess([0,0,0,0,1], self.metric, spec, True)
        self.assertAlmostEqual(result['ci']['low'], -.2)
        self.assertAlmostEqual(result['ci']['high'], .4)

    def test_legacy_scope_and_mismatched_statistics_block_result_decisions(self):
        helper = test_protocol_coverage.CoverageTests(methodName='test_complete_evaluation_and_data_plan')
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        for metric in helper.cfg['evaluation']['metrics']:
            metric['min_improvement'] = .01
        helper.cfg['evaluation']['statistics'] = statistics_plan()
        helper.freeze()
        del helper.a['source_scope']
        helper.check = audit(helper.a, helper.b, 'adapter', ['/model/adapter'], [])
        report = helper.result(helper.rows())
        self.assertEqual(report['groups'][0]['statistics']['status'], 'blocked_incomplete_or_confounded')
        helper.freeze()
        helper.b['config']['evaluation']['statistics']['random_seed'] = 123
        helper.check = audit(helper.a, helper.b, 'adapter', ['/model/adapter', '/evaluation/statistics/random_seed'], [])
        report = helper.result(helper.rows())
        self.assertEqual(report['groups'][0]['statistics']['status'], 'blocked_incomplete_or_confounded')

    def test_result_import_carries_statistics_and_blocks_source_gaps(self):
        helper = test_protocol_coverage.CoverageTests(methodName='test_complete_evaluation_and_data_plan')
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.cfg['training']['seeds'] = [1,2,3,4,5]
        helper.cfg['evaluation']['statistics'] = statistics_plan()
        for metric in helper.cfg['evaluation']['metrics']:
            metric['min_improvement'] = .01
        helper.plan['episodes'] = [{**helper.plan['episodes'][0], 'task': task, 'seed': seed}
                                    for task in helper.cfg['evaluation']['tasks'] for seed in range(1,6)]
        helper.freeze()
        rows = []
        for exp in (helper.a, helper.b):
            for task in helper.cfg['evaluation']['tasks']:
                for metric in helper.cfg['evaluation']['metrics']:
                    for seed in range(1,6):
                        rows.append({'experiment_id': exp['experiment_id'], 'seed': seed, 'task': task, 'metric': metric['name'],
                                     'unit': metric['unit'], 'value': .6 + (.02+seed*.005 if exp is helper.b else 0), 'manifest_sha256': exp['manifest_sha256']})
        report = helper.result(rows)
        self.assertEqual(report['groups'][0]['decision'], 'threshold_supported_exploratory')
        helper.a['skipped'].append({'path': 'large.py', 'reason': 'size_limit'})
        helper.check = audit(helper.a, helper.b, 'adapter', ['/model/adapter'], [])
        report = helper.result(rows)
        self.assertEqual(report['interpretation_status'], 'incomplete_or_confounded')
        self.assertEqual(report['groups'][0]['statistics']['status'], 'blocked_incomplete_or_confounded')


if __name__ == '__main__':
    unittest.main()
