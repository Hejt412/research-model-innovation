"""Synthetic numeric records and inert adapters only; never a tensor/model."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_structure_probe import probe, spec, observation, SCRIPT


def v2():
    plan, data = spec(), observation()
    plan['schema_version'] = 2
    data['cases'][0]['setup'] = deepcopy(data['setup'])
    plan['context'] = {'baseline': {'experiment_id': 'E0', 'manifest_sha256': '0'*64},
                       'experiment': {'experiment_id': 'E1', 'manifest_sha256': '1'*64}}
    return plan, data


def relation(plan, *, kind='close', left_case='a', right_case='b', left_indices=None, right_indices=None):
    left = {'case': left_case, 'variant': 'enabled', 'output': 'logits'}
    right = {'case': right_case, 'variant': 'enabled', 'output': 'logits'}
    if left_indices is not None:
        left['indices'] = left_indices
    if right_indices is not None:
        right['indices'] = right_indices
    plan['relations'] = [{'id': 'r', 'intent': 'Synthetic declared relation', 'kind': kind,
                          'left': left, 'right': right, 'comparison': {'atol': 0, 'rtol': 0}}]


def two_cases():
    plan, data = v2()
    plan['cases'].append({**deepcopy(plan['cases'][0]), 'id': 'b'})
    data['cases'].append({**deepcopy(data['cases'][0]), 'id': 'b'})
    return plan, data


class RecheckTests(unittest.TestCase):
    def test_nonstring_nested_keys_cannot_create_unstable_archive(self):
        for metadata in ({2: 0, 10: 0}, {'nested': {1: 0, '1': 1}}):
            data = observation()
            data['metadata'] = metadata
            report = probe.check_outputs(spec(), data)
            self.assertEqual(report['status'], 'failed_or_unconfirmed')
            self.assertNotIn('observation', report)
            json.dumps(report, allow_nan=False)
            with self.assertRaises(ValueError):
                probe.canonical(metadata)

    def test_valid_string_keys_roundtrip_with_stable_digest(self):
        data = observation()
        data['metadata'] = {'2': 0, '10': 0, 'nested': [{'unicode': '中文'}]}
        report = probe.check_outputs(spec(), data)
        restored = json.loads(json.dumps(report, ensure_ascii=False))
        self.assertEqual(probe.digest(restored['observation']), report['observation_sha256'])

    def test_circular_metadata_is_rejected_without_recursion_crash(self):
        data = {}
        data['self'] = data
        with self.assertRaises(ValueError):
            probe.canonical(data)
        self.assertEqual(probe.safe_metadata(data)['status'], 'unavailable_non_json_or_nonfinite_data')

    def test_json_underflow_rejected_and_representable_or_literal_zero_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'numbers.json'
            for number in ('1e-400', '-1.25e-400', '0.0001e-9999'):
                source.write_text(number, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'underflows'):
                    probe.load_json(source)
            for number, expected in (('0e-400', 0), ('-0.000e-99999', 0), ('5e-324', 5e-324)):
                source.write_text(number, encoding='utf-8')
                self.assertEqual(probe.load_json(source), expected)

    def test_underflow_spec_rejected_before_adapter_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'spec.json').write_text(json.dumps(spec()).replace('"atol": 0', '"atol": 1e-400'), encoding='utf-8')
            (root/'adapter.py').write_text('from pathlib import Path\nPath("imported").touch()\ndef collect(spec): return {}\n')
            result = self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'underflows', result.stderr)
            self.assertFalse((root/'imported').exists())

    def hardlink(self, source, target):
        try:
            os.link(source, target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Hardlink unavailable: ' + str(exc))

    def test_hardlink_output_cannot_overwrite_offline_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            original = (root/'raw.json').read_bytes()
            self.hardlink(root/'raw.json', root/'out.json')
            result = self.cli(root, '--observation', str(root/'raw.json'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'must not overwrite', result.stderr)
            self.assertEqual((root/'raw.json').read_bytes(), original)

    def test_hardlink_output_cannot_overwrite_source_before_import(self):
        for protected_name in ('adapter.py', 'declared.py'):
            with self.subTest(protected_name=protected_name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.files(root)
                (root/'adapter.py').write_text('from pathlib import Path\nPath("imported").touch()\ndef collect(spec): return {}\n')
                (root/'declared.py').write_text('# inert declared source\n')
                original = (root/protected_name).read_bytes()
                self.hardlink(root/protected_name, root/'out.json')
                result = self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe',
                                  '--source-file', str(root/'declared.py'))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'must not overwrite', result.stderr)
                self.assertFalse((root/'imported').exists())
                self.assertEqual((root/protected_name).read_bytes(), original)

    def test_overflow_cannot_turn_mismatch_into_pass(self):
        plan, data = spec(), observation()
        plan['comparison'] = {'atol': 0, 'rtol': 1.9}
        data['cases'][0]['baseline']['logits']['values'] = [1e308, 1]
        data['cases'][0]['disabled']['logits']['values'] = [-1e308, 1]
        report = probe.check_outputs(plan, data)
        self.assertEqual(report['status'], 'failed_or_unconfirmed')
        diag = report['cases'][0]['checks'][-1]['diagnostics']
        self.assertEqual(diag['failure_count'], 1)
        self.assertEqual(diag['first_failure_coordinate'], [0, 0])
        self.assertIsInstance(diag['max_abs_error'], str)
        json.dumps(report, allow_nan=False)

    def test_large_tolerance_can_mathematically_allow_large_difference(self):
        self.assertTrue(probe.compare_values([1e308], [-1e308], {'atol': 0, 'rtol': 2})['within_tolerance'])

    def test_tiny_nonzero_error_kept_in_diagnostics(self):
        diag = probe.compare_values([0], [5e-324], {'atol': 0, 'rtol': 0})
        self.assertFalse(diag['within_tolerance'])
        self.assertEqual(diag['zero_baseline_nonzero_difference_count'], 1)
        self.assertNotEqual(diag['max_abs_error'], 0)

    def test_diagnostics_locate_all_failures_and_worst_coordinate(self):
        diag = probe.compare_values([0, 1, 2, 3], [0.1, 1, 5, 2], {'atol': 0, 'rtol': 0}, [2, 2])
        self.assertEqual(diag['failure_count'], 3)
        self.assertEqual(diag['failed_indices_sample'], [0, 2, 3])
        self.assertEqual(diag['worst_coordinate'], [1, 0])
        self.assertEqual(diag['max_abs_error'], 3)

    def test_diagnostics_do_not_silently_zip_different_lengths(self):
        for a, b in (([], []), ([1], [1, 2])):
            with self.assertRaises(ValueError):
                probe.compare_values(a, b, {'atol': 0, 'rtol': 0})

    def test_archive_preserves_actual_outputs_and_digest(self):
        data = observation()
        report = probe.check_outputs(spec(), data)
        self.assertEqual(report['observation'], data)
        self.assertEqual(report['observation_sha256'], probe.digest(data))
        data['cases'][0]['enabled']['logits']['values'][0] = 99
        self.assertNotEqual(report['observation'], data)

    def test_invalid_nonfinite_observation_still_produces_strict_diagnostics(self):
        data = observation()
        data['setup']['eval_mode'] = float('nan')
        data['cases'][0]['enabled']['logits']['values'][0] = float('inf')
        report = probe.check_outputs(spec(), data)
        self.assertEqual(report['status'], 'failed_or_unconfirmed')
        self.assertNotIn('observation', report)
        json.dumps(report, allow_nan=False)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root, data=data)
            result = self.online(root)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(probe.load_json(root/'out.json')['observation_archive_status'],
                             'unavailable_non_json_or_nonfinite_data')

    def test_v1_compatibility_and_v2_case_setup(self):
        self.assertEqual(probe.check_outputs(spec(), observation())['status'], 'passed_sampled_checks')
        plan, data = v2()
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
        del data['cases'][0]['setup']
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_context_links_are_validated_but_not_authenticated(self):
        plan, data = v2()
        report = probe.check_outputs(plan, data)
        self.assertEqual(report['context_declarations'], plan['context'])
        self.assertFalse(report['context_verified'])
        plan['context']['experiment']['experiment_id'] = 'E0'
        with self.assertRaises(ValueError):
            probe.validate_spec(plan)

    def test_v1_cannot_silently_ignore_new_checks(self):
        plan = spec()
        plan['relations'] = []
        with self.assertRaises(ValueError):
            probe.validate_spec(plan)

    def test_undeclared_mechanism_is_not_reported_verified(self):
        plan, data = v2()
        report = probe.check_outputs(plan, data)
        self.assertEqual(report['mechanism_check_status'], 'not_declared')
        self.assertFalse(report['mechanism_causality_verified'])

    def test_execution_count_accepts_legal_zero_initialization(self):
        plan, data = v2()
        plan['mechanism_checks'] = [{'id': 'm', 'intent': 'Branch executes even with zero initialized gate',
                                    'case': 'a', 'observable': 'branch', 'kind': 'executed', 'min_calls': 1}]
        data['cases'][0]['enabled'] = deepcopy(data['cases'][0]['baseline'])
        data['cases'][0]['observables'] = {'branch': {'calls': 1}}
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
        for count in (0, True, -1):
            data['cases'][0]['observables']['branch']['calls'] = count
            self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_range_and_controlled_nonzero_checks(self):
        plan, data = v2()
        plan['mechanism_checks'] = [
            {'id': 'range', 'intent': 'Gate range', 'case': 'a', 'observable': 'gate',
             'kind': 'range', 'shape': [2], 'min': 0, 'max': 1},
            {'id': 'nonzero', 'intent': 'Controlled nonzero gate case, not initialization',
             'case': 'a', 'observable': 'gate', 'kind': 'nonzero', 'shape': [2], 'atol': 0.01}]
        data['cases'][0]['observables'] = {'gate': {'shape': [2], 'values': [0, 0.5]}}
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
        for values in ([0, 0], [0, 2], [0, float('nan')]):
            data['cases'][0]['observables']['gate']['values'] = values
            self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_missing_mechanism_observable_blocks_declared_check(self):
        plan, data = v2()
        plan['mechanism_checks'] = [{'id': 'm', 'intent': 'Branch', 'case': 'a',
                                    'observable': 'branch', 'kind': 'executed', 'min_calls': 1}]
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_batch_permutation_relation_uses_declared_mapping(self):
        plan, data = two_cases()
        relation(plan, right_indices=[1, 0])
        data['cases'][1]['enabled']['logits']['values'] = [7, 5]
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
        data['cases'][1]['enabled']['logits']['values'] = [7, 9]
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_causal_prefix_check_ignores_only_declared_future_positions(self):
        plan, data = two_cases()
        relation(plan, left_indices=[0], right_indices=[0])
        data['cases'][1]['enabled']['logits']['values'] = [5, 99]
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
        data['cases'][1]['enabled']['logits']['values'][0] = 6
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_reset_and_chunk_relations_detect_declared_mismatch(self):
        for intent in ('Fresh versus reset state', 'Full versus stitched chunk output'):
            plan, data = two_cases()
            relation(plan)
            plan['relations'][0]['intent'] = intent
            self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')
            data['cases'][1]['enabled']['logits']['values'][1] += 1
            self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_different_relation_requires_a_real_difference(self):
        plan, data = two_cases()
        relation(plan, kind='different')
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')
        data['cases'][1]['enabled']['logits']['values'][0] += 1
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'passed_sampled_checks')

    def test_relation_does_not_pass_with_invalid_or_missing_output(self):
        plan, data = two_cases()
        relation(plan)
        del data['cases'][1]['enabled']['logits']
        self.assertEqual(probe.check_outputs(plan, data)['status'], 'failed_or_unconfirmed')

    def test_bad_selectors_and_unmatched_lengths_rejected(self):
        for indices in ([], [2], [True], [0, 0], None):
            plan, _ = two_cases()
            relation(plan, left_indices=indices)
            if indices is None:
                plan['relations'][0]['left']['indices'] = None
            with self.assertRaises(ValueError):
                probe.validate_spec(plan)
        plan, _ = two_cases()
        relation(plan, left_indices=[0])
        with self.assertRaises(ValueError):
            probe.validate_spec(plan)

    def test_invalid_mechanism_rules_rejected(self):
        for update in ({'kind': 'unknown'}, {'min_calls': True}, {'min_calls': 0}, {'case': 'missing'}, {'intent': ''}):
            plan, _ = v2()
            plan['mechanism_checks'] = [{**{'id': 'm', 'intent': 'Branch', 'case': 'a',
                'observable': 'branch', 'kind': 'executed', 'min_calls': 1}, **update}]
            with self.assertRaises(ValueError):
                probe.validate_spec(plan)

    def test_future_schema_rejected(self):
        plan = spec()
        plan['schema_version'] = 3
        with self.assertRaises(ValueError):
            probe.validate_spec(plan)

    def cli(self, root, *arguments):
        env = dict(os.environ)
        env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
        return subprocess.run([sys.executable, str(SCRIPT), '--spec', str(root/'spec.json'),
            '--out', str(root/'out.json'), *arguments], cwd=root, env=env, capture_output=True)

    def files(self, root, plan=None, data=None):
        (root/'spec.json').write_text(json.dumps(plan or spec()), encoding='utf-8')
        (root/'raw.json').write_text(json.dumps(data or observation()), encoding='utf-8')

    def online(self, root):
        (root/'adapter.py').write_text('import json\nfrom pathlib import Path\ndef collect(spec):\n return json.loads(Path("raw.json").read_text())\n')
        return self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe')

    def test_offline_raw_mode_does_not_import_available_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'adapter.py').write_text('raise RuntimeError("Must never import")\n')
            result = self.cli(root, '--observation', 'raw.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root/'out.json').read_text())
            self.assertEqual(report['execution_mode'], 'offline_recheck')
            self.assertEqual(report['source_consistency']['status'], 'not_assessed_offline')

    def test_online_archive_offline_recheck_and_second_recheck(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            self.assertEqual(self.online(root).returncode, 0)
            (root/'archive.json').write_bytes((root/'out.json').read_bytes())
            # A crashing adapter is irrelevant to offline checking.
            (root/'adapter.py').write_text('raise RuntimeError("No offline import")\n')
            for _ in range(2):
                result = self.cli(root, '--observation', 'archive.json')
                self.assertEqual(result.returncode, 0, result.stderr)
                (root/'archive.json').write_bytes((root/'out.json').read_bytes())

    def test_raw_offline_archive_can_be_rechecked_without_execution_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            self.assertEqual(self.cli(root, '--observation', 'raw.json').returncode, 0)
            (root/'archive.json').write_bytes((root/'out.json').read_bytes())
            self.assertEqual(self.cli(root, '--observation', 'archive.json').returncode, 0)

    def test_tampered_archive_digest_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            self.assertEqual(self.online(root).returncode, 0)
            report = json.loads((root/'out.json').read_text())
            report['observation']['cases'][0]['enabled']['logits']['values'][0] = 99
            (root/'archive.json').write_text(json.dumps(report))
            self.assertNotEqual(self.cli(root, '--observation', 'archive.json').returncode, 0)

    def test_changed_spec_cannot_launder_a_retroactive_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            self.assertEqual(self.online(root).returncode, 0)
            (root/'archive.json').write_bytes((root/'out.json').read_bytes())
            plan = spec()
            plan['comparison']['atol'] = 999
            (root/'spec.json').write_text(json.dumps(plan))
            for _ in range(2):
                self.assertEqual(self.cli(root, '--observation', 'archive.json').returncode, 2)
                report = json.loads((root/'out.json').read_text())
                self.assertTrue(report['provenance_issues'])
                (root/'archive.json').write_bytes((root/'out.json').read_bytes())

    def test_source_mutation_during_collect_blocks_pass_and_offline_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'adapter.py').write_text('import json\nfrom pathlib import Path\ndef collect(spec):\n'
                ' p=Path(__file__)\n p.write_text(p.read_text()+"\\n# changed")\n'
                ' return json.loads(Path("raw.json").read_text())\n')
            result = self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe')
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads((root/'out.json').read_text())
            self.assertEqual(report['source_consistency']['status'], 'changed_or_unconfirmed')
            (root/'archive.json').write_bytes((root/'out.json').read_bytes())
            self.assertEqual(self.cli(root, '--observation', 'archive.json').returncode, 2)

    def test_unreadable_declared_source_is_unconfirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'adapter.py').write_text('import json\nfrom pathlib import Path\ndef collect(spec):\n return json.loads(Path("raw.json").read_text())\n')
            result = self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe', '--source-file', 'missing.py')
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_snapshot_inconsistency_not_hidden_by_status_label(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            self.assertEqual(self.online(root).returncode, 0)
            report = json.loads((root/'out.json').read_text())
            first = next(iter(report['source_after']))
            report['source_after'][first]['sha256'] = 'f'*64
            (root/'archive.json').write_text(json.dumps(report))
            self.assertEqual(self.cli(root, '--observation', 'archive.json').returncode, 2)

    def test_offline_mode_rejects_execution_flags_and_inputs_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            for extra in (('--execute-reviewed-probe',), ('--source-file', 'adapter.py'), ('--adapter', 'adapter:collect')):
                self.assertNotEqual(self.cli(root, '--observation', 'raw.json', *extra).returncode, 0)
            original = (root/'raw.json').read_bytes()
            self.assertNotEqual(self.cli(root, '--observation', 'raw.json', '--out', 'raw.json').returncode, 0)
            self.assertEqual((root/'raw.json').read_bytes(), original)

    def test_output_cannot_overwrite_adapter_before_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'adapter.py').write_text('from pathlib import Path\nPath("IMPORTED").touch()\n')
            result = self.cli(root, '--adapter', 'adapter:collect', '--execute-reviewed-probe', '--out', 'adapter.py')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root/'IMPORTED').exists())

    def test_dotted_adapter_source_resolution_does_not_import_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            package = root/'pkg'
            package.mkdir()
            (package/'__init__.py').write_text('from pathlib import Path\nPath("IMPORTED").touch()\n')
            (package/'adapter.py').write_text('import json\nfrom pathlib import Path\ndef collect(spec):\n return json.loads(Path("raw.json").read_text())\n')
            result = self.cli(root, '--adapter', 'pkg.adapter:collect', '--execute-reviewed-probe', '--out', str(package/'adapter.py'))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root/'IMPORTED').exists())

    def test_old_summary_only_archive_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.files(root)
            (root/'legacy.json').write_text(json.dumps({'kind': 'user_run_structure_observation', 'schema_version': 1}))
            self.assertNotEqual(self.cli(root, '--observation', 'legacy.json').returncode, 0)


if __name__ == '__main__':
    unittest.main()
