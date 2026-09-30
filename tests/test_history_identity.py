"""Relocation/install and evidence-change checks using standard-library fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_innovation_history as fixtures
from _records import fingerprint
from _versions import scripts_digest
from import_results import append_history, history_identity, summarize
from run_fixture import make_ledger, write_csv


class HistoryIdentityTests(unittest.TestCase):
    setUp = fixtures.InnovationHistoryTests.setUp
    write_metadata = fixtures.InnovationHistoryTests.write_metadata
    report = fixtures.InnovationHistoryTests.report
    cli = fixtures.InnovationHistoryTests.cli

    def test_only_documented_producer_locators_are_ignored_in_nested_versions(self):
        first = self.report(self.metadata_path)
        original = deepcopy(first)
        append_history(self.history, first)
        before = self.history.read_bytes()
        second = deepcopy(first)
        stamps = [second['producer'], second['supplied_audit_producer'], second['audit']['producer']]
        stamps.extend(v['producer'] for v in second['audit']['input_versions'].values())
        for stamp in stamps:
            stamp.update(tool_commit=None, working_tree_dirty=False, commit_source='matching_packaged_stamp')
        second['innovation_link']['metadata_path'] = 'D:/moved/innovation.json'
        second['innovation_link']['source_card']['path'] = 'D:/moved/source-card.md'
        self.assertEqual(history_identity(first), history_identity(second))
        self.assertFalse(append_history(self.history, second))
        self.assertEqual(self.history.read_bytes(), before)
        self.assertEqual(first, original)
        second['producer']['unknown_provenance_path'] = 'scientific-source.py'
        self.assertNotEqual(history_identity(first), history_identity(second))

    def test_scripts_and_scientific_evidence_or_identity_changes_append(self):
        first = self.report(self.metadata_path)
        append_history(self.history, first)
        variants = []
        for location in ('summary', 'audit', 'supplied_audit', 'input_control', 'input_experiment'):
            changed = deepcopy(first)
            stamp = {'summary': changed['producer'], 'audit': changed['audit']['producer'],
                     'supplied_audit': changed['supplied_audit_producer'],
                     'input_control': changed['audit']['input_versions']['control']['producer'],
                     'input_experiment': changed['audit']['input_versions']['experiment']['producer']}[location]
            stamp['scripts_sha256'] = '0' * 64
            variants.append((location, changed))
        for field in ('csv_sha256', 'control_sha256', 'experiment_sha256', 'rules_version', 'experiment_id'):
            changed = deepcopy(first)
            changed[field] = 'different-' + field
            variants.append((field, changed))
        changed = deepcopy(first)
        changed['audit']['declared_config_paths'] = ['/model/real_source_path']
        variants.append(('declaration path', changed))
        changed = deepcopy(first)
        changed['audit']['config_changes'][0]['before'] = {'path': 'D:/actual-source/config.json'}
        variants.append(('scientific config path', changed))
        changed = deepcopy(first)
        changed['innovation_link']['metadata']['mechanism_fingerprint']['location'] = 'other/source.py: fusion'
        variants.append(('mechanism source path', changed))
        changed = deepcopy(first)
        changed['groups'][0]['mean_delta'] = -.123
        variants.append(('statistical result', changed))
        for label, report in variants:
            with self.subTest(change=label):
                before = self.history.read_bytes()
                self.assertNotEqual(history_identity(first), history_identity(report))
                self.assertTrue(append_history(self.history, report))
                self.assertTrue(self.history.read_bytes().startswith(before))
                self.assertFalse(append_history(self.history, report))

    def test_moving_identical_relative_evidence_and_relocating_run_artifacts_is_idempotent(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        self.metadata['source_card_path'] = str(self.card.resolve())
        self.write_metadata()
        imported = self.cli(metadata=self.metadata_path, ledger=ledger, history=self.history)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        first = json.loads((self.root / 'summary.json').read_text(encoding='utf-8'))
        relocated_temp = tempfile.TemporaryDirectory()
        self.addCleanup(relocated_temp.cleanup)
        relocated = Path(relocated_temp.name) / 'whole-project'
        shutil.copytree(self.root, relocated)
        relocated_ledger = relocated / 'runs/ledger.json'
        record = json.loads(relocated_ledger.read_text(encoding='utf-8'))
        for run in record['runs']:
            for artifact in run['artifacts'].values():
                artifact['path'] = str(relocated / Path(artifact['path']).relative_to(self.root.resolve()))
        record['producer'].update(tool_commit=None, working_tree_dirty=False, commit_source='unavailable')
        record['record_sha256'] = fingerprint({k: v for k, v in record.items() if k != 'record_sha256'})
        relocated_ledger.write_text(json.dumps(record), encoding='utf-8')
        moved_metadata = relocated / self.metadata_path.relative_to(self.root)
        moved_record = json.loads(moved_metadata.read_text(encoding='utf-8'))
        moved_record['source_card_path'] = str(relocated / self.card.relative_to(self.root))
        moved_metadata.write_text(json.dumps(moved_record, ensure_ascii=False), encoding='utf-8')
        moved_history = relocated / self.history.name
        before = moved_history.read_bytes()
        moved_out = relocated / 'relocated-summary.json'
        command = [sys.executable, '-X', 'utf8', str(fixtures.ROOT / 'scripts/import_results.py'),
                   str(relocated / self.csv.name), '--run-records', str(relocated_ledger),
                   '--innovation-metadata', str(moved_metadata), '--out', str(moved_out),
                   '--history', str(moved_history)]
        for name, path in self.paths.items():
            command.extend(['--' + name, str(relocated / path.relative_to(self.root))])
        imported = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(imported.returncode, 0, imported.stderr)
        second = json.loads(moved_out.read_text(encoding='utf-8'))
        self.assertNotEqual(first['innovation_link']['metadata_path'], second['innovation_link']['metadata_path'])
        self.assertNotEqual(first['innovation_link']['metadata_file_sha256'], second['innovation_link']['metadata_file_sha256'])
        self.assertNotEqual(first['run_provenance']['ledger_file_sha256'], second['run_provenance']['ledger_file_sha256'])
        self.assertEqual(first['groups'], second['groups'])
        self.assertEqual(first['history_identity'], second['history_identity'])
        self.assertFalse(append_history(moved_history, second))
        self.assertEqual(moved_history.read_bytes(), before)

    def test_actual_changed_artifact_content_is_retained_even_with_identical_failure_reason(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        records = json.loads(ledger.read_text(encoding='utf-8'))
        artifact = Path(records['runs'][0]['artifacts']['checkpoint']['path'])
        first = summarize(self.csv, self.control, self.experiment, self.audit, ledger)
        append_history(self.history, first)
        artifact.write_bytes(b'Synthetic changed bytes version one; not weights')
        second = summarize(self.csv, self.control, self.experiment, self.audit, ledger)
        self.assertFalse(second['run_provenance']['statistical_use_allowed'])
        self.assertTrue(append_history(self.history, second))
        artifact.write_bytes(b'Synthetic changed bytes version two; not weights')
        third = summarize(self.csv, self.control, self.experiment, self.audit, ledger)
        self.assertEqual(second['run_provenance']['issues'], third['run_provenance']['issues'])
        self.assertNotEqual(second['history_identity'], third['history_identity'])
        self.assertTrue(append_history(self.history, third))

    def test_missing_artifacts_remain_importable_and_failure_paths_do_not_break_relocation(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        record = json.loads(ledger.read_text(encoding='utf-8'))
        Path(record['runs'][0]['artifacts']['checkpoint']['path']).unlink()
        first = summarize(self.csv, self.control, self.experiment, self.audit, ledger)
        self.assertFalse(first['run_provenance']['statistical_use_allowed'])
        self.assertTrue(append_history(self.history, first))
        moved_temp = tempfile.TemporaryDirectory()
        self.addCleanup(moved_temp.cleanup)
        moved = Path(moved_temp.name) / 'relocated'
        shutil.copytree(self.root, moved)
        for run in record['runs']:
            for artifact in run['artifacts'].values():
                artifact['path'] = str(moved / Path(artifact['path']).relative_to(self.root.resolve()))
        record['record_sha256'] = fingerprint({k: v for k, v in record.items() if k != 'record_sha256'})
        moved_ledger = moved / 'runs/ledger.json'
        moved_ledger.write_text(json.dumps(record), encoding='utf-8')
        second = summarize(moved / self.csv.name, self.control, self.experiment, self.audit, moved_ledger)
        self.assertFalse(second['run_provenance']['statistical_use_allowed'])
        self.assertEqual(first['history_identity'], second['history_identity'])
        self.assertFalse(append_history(moved / self.history.name, second))

    def test_short_relative_artifact_locators_do_not_replace_nonpath_failure_text(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        record = json.loads(ledger.read_text(encoding='utf-8'))
        original = record['runs'][0]['artifacts']['checkpoint']
        reports = []
        for name in ('bytes', 'renamed'):
            (ledger.parent / name).write_bytes(b'Same synthetic changed artifact; not weights')
            original['path'] = name
            record['record_sha256'] = fingerprint({k: v for k, v in record.items() if k != 'record_sha256'})
            ledger.write_text(json.dumps(record), encoding='utf-8')
            out = self.root / ('relative-' + name + '.json')
            command = [sys.executable, '-X', 'utf8', str(fixtures.ROOT / 'scripts/import_results.py'),
                       str(self.csv), '--run-records', ledger.name, '--out', str(out)]
            for role, path in self.paths.items():
                command.extend(['--' + role, str(path)])
            imported = subprocess.run(command, cwd=ledger.parent, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(imported.returncode, 0, imported.stderr)
            reports.append(json.loads(out.read_text(encoding='utf-8')))
        reasons = [r['run_provenance']['history_evidence']['issues'][0]['reason'] for r in reports]
        self.assertEqual(reasons, ['bytes or hash differ', 'bytes or hash differ'])
        self.assertEqual(reports[0]['history_identity'], reports[1]['history_identity'])
        self.assertTrue(append_history(self.history, reports[0]))
        self.assertFalse(append_history(self.history, reports[1]))

    def test_shared_missing_artifact_locators_can_split_without_changing_run_identity(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        record = json.loads(ledger.read_text(encoding='utf-8'))
        first_two = record['runs'][:2]
        reports = []
        for names in (('shared-missing', 'shared-missing'), ('one-missing', 'two-missing')):
            for run, name in zip(first_two, names):
                run['artifacts']['checkpoint']['path'] = name
            record['record_sha256'] = fingerprint({k: v for k, v in record.items() if k != 'record_sha256'})
            ledger.write_text(json.dumps(record), encoding='utf-8')
            out = self.root / ('shared-' + str(len(reports)) + '.json')
            command = [sys.executable, '-X', 'utf8', str(fixtures.ROOT / 'scripts/import_results.py'),
                       str(self.csv), '--run-records', ledger.name, '--out', str(out),
                       '--history', str(self.history)]
            for role, path in self.paths.items():
                command.extend(['--' + role, str(path)])
            before = self.history.read_bytes()
            imported = subprocess.run(command, cwd=ledger.parent, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(imported.returncode, 0, imported.stderr)
            reports.append(json.loads(out.read_text(encoding='utf-8')))
            self.assertFalse(reports[-1]['run_provenance']['statistical_use_allowed'])
            if len(reports) == 2:
                self.assertEqual(self.history.read_bytes(), before)
        self.assertNotEqual(reports[0]['run_provenance']['issues'], reports[1]['run_provenance']['issues'])
        self.assertEqual(reports[0]['run_provenance']['history_evidence'], reports[1]['run_provenance']['history_evidence'])
        self.assertEqual(reports[0]['history_identity'], reports[1]['history_identity'])
        self.assertFalse(append_history(self.history, reports[1]))

    def test_run_identity_rules_scripts_and_unknown_scientific_paths_are_retained(self):
        rows, ledger = make_ledger(self.root / 'runs', self.rows)
        write_csv(self.csv, rows)
        first = summarize(self.csv, self.control, self.experiment, self.audit, ledger)
        for field, value in (('run_id', 'different-run'), ('rules_version', '2.1'),
                             ('scripts_sha256', 'a' * 64), ('config_path', 'D:/real/config.json')):
            with self.subTest(field=field):
                changed = deepcopy(first)
                content = changed['run_provenance']['history_evidence']['ledger_content']
                if field == 'scripts_sha256':
                    content['producer'][field] = value
                elif field == 'run_id':
                    content['runs'][0][field] = value
                else:
                    content[field] = value
                self.assertNotEqual(history_identity(first), history_identity(changed))

    def test_repository_and_packaged_install_with_identical_scripts_deduplicate(self):
        package = self.root / 'installed-skill'
        shutil.copytree(fixtures.ROOT / 'scripts', package / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        (package / '.tool-release.json').write_text(json.dumps({'tool_commit': 'f' * 40,
                                                               'scripts_sha256': scripts_digest()}), encoding='utf-8')
        # Both fresh processes use the same scripts bytes, avoiding cached producer
        # stamps from other tests. Their installation markers intentionally differ.
        reports = []
        for script_dir in (fixtures.ROOT / 'scripts', package / 'scripts'):
            out = self.root / ('summary-' + str(len(reports)) + '.json')
            command = [sys.executable, '-X', 'utf8', str(script_dir / 'import_results.py'), str(self.csv),
                       '--innovation-metadata', str(self.metadata_path), '--out', str(out)]
            for name, path in self.paths.items():
                command.extend(['--' + name, str(path)])
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            reports.append(json.loads(out.read_text(encoding='utf-8')))
        self.assertNotEqual(reports[0]['producer']['commit_source'], reports[1]['producer']['commit_source'])
        self.assertEqual(reports[0]['history_identity'], reports[1]['history_identity'])
        self.assertTrue(append_history(self.history, reports[0]))
        before = self.history.read_bytes()
        self.assertFalse(append_history(self.history, reports[1]))
        self.assertEqual(self.history.read_bytes(), before)

    def test_legacy_markers_are_recognized_only_for_exact_available_summaries(self):
        report = self.report(self.metadata_path)
        report.pop('history_identity')
        legacy = b'# Original legacy history\r\n' + ('<!-- result-import:' + fingerprint(report) + ' -->\r\n').encode()
        self.history.write_bytes(legacy)
        self.assertFalse(append_history(self.history, report))
        self.assertEqual(self.history.read_bytes(), legacy)
        changed = deepcopy(report)
        changed['producer']['commit_source'] = 'other-install'
        # The old marker carries no original summary or stable digest. Matching
        # the current stable content to that opaque old hash would be a guess.
        self.assertTrue(append_history(self.history, changed))
        self.assertTrue(self.history.read_bytes().startswith(legacy))
        self.assertFalse(append_history(self.history, changed))


if __name__ == '__main__':
    unittest.main()
