from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from behavior_records import (case_snapshot, check_current, fingerprint, read_json,
                              register, rerun_plan, snapshot, validate_case_snapshot,
                              validate_index, validate_record, validate_snapshot, write_new)


class BehaviorRecordTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'中文输入'
        self.root.mkdir()
        (self.root/'SKILL.md').write_bytes(b'# skill\r\nRead sources.\r\n')
        (self.root/'rules.md').write_bytes(b'Only synthetic behavior is reviewed.\n')
        (self.root/'request.md').write_bytes(b'Analyze this fixture without executing it.\n')
        (self.root/'fixture.py').write_bytes(b'raise RuntimeError("must never import project")\r\nx = 1\r\n')
        (self.root/'second.md').write_bytes(b'A separate request.\n')
        self.report = Path(tmp.name)/'private-project-report.md'
        self.report.write_bytes(b'# Actual independent report\r\nEvidence and action.\r\n')
        self.index = {'kind': 'behavior_case_index', 'schema_version': 1,
                      'shared_source_paths': ['SKILL.md'], 'cases': [
                          {'case_id': '01', 'rule_tags': ['structure', 'source-scope'],
                           'request_path': 'request.md', 'fixture_paths': ['fixture.py'], 'source_paths': ['rules.md']},
                          {'case_id': '02', 'rule_tags': ['budget'],
                           'request_path': 'second.md', 'fixture_paths': [], 'source_paths': []}]}
        self.frozen = case_snapshot(self.index, '01', self.root)
        self.record = self.review()

    def review(self, **kwargs):
        return register(self.frozen, self.report, 'review-01', 'maintainer', 'passed', 'confirmed',
                        reviewed_at='2026-09-30T01:02:03Z', **kwargs)

    def reseal(self, value, field):
        value[field] = fingerprint({k: v for k, v in value.items() if k != field})
        return value

    def test_explicit_file_order_and_lf_normalization_are_stable(self):
        first = snapshot(self.root, ['fixture.py', 'SKILL.md'])
        (self.root/'fixture.py').write_bytes((self.root/'fixture.py').read_bytes().replace(b'\r\n', b'\n'))
        second = snapshot(self.root, ['SKILL.md', 'fixture.py'])
        self.assertEqual(first, second)
        self.assertEqual(first['files'][0]['sha256'], hashlib.sha256(b'# skill\nRead sources.\n').hexdigest())
        # An unlisted file has no influence; no implicit repository scan occurs.
        (self.root/'unlisted.py').write_text('raise RuntimeError("never execute")\n')
        self.assertEqual(second, snapshot(self.root, ['fixture.py', 'SKILL.md']))

    def test_set_digest_binds_path_and_file_membership(self):
        before = snapshot(self.root, ['rules.md'])
        (self.root/'copy.md').write_bytes((self.root/'rules.md').read_bytes())
        after = snapshot(self.root, ['copy.md'])
        self.assertEqual(before['files'][0]['sha256'], after['files'][0]['sha256'])
        self.assertNotEqual(before['files_sha256'], after['files_sha256'])
        self.assertNotEqual(after['files_sha256'], snapshot(self.root, ['copy.md', 'rules.md'])['files_sha256'])

    def test_raw_report_bytes_are_hashed_without_lf_normalization(self):
        self.assertEqual(self.record['report']['sha256'], hashlib.sha256(self.report.read_bytes()).hexdigest())
        self.assertEqual(self.record['report']['bytes'], len(self.report.read_bytes()))
        self.assertNotIn(str(self.report), json.dumps(self.record))
        self.assertNotIn(self.report.name, json.dumps(self.record))
        self.report.write_bytes(self.report.read_bytes().replace(b'\r\n', b'\n'))
        result = check_current(self.index, self.root, self.record, self.report)
        self.assertTrue(result['inputs_match'])
        self.assertFalse(result['current_pass'])
        self.assertIn('report_bytes_drift', result['reasons'])

    def test_current_pass_requires_original_report_and_confirmed_source(self):
        passed = check_current(self.index, self.root, self.record, self.report)
        self.assertTrue(passed['current_pass'])
        self.assertFalse(passed['research_conclusions_certified'])
        absent = check_current(self.index, self.root, self.record)
        self.assertFalse(absent['current_pass'])
        self.assertIn('report_unavailable', absent['reasons'])
        for source_match in ('unknown', 'mismatch'):
            altered = deepcopy(self.record)
            altered['review']['source_match'] = source_match
            self.reseal(altered, 'record_sha256')
            self.assertFalse(check_current(self.index, self.root, altered, self.report)['current_pass'])
        self.report.unlink()
        self.assertFalse(check_current(self.index, self.root, self.record, self.report)['current_pass'])

    def test_manual_failed_and_needs_review_remain_not_passed(self):
        for verdict in ('failed', 'needs_review'):
            record = deepcopy(self.record)
            record['review']['verdict'] = verdict
            self.reseal(record, 'record_sha256')
            self.assertIn('review_not_passed', check_current(self.index, self.root, record, self.report)['reasons'])

    def test_source_fixture_and_request_drift_are_separate(self):
        for name, reason in [('SKILL.md', 'source_drift'), ('fixture.py', 'request_or_fixture_drift'),
                             ('request.md', 'request_or_fixture_drift')]:
            with self.subTest(name=name):
                path = self.root/name
                original = path.read_bytes()
                path.write_bytes(original+b'changed\n')
                result = check_current(self.index, self.root, self.record, self.report)
                self.assertFalse(result['current_pass'])
                self.assertIn(reason, result['reasons'])
                path.write_bytes(original)

    def test_deleted_input_or_changed_case_scope_cannot_pass(self):
        altered = deepcopy(self.index)
        altered['cases'][0]['rule_tags'].append('budget')
        result = check_current(altered, self.root, self.record, self.report)
        self.assertIn('case_definition_drift', result['reasons'])
        (self.root/'fixture.py').unlink()
        result = check_current(self.index, self.root, self.record, self.report)
        self.assertIn('input_unavailable', result['reasons'])
        self.assertFalse(result['current_pass'])

    def test_commit_metadata_never_substitutes_for_input_matching(self):
        clean = self.review(tested_commit='a'*40)
        dirty = self.review(base_commit='b'*40, dirty=True)
        self.assertEqual(clean['historical_revision']['type'], 'tested_commit')
        self.assertTrue(dirty['historical_revision']['dirty'])
        (self.root/'SKILL.md').write_bytes(b'changed while same commit metadata remains\n')
        for record in (clean, dirty):
            self.assertFalse(check_current(self.index, self.root, record, self.report)['current_pass'])

    def test_revision_parameters_require_explicit_consistent_values(self):
        invalid = [{'tested_commit': 'abc'}, {'base_commit': 'a'*40}, {'dirty': True},
                   {'base_commit': 'a'*40, 'dirty': 1},
                   {'tested_commit': 'a'*40, 'base_commit': 'b'*40, 'dirty': True},
                   {'tested_commit': 'a'*40, 'dirty': False}]
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.review(**params)

    def test_registration_requires_nonempty_actual_report(self):
        self.report.write_bytes(b'')
        with self.assertRaises(ValueError):
            self.review()
        self.report.unlink()
        with self.assertRaises(OSError):
            self.review()

    def test_future_formats_and_private_extra_fields_are_rejected(self):
        for value, validator in [(self.index, validate_index), (self.frozen, validate_case_snapshot),
                                 (self.record, validate_record), (self.frozen['source_snapshot'], validate_snapshot)]:
            with self.subTest(kind=value['kind']):
                altered = deepcopy(value)
                altered['schema_version'] = 2
                with self.assertRaises(ValueError):
                    validator(altered)
                altered = deepcopy(value)
                altered['report_path'] = str(self.report)
                with self.assertRaises(ValueError):
                    validator(altered)
        altered = deepcopy(self.record)
        del altered['report']['sha256']
        self.reseal(altered, 'record_sha256')
        with self.assertRaises(ValueError):
            check_current(self.index, self.root, altered, self.report)

    def test_tampered_or_internally_inconsistent_records_are_rejected(self):
        altered = deepcopy(self.record)
        altered['review']['verdict'] = 'failed'
        with self.assertRaises(ValueError):
            validate_record(altered)
        altered = deepcopy(self.record)
        altered['case_id'] = '02'
        self.reseal(altered, 'record_sha256')
        with self.assertRaises(ValueError):
            validate_record(altered)
        altered = deepcopy(self.record)
        altered['frozen_snapshot']['source_snapshot']['files'][0]['sha256'] = 'c'*64
        self.reseal(altered['frozen_snapshot'], 'snapshot_sha256')
        self.reseal(altered, 'record_sha256')
        with self.assertRaises(ValueError):
            validate_record(altered)

    def test_invalid_review_and_digest_parameters_are_rejected(self):
        for field, bad in [('reviewer', '../private'), ('reviewed_at', '2026-02-30T01:02:03Z'),
                           ('reviewed_at', '2026-9-30T01:02:03Z'), ('verdict', 'green'),
                           ('source_match', 'trusted'), ('scope', 'research_certified')]:
            altered = deepcopy(self.record)
            altered['review'][field] = bad
            self.reseal(altered, 'record_sha256')
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                validate_record(altered)
        for field, bad in [('bytes', True), ('bytes', 0), ('sha256', 'xyz')]:
            altered = deepcopy(self.record)
            altered['report'][field] = bad
            self.reseal(altered, 'record_sha256')
            with self.assertRaises(ValueError):
                validate_record(altered)

    def test_path_boundary_and_cross_platform_ambiguity_are_rejected(self):
        for value in ('../report.md', '/absolute.md', 'C:/private.md', 'C:private.md',
                      'folder\\file.py', './SKILL.md', 'folder//file.py', 'SKILL.md/'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot(self.root, [value])
        for values in ([], ['SKILL.md', 'SKILL.md'], ['SKILL.md', 'skill.md']):
            with self.assertRaises(ValueError):
                snapshot(self.root, values)
        with self.assertRaises(ValueError):
            snapshot(self.root, ['.'])

    def test_windows_noncanonical_components_are_rejected_on_every_platform(self):
        for relative in ('SKILL.md.', 'SKILL.md ', 'SKILL.md. ', 'folder./request.md',
                         'folder /request.md', 'CON.txt', 'dir/NUL', 'file?.md', 'file*.md'):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    snapshot(self.root, [relative])
                altered = deepcopy(self.index)
                altered['cases'][0]['request_path'] = relative
                with self.assertRaises(ValueError):
                    validate_index(altered)
                # Self-consistent hashes cannot legitimize an alias spelling.
                frozen = deepcopy(self.frozen)
                frozen['input_snapshot']['files'][1]['path'] = relative
                frozen['input_snapshot']['files'].sort(key=lambda e: e['path'])
                frozen['input_snapshot']['files_sha256'] = fingerprint(frozen['input_snapshot']['files'])
                self.reseal(frozen, 'snapshot_sha256')
                with self.assertRaises(ValueError):
                    validate_case_snapshot(frozen)

    def test_casefolded_input_source_overlap_is_rejected_before_filesystem_access(self):
        for relative in ('skill.md', 'Skill.Md', 'SKILL.md'):
            altered = deepcopy(self.index)
            altered['cases'][0]['request_path'] = relative
            if sys.platform == 'win32':
                self.assertTrue((self.root/relative).samefile(self.root/'SKILL.md'))
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                validate_index(altered)
            with self.assertRaises(ValueError):
                case_snapshot(altered, '01', self.root)

    def test_separate_files_with_identical_bytes_are_valid_inputs_and_sources(self):
        request = self.root/'request.md'
        source = self.root/'SKILL.md'
        request.write_bytes(source.read_bytes())
        self.assertFalse(request.samefile(source))
        frozen = case_snapshot(self.index, '01', self.root)
        input_digest = next(e['sha256'] for e in frozen['input_snapshot']['files'] if e['path'] == 'request.md')
        source_digest = next(e['sha256'] for e in frozen['source_snapshot']['files'] if e['path'] == 'SKILL.md')
        self.assertEqual(input_digest, source_digest)
        record = register(frozen, self.report, 'same-content', 'maintainer', 'passed', 'confirmed')
        self.assertTrue(check_current(self.index, self.root, record, self.report)['current_pass'])

    def test_cross_group_hardlink_alias_is_rejected_even_when_hashes_are_unchanged(self):
        request = self.root/'request.md'
        source = self.root/'SKILL.md'
        request.write_bytes(source.read_bytes())
        frozen = case_snapshot(self.index, '01', self.root)
        record = register(frozen, self.report, 'before-hardlink', 'maintainer', 'passed', 'confirmed')
        request.unlink()
        try:
            request.hardlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit creating a test hard link')
        self.assertTrue(request.samefile(source))
        with self.assertRaises(ValueError):
            case_snapshot(self.index, '01', self.root)
        # Offline validation has no filesystem identity evidence; the current
        # root check must supply it before a historical review can be current.
        validate_record(record)
        result = check_current(self.index, self.root, record, self.report)
        self.assertFalse(result['current_pass'])
        self.assertIn('input_unavailable', result['reasons'])

    def test_internal_cross_group_symlink_alias_is_rejected_if_supported(self):
        alias = self.root/'request-alias.md'
        try:
            alias.symlink_to(self.root/'SKILL.md')
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit creating a test symlink')
        altered = deepcopy(self.index)
        altered['cases'][0]['request_path'] = alias.name
        validate_index(altered)
        self.assertTrue(alias.samefile(self.root/'SKILL.md'))
        with self.assertRaises(ValueError):
            case_snapshot(altered, '01', self.root)

    def test_symlink_escape_is_rejected_if_platform_permits_symlinks(self):
        link = self.root/'external.md'
        try:
            link.symlink_to(self.report)
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit creating a test symlink')
        with self.assertRaises(ValueError):
            snapshot(self.root, ['external.md'])

    def test_exclusive_creation_preserves_existing_history_bytes(self):
        output = self.root/'history'/'review-01.json'
        write_new(self.record, output)
        original = output.read_bytes()
        record = deepcopy(self.record)
        record['record_id'] = 'review-02'
        self.reseal(record, 'record_sha256')
        with self.assertRaises(FileExistsError):
            write_new(record, output)
        self.assertEqual(output.read_bytes(), original)
        write_new(record, output.with_name('review-02.json'))
        self.assertEqual(read_json(output), self.record)

    def test_index_requires_known_unique_cases_tags_and_explicit_files(self):
        for mutate in (lambda v: v['cases'].append(deepcopy(v['cases'][0])),
                       lambda v: v['cases'][0]['rule_tags'].append('structure'),
                       lambda v: v['cases'][0].update(request_path='../request.md'),
                       lambda v: v['cases'][0]['fixture_paths'].append('request.md'),
                       lambda v: v['cases'][0]['source_paths'].append('request.md')):
            altered = deepcopy(self.index)
            mutate(altered)
            with self.assertRaises(ValueError):
                validate_index(altered)
        with self.assertRaises(ValueError):
            case_snapshot(self.index, 'absent', self.root)

    def test_directed_rules_do_not_mark_unrecorded_cases_passed(self):
        plan = rerun_plan(self.index, ['budget'])
        self.assertEqual([c['case_id'] for c in plan['cases']], ['02'])
        self.assertEqual(plan['cases'][0]['rule_hits'], ['budget'])
        self.assertFalse(plan['evaluation_dispatched'])
        self.assertNotIn('passed', json.dumps(plan))
        for tags in ([], ['unknown'], ['budget', 'budget'], ['Budget']):
            with self.assertRaises(ValueError):
                rerun_plan(self.index, tags)

    def test_directed_plan_can_add_recorded_source_or_fixture_drift(self):
        plan = rerun_plan(self.index, ['budget'], self.root, [self.record])
        self.assertEqual([c['case_id'] for c in plan['cases']], ['02'])
        (self.root/'fixture.py').write_bytes(b'changed fixture\n')
        plan = rerun_plan(self.index, ['budget'], self.root, [self.record])
        self.assertEqual([c['case_id'] for c in plan['cases']], ['01', '02'])
        self.assertEqual(plan['cases'][0]['rule_hits'], [])
        self.assertIn('request_or_fixture_drift', plan['cases'][0]['reasons'])
        with self.assertRaises(ValueError):
            rerun_plan(self.index, ['budget'], records=[self.record])

    def test_latest_supplied_history_is_used_without_overwriting_or_resurrection(self):
        (self.root/'rules.md').write_bytes(b'updated rule\n')
        newer = register(case_snapshot(self.index, '01', self.root), self.report,
                         'review-02', 'maintainer', 'failed', 'confirmed', '2026-09-30T01:02:04Z')
        for order in ([newer, self.record], [self.record, newer]):
            plan = rerun_plan(self.index, ['budget'], self.root, order)
            self.assertEqual([c['case_id'] for c in plan['cases']], ['02'])
        self.assertFalse(check_current(self.index, self.root, newer, self.report)['current_pass'])
        with self.assertRaises(ValueError):
            rerun_plan(self.index, ['budget'], self.root, [self.record, self.record])
        newer['review']['reviewed_at'] = self.record['review']['reviewed_at']
        self.reseal(newer, 'record_sha256')
        with self.assertRaises(ValueError):
            rerun_plan(self.index, ['budget'], self.root, [self.record, newer])

    def test_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        path = self.root/'bad.json'
        for raw in ('{"case_id":"01","case_id":"02"}', '{"value":NaN}'):
            path.write_text(raw, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_json(path)

    def test_cli_freeze_register_check_and_rerun_use_only_synthetic_files(self):
        index_path = self.root/'index.json'
        index_path.write_text(json.dumps(self.index), encoding='utf-8')
        frozen_path = self.root/'frozen.json'
        record_path = self.root/'history.json'

        def run(*args):
            return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts'/'behavior_records.py'), *map(str, args)],
                                  capture_output=True, text=True, encoding='utf-8')

        result = run('case-snapshot', '--index', index_path, '--root', self.root,
                     '--case', '01', '--out', frozen_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run('register', '--snapshot', frozen_path, '--report', self.report,
                     '--record-id', 'cli-01', '--reviewer', 'maintainer', '--verdict', 'passed',
                     '--source-match', 'confirmed', '--base-commit', 'a'*40, '--dirty', 'true', '--out', record_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(str(self.report), result.stdout)
        result = run('check', '--index', index_path, '--root', self.root, '--record', record_path, '--report', self.report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['current_pass'])
        result = run('check', '--index', index_path, '--root', self.root, '--record', record_path)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)['current_pass'])
        result = run('rerun', '--index', index_path, '--changed-rule', 'budget')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['case_id'] for c in json.loads(result.stdout)['cases']], ['02'])


if __name__ == '__main__':
    unittest.main()
