"""Synthetic identity/observation fixtures; never import models or run training."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _records import fingerprint
from experiment_manifest import audit, snapshot
from import_results import append_history, summarize
from test_protocol_coverage import config
from run_fixture import make_ledger, write_csv


class InnovationHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        project = self.root / 'project'
        project.mkdir()
        # Snapshot reads source bytes, never executes this deliberately unsafe fixture.
        (project / 'model.py').write_text('raise RuntimeError("must never import")\n', encoding='utf-8')
        cfg = config()
        cfg['evaluation']['tasks'] = ['A-to-B']
        cfg['evaluation']['sampling'] = 'fixed_split'
        cfg['evaluation']['metrics'] = [cfg['evaluation']['metrics'][0]]
        config_path = self.root / 'config.json'
        config_path.write_text(json.dumps(cfg), encoding='utf-8')
        self.control = snapshot(project, config_path, 'E-control')
        cfg['model']['adapter'] = True
        config_path.write_text(json.dumps(cfg), encoding='utf-8')
        self.experiment = snapshot(project, config_path, 'E-experiment', 'E-control')
        self.audit = audit(self.control, self.experiment, 'adapter', ['/model/adapter'], [])
        self.csv = self.root / 'observations.csv'
        self.rows = [{'experiment_id': exp['experiment_id'], 'seed': seed, 'task': 'A-to-B',
                      'metric': 'accuracy', 'value': .7 + (.01 * seed if exp is self.experiment else 0),
                      'unit': 'fraction', 'manifest_sha256': exp['manifest_sha256']}
                     for exp in (self.control, self.experiment) for seed in (1, 2)]
        write_csv(self.csv, self.rows)
        metadata_dir = self.root / '研究记录'
        metadata_dir.mkdir()
        self.card = metadata_dir / 'source-card.md'
        self.card.write_text('# Synthetic user-declared mechanism card\n', encoding='utf-8')
        self.metadata_path = metadata_dir / 'unrelated-filename.json'
        self.metadata = {
            'schema_version': 1, 'kind': 'innovation_metadata', 'research_id': 'R-synthetic',
            'innovation_id': 'I-synthetic', 'gap_ids': ['G-synthetic'],
            'paper_ids': ['P-synthetic'], 'history_id': 'H-synthetic',
            'source_card_path': 'source-card.md',
            'mechanism_fingerprint': {'location': 'model.py: feature fusion',
                                      'transformation': 'x + gate(support) * residual(x)',
                                      'data_dependencies': ['support features', 'query features without query labels'],
                                      'objective': 'Preserve baseline loss; condition the residual on support'},
            'control': {k: self.control[k] for k in ('experiment_id', 'manifest_sha256')},
            'experiment': {k: self.experiment[k] for k in ('experiment_id', 'manifest_sha256')}
        }
        self.write_metadata()
        self.history = self.root / 'history.md'
        self.history.write_bytes(b'# Prior history\r\nRejected mechanism retained.\r\n')
        self.paths = {}
        for name in ('control', 'experiment', 'audit'):
            path = self.root / (name + '.json')
            path.write_text(json.dumps(getattr(self, name)), encoding='utf-8')
            self.paths[name] = path

    def write_metadata(self, value=None):
        self.metadata_path.write_text(json.dumps(self.metadata if value is None else value, ensure_ascii=False), encoding='utf-8')

    def report(self, path=None):
        return summarize(self.csv, self.control, self.experiment, self.audit, innovation_metadata=path)

    def cli(self, out=None, history=None, metadata=None, ledger=None):
        command = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/import_results.py'), str(self.csv)]
        for name, path in self.paths.items():
            command.extend(['--' + name, str(path)])
        command.extend(['--out', str(out or self.root / 'summary.json')])
        for flag, path in (('--history', history), ('--innovation-metadata', metadata), ('--run-records', ledger)):
            if path is not None:
                command.extend([flag, str(path)])
        return subprocess.run(command, capture_output=True, text=True, encoding='utf-8')

    def test_missing_metadata_imports_without_fabricated_identity(self):
        report = self.report()
        association = report['innovation_link']
        self.assertEqual(association['status'], 'not_linked_manual_completion_required')
        self.assertNotIn('metadata', association)
        self.assertFalse(association['mathematical_equivalence_verified'])
        self.assertTrue(append_history(self.history, report))
        content = self.history.read_text(encoding='utf-8')
        self.assertIn('机制身份：未关联', content)
        self.assertNotIn('H-synthetic', content)
        self.assertEqual(report['groups'][0]['paired_seed_count'], 2)

    def test_link_uses_explicit_ids_and_resolves_card_relative_to_metadata(self):
        report = self.report(self.metadata_path)
        association = report['innovation_link']
        self.assertEqual(association['metadata'], self.metadata)
        self.assertEqual(association['source_card']['path'], str(self.card.resolve()))
        self.assertEqual(association['source_card']['sha256'], hashlib.sha256(self.card.read_bytes()).hexdigest())
        self.assertEqual(association['metadata_file_sha256'], hashlib.sha256(self.metadata_path.read_bytes()).hexdigest())
        self.assertEqual(association['metadata_record_sha256'], fingerprint(self.metadata))
        self.assertEqual(association['mechanism_fingerprint_sha256'], fingerprint(self.metadata['mechanism_fingerprint']))
        plain = self.report()
        self.assertEqual(report['groups'], plain['groups'])
        self.assertEqual(report['interpretation_status'], plain['interpretation_status'])
        self.assertFalse(report['mechanism_benefit_proven'])

    def test_schema2_pending_search_keeps_negative_result_mechanism_identity(self):
        self.metadata.update(schema_version=2, paper_ids=[], literature_status='pending_search')
        self.write_metadata()
        for row in self.rows:
            if row['experiment_id'] == self.experiment['experiment_id']:
                row['value'] = .6
        write_csv(self.csv, self.rows)
        report = self.report(self.metadata_path)
        association = report['innovation_link']
        self.assertEqual(association['status'], 'partially_linked_declared_metadata_review_required')
        self.assertEqual(association['association_completeness'], 'partial_declared')
        self.assertEqual(association['literature_status'], 'pending_search')
        self.assertEqual(association['metadata']['paper_ids'], [])
        self.assertLess(report['groups'][0]['mean_delta'], 0)
        self.assertFalse(report['mechanism_benefit_proven'])
        self.assertTrue(append_history(self.history, report))
        before = self.history.read_bytes()
        self.assertFalse(append_history(self.history, report))
        self.assertEqual(self.history.read_bytes(), before)
        content = before.decode('utf-8')
        for identity in ('R-synthetic', 'I-synthetic', 'G-synthetic', 'H-synthetic', 'E-experiment'):
            self.assertIn(identity, content)
        self.assertIn('partial_declared', content)
        self.assertIn('pending_search', content)
        self.assertNotIn('P-synthetic', content)
        self.metadata.update(paper_ids=['P-later-declared'], literature_status='references_declared')
        self.write_metadata()
        revised = self.report(self.metadata_path)
        self.assertEqual(revised['innovation_link']['association_completeness'], 'complete_declared')
        self.assertTrue(append_history(self.history, revised))
        self.assertTrue(self.history.read_bytes().startswith(before))
        self.assertIn('追加记录或修订', self.history.read_text(encoding='utf-8'))

    def test_schema2_unknown_is_explicit_and_conflicting_literature_states_rejected(self):
        record = {**self.metadata, 'schema_version': 2, 'paper_ids': [], 'literature_status': 'unknown'}
        self.write_metadata(record)
        association = self.report(self.metadata_path)['innovation_link']
        self.assertEqual(association['literature_status'], 'unknown')
        self.assertEqual(association['literature_verification'], 'not_verified_by_tool')
        invalid = [{**record, 'literature_status': status} for status in
                   ('references_declared', 'verified', 'complete', '', None, [], True)]
        invalid.extend([{**record, 'paper_ids': ['P-synthetic'], 'literature_status': status}
                        for status in ('pending_search', 'unknown')])
        for value in invalid:
            with self.subTest(record=value):
                self.write_metadata(value)
                with self.assertRaises(ValueError):
                    self.report(self.metadata_path)

    def test_schema2_unknown_placeholder_ids_are_rejected(self):
        record = {**self.metadata, 'schema_version': 2, 'literature_status': 'references_declared'}
        for field in ('research_id', 'innovation_id', 'history_id', 'gap_ids', 'paper_ids'):
            for unknown in ('unknown', 'UNKNOWN'):
                with self.subTest(field=field, unknown=unknown):
                    value = [unknown] if field.endswith('_ids') else unknown
                    self.write_metadata({**record, field: value})
                    with self.assertRaises(ValueError):
                        self.report(self.metadata_path)

    def test_schema1_original_string_id_boundary_remains_readable(self):
        record = {**self.metadata, 'research_id': 'unknown', 'paper_ids': ['unknown']}
        self.write_metadata(record)
        association = self.report(self.metadata_path)['innovation_link']
        self.assertEqual(association['metadata'], record)
        self.assertEqual(association['status'], 'linked_declared_metadata_review_required')
        self.assertEqual(association['literature_verification'], 'not_verified_by_tool')
        self.write_metadata({**record, 'paper_ids': []})
        with self.assertRaises(ValueError):
            self.report(self.metadata_path)

    def test_schema2_partial_links_still_require_source_card_and_exact_experiment_links(self):
        record = {**self.metadata, 'schema_version': 2, 'paper_ids': [], 'literature_status': 'pending_search'}
        invalid = [{**record, 'source_card_path': 'missing.md'},
                   {**record, 'gap_ids': []},
                   {**record, 'control': record['experiment']},
                   {**record, 'experiment': {**record['experiment'], 'manifest_sha256': '0' * 64}}]
        for value in invalid:
            with self.subTest(record=value):
                self.write_metadata(value)
                before = self.history.read_bytes()
                result = self.cli(metadata=self.metadata_path, history=self.history)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(self.history.read_bytes(), before)
                self.assertFalse((self.root / 'summary.json').exists())

    def test_missing_fields_and_unsupported_versions_are_rejected(self):
        cases = []
        for field in self.metadata:
            record = deepcopy(self.metadata)
            del record[field]
            cases.append(record)
        for version in (True, '1', 0, 2, None):
            cases.append({**self.metadata, 'schema_version': version})
        cases.extend([[], None, {**self.metadata, 'kind': 'other'}, {**self.metadata, 'reseach_id': 'typo'}])
        for record in cases:
            with self.subTest(record=record):
                self.metadata_path.write_text(json.dumps(record), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.report(self.metadata_path)

    def test_string_ids_and_evidence_lists_are_strict(self):
        for field in ('research_id', 'innovation_id', 'history_id'):
            for invalid in ('', ' ', ' padded', 'two ids', 'bad\nID', 7, True, None, []):
                with self.subTest(field=field, invalid=invalid):
                    self.write_metadata({**self.metadata, field: invalid})
                    with self.assertRaises(ValueError):
                        self.report(self.metadata_path)
        for field in ('gap_ids', 'paper_ids'):
            for invalid in ([], [''], ['P', 'P'], [1], 'P', None, ['two ids']):
                with self.subTest(field=field, invalid=invalid):
                    self.write_metadata({**self.metadata, field: invalid})
                    with self.assertRaises(ValueError):
                        self.report(self.metadata_path)

    def test_structured_mechanism_requires_all_four_dimensions(self):
        original = self.metadata['mechanism_fingerprint']
        invalid = ['module-name', {}, {**original, 'name': 'name-only'},
                   {**original, 'location': 1}, {**original, 'transformation': ''},
                   {**original, 'objective': None}, {**original, 'data_dependencies': []},
                   {**original, 'data_dependencies': 'x'}, {**original, 'data_dependencies': [True]}]
        invalid.extend([{k: v for k, v in original.items() if k != missing} for missing in original])
        for mechanism in invalid:
            with self.subTest(mechanism=mechanism):
                self.write_metadata({**self.metadata, 'mechanism_fingerprint': mechanism})
                with self.assertRaises(ValueError):
                    self.report(self.metadata_path)

    def test_manifest_identity_and_digest_mismatches_are_rejected(self):
        for role in ('control', 'experiment'):
            for link in ({**self.metadata[role], 'experiment_id': 'E-other'},
                         {**self.metadata[role], 'manifest_sha256': '0' * 64},
                         {**self.metadata[role], 'manifest_sha256': 'BAD'},
                         {**self.metadata[role], 'experiment_id': 1},
                         self.metadata['experiment' if role == 'control' else 'control']):
                with self.subTest(role=role, link=link):
                    self.write_metadata({**self.metadata, role: link})
                    with self.assertRaises(ValueError):
                        self.report(self.metadata_path)
        result = self.cli(metadata=self.metadata_path, history=self.history)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'summary.json').exists())
        self.assertEqual(self.history.read_bytes(), b'# Prior history\r\nRejected mechanism retained.\r\n')

    def test_source_card_is_required_and_is_not_guessed_from_filename(self):
        for path in ('', 'absent.md', '.', True):
            with self.subTest(path=path):
                self.write_metadata({**self.metadata, 'source_card_path': path})
                with self.assertRaises(ValueError):
                    self.report(self.metadata_path)
        self.write_metadata()
        self.card.write_bytes(b'')
        with self.assertRaises(ValueError):
            self.report(self.metadata_path)

    def test_duplicate_json_keys_and_nonfinite_json_rejected(self):
        for extra in ('"research_id": "R-second"', '"schema_version": NaN'):
            self.metadata_path.write_text(json.dumps(self.metadata)[:-1] + ', ' + extra + '}', encoding='utf-8')
            with self.assertRaises(ValueError):
                self.report(self.metadata_path)

    def test_history_is_idempotent_and_preserves_existing_bytes(self):
        original = self.history.read_bytes()
        report = self.report(self.metadata_path)
        self.assertTrue(append_history(self.history, report))
        first = self.history.read_bytes()
        self.assertTrue(first.startswith(original))
        self.assertFalse(append_history(self.history, self.report(self.metadata_path)))
        self.assertEqual(self.history.read_bytes(), first)
        content = first.decode('utf-8')
        for identity in ('R-synthetic', 'I-synthetic', 'G-synthetic', 'P-synthetic', 'H-synthetic'):
            self.assertIn(identity, content)
        for value in (self.metadata['mechanism_fingerprint']['transformation'],
                      report['control_sha256'], report['experiment_sha256'],
                      report['innovation_link']['metadata_file_sha256']):
            self.assertIn(value, content)

    def test_metadata_changes_append_revision_and_never_replace_old_history(self):
        first = self.report(self.metadata_path)
        append_history(self.history, first)
        before = self.history.read_bytes()
        self.metadata['mechanism_fingerprint']['transformation'] = 'x + gate(support, query) * residual(x)'
        self.write_metadata()
        revised = self.report(self.metadata_path)
        self.assertNotEqual(first['innovation_link']['mechanism_fingerprint_sha256'],
                            revised['innovation_link']['mechanism_fingerprint_sha256'])
        self.assertTrue(append_history(self.history, revised))
        after = self.history.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertIn('追加记录或修订', after.decode('utf-8'))
        self.assertEqual(after.count(b'<!-- result-import:'), 2)
        self.assertFalse(append_history(self.history, revised))

    def test_identical_mechanism_does_not_collapse_distinct_user_identities(self):
        first = self.report(self.metadata_path)
        append_history(self.history, first)
        self.metadata.update(innovation_id='I-renamed', history_id='H-other')
        self.write_metadata()
        second = self.report(self.metadata_path)
        self.assertEqual(first['innovation_link']['mechanism_fingerprint_sha256'], second['innovation_link']['mechanism_fingerprint_sha256'])
        self.assertFalse(second['innovation_link']['mathematical_equivalence_verified'])
        self.assertTrue(append_history(self.history, second))
        self.assertEqual(self.history.read_bytes().count(b'<!-- result-import:'), 2)

    def test_raw_metadata_and_source_card_changes_are_visible_in_history(self):
        first = self.report(self.metadata_path)
        append_history(self.history, first)
        self.metadata_path.write_text(json.dumps(self.metadata, indent=2), encoding='utf-8-sig')
        reformatted = self.report(self.metadata_path)
        self.assertNotEqual(first['innovation_link']['metadata_file_sha256'], reformatted['innovation_link']['metadata_file_sha256'])
        self.assertEqual(first['innovation_link']['metadata_record_sha256'], reformatted['innovation_link']['metadata_record_sha256'])
        self.assertTrue(append_history(self.history, reformatted))
        self.card.write_text('# Revised synthetic source\n', encoding='utf-8')
        updated_card = self.report(self.metadata_path)
        self.assertNotEqual(updated_card['innovation_link']['source_card'], reformatted['innovation_link']['source_card'])
        self.assertTrue(append_history(self.history, updated_card))

    def test_old_report_without_link_remains_appendable_and_idempotent(self):
        report = self.report()
        del report['innovation_link']
        self.assertTrue(append_history(self.history, report))
        self.assertFalse(append_history(self.history, report))
        self.assertIn('机制身份：未关联', self.history.read_text(encoding='utf-8'))

    def test_later_manual_association_does_not_replace_unlinked_observation(self):
        append_history(self.history, self.report())
        before = self.history.read_bytes()
        self.assertTrue(append_history(self.history, self.report(self.metadata_path)))
        after = self.history.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(after.count(b'<!-- result-import:'), 2)
        self.assertIn('机制身份：未关联', after.decode('utf-8'))
        self.assertIn('机制身份：已关联用户元数据', after.decode('utf-8'))

    def test_successful_cli_exports_the_same_association_and_history(self):
        result = self.cli(metadata=self.metadata_path, history=self.history)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.root / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['innovation_link']['metadata'], self.metadata)
        before = self.history.read_bytes()
        result = self.cli(metadata=self.metadata_path, history=self.history)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.history.read_bytes(), before)

    def test_outputs_cannot_overwrite_direct_inputs_or_each_other(self):
        inputs = [self.csv, *self.paths.values(), self.metadata_path, self.card]
        for original in inputs:
            for kind in ('out', 'history'):
                with self.subTest(original=original, kind=kind):
                    before = {p: p.read_bytes() for p in inputs}
                    kwargs = {kind: original, 'metadata': self.metadata_path}
                    result = self.cli(**kwargs)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
                    self.assertFalse((self.root / 'summary.json').exists())
        result = self.cli(out=self.history, history=self.history, metadata=self.metadata_path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.history.read_bytes(), b'# Prior history\r\nRejected mechanism retained.\r\n')

    def test_hardlinked_output_and_history_cannot_overwrite_inputs(self):
        for original in (self.csv, self.metadata_path, self.card):
            alias = self.root / ('alias-' + original.name)
            try:
                os.link(original, alias)
            except OSError as exc:
                self.skipTest('Hard links unavailable: ' + str(exc))
            before = original.read_bytes()
            for kind in ('out', 'history'):
                with self.subTest(original=original, kind=kind):
                    result = self.cli(metadata=self.metadata_path, **{kind: alias})
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(original.read_bytes(), before)
                    self.assertFalse((self.root / 'summary.json').exists())

    def test_resolved_relative_alias_cannot_overwrite_input(self):
        alias = self.root / 'project' / '..' / self.csv.name
        before = self.csv.read_bytes()
        result = self.cli(out=alias)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.csv.read_bytes(), before)

    def test_symbolic_output_alias_cannot_overwrite_input_when_available(self):
        alias = self.root / 'symlink-output.csv'
        try:
            alias.symlink_to(self.csv)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Symbolic links unavailable: ' + str(exc))
        before = self.csv.read_bytes()
        result = self.cli(out=alias)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.csv.read_bytes(), before)

    def test_output_cannot_overwrite_run_ledger_or_its_original_artifacts(self):
        run_rows, ledger = make_ledger(self.root / 'synthetic-runs', self.rows)
        write_csv(self.csv, run_rows)
        records = json.loads(ledger.read_text(encoding='utf-8'))
        originals = [ledger] + [Path(a['path']) for r in records['runs'] for a in r['artifacts'].values()]
        for original in originals:
            before = original.read_bytes()
            with self.subTest(original=original):
                result = self.cli(out=original, ledger=ledger, metadata=self.metadata_path)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(original.read_bytes(), before)
        alias = self.root / 'ledger-linked.json'
        try:
            os.link(ledger, alias)
        except OSError as exc:
            self.skipTest('Hard links unavailable: ' + str(exc))
        result = self.cli(history=alias, ledger=ledger)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(ledger.read_bytes(), alias.read_bytes())


if __name__ == '__main__':
    unittest.main()
