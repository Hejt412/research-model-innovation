import base64
from copy import deepcopy
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from _records import read_json, seal, manifest, fingerprint
from _versions import compatibility, producer, scripts_digest
from experiment_manifest import snapshot, audit
from import_results import summarize
from record_versions import check, migrate, unwrap
from run_records import capture, verify
from trace_config import trace
from run_fixture import make_ledger, write_csv
from test_protocol_coverage import config


class SideEffectTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.model, self.factory = self.root/'model.py', self.root/'factory.py'
        self.model.write_text('class Model:\n def __init__(self,width=64,flag=None): pass\n')

    def trace_source(self, source):
        self.factory.write_text('raise RuntimeError("must never execute")\n' + source)
        return trace(self.factory, 'factory', self.model, 'Model', {'width':32})

    def test_unknown_call_assigned_to_unused_variable_taints_later_read(self):
        result = self.trace_source('def factory(cfg):\n ignored=mutate(cfg)\n return Model(width=cfg["width"])\n')
        self.assertTrue(result['uncertain_factory_context'])
        self.assertTrue(all(r['constructor_input_status'] == 'unknown' for r in result['parameters']))
        self.assertIn('mutate(cfg)', [r['expression'] for r in result['possible_side_effects']])

    def test_calls_in_positional_keyword_unpack_and_surrounding_expressions(self):
        sources = ['return Model(flag=mutate(cfg),width=cfg["width"])',
                   'return Model(mutate(cfg),flag=cfg["width"])',
                   'return Model(**build(cfg))',
                   'return mutate(cfg),Model(width=cfg["width"])',
                   'return Model(width=cfg.get("width", mutate(cfg)))',
                   'return Model(width=(cfg := other)["width"])']
        for source in sources:
            with self.subTest(source=source):
                result = self.trace_source('def factory(cfg):\n ' + source + '\n')
                self.assertTrue(result['uncertain_factory_context'])
                self.assertTrue(all(r['constructor_input_status'] == 'unknown' for r in result['parameters']))

    def test_plain_json_get_and_literal_comprehension_stay_resolvable(self):
        result = self.trace_source('def factory(cfg):\n keys=("width",)\n return Model(**{k:cfg[k] for k in keys},flag=cfg.get("flag",False)).to(device)\n')
        self.assertFalse(result['uncertain_factory_context'])
        self.assertEqual(result['parameters'][0]['constructor_input'], 32)
        self.assertEqual(result['possible_side_effects'], [])


class RecordTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        project = self.root/'project'
        project.mkdir()
        (project/'model.py').write_text('x=1\n')
        cfg = self.root/'cfg.json'
        values = config()
        cfg.write_text(json.dumps(values))
        self.a = snapshot(project, cfg, 'E0')
        values['model']['adapter'] = True
        cfg.write_text(json.dumps(values))
        self.b = snapshot(project, cfg, 'E1', 'E0')
        self.audit = audit(self.a,self.b,'adapter',['/model/adapter'],[])
        self.rows = [{'experiment_id': m['experiment_id'], 'seed': seed, 'task': 'A-to-B', 'metric':'accuracy',
                      'value': .6+seed*.01, 'unit':'fraction', 'manifest_sha256':m['manifest_sha256']}
                     for m in (self.a,self.b) for seed in (1,2)]
        self.rows, self.ledger = make_ledger(self.root/'runs',self.rows)
        self.manifests = {m['experiment_id']:m for m in (self.a,self.b)}

    def verify(self):
        return verify(self.ledger,self.manifests,self.rows)

    def rewrite_ledger(self, ledger):
        ledger.pop('record_sha256',None)
        ledger['record_sha256'] = fingerprint(ledger)
        self.ledger.write_text(json.dumps(ledger))

    def test_linked_files_do_not_claim_independence_proof(self):
        result = self.verify()
        self.assertEqual(result['status'],'linked_artifacts_no_reuse_detected')
        self.assertTrue(result['statistical_use_allowed'])
        self.assertFalse(result['independence_verified'])

    def test_absent_provenance_is_unknown(self):
        result = verify(None,self.manifests,self.rows)
        self.assertEqual(result['independence_status'],'unknown')
        self.assertFalse(result['statistical_use_allowed'])

    def test_changed_or_missing_artifact_blocks_decision(self):
        ledger = read_json(self.ledger)
        checkpoint = Path(ledger['runs'][0]['artifacts']['checkpoint']['path'])
        checkpoint.write_bytes(b'Changed synthetic bytes, never deserialized')
        self.assertIn('artifact_unavailable_or_changed',{i['kind'] for i in self.verify()['issues']})
        ledger['runs'][0]['artifacts']['training_log']['path'] = str(self.root/'absent.txt')
        self.rewrite_ledger(ledger)
        result = self.verify()
        self.assertFalse(result['statistical_use_allowed'])

    def test_reused_checkpoint_across_seeds_is_detected_after_valid_capture(self):
        spec_path = self.root/'runs/spec.json'
        spec = read_json(spec_path)
        first, second = spec['runs'][:2]
        Path(second['checkpoint_path']).write_bytes(Path(first['checkpoint_path']).read_bytes())
        receipt_path = Path(second['evaluation_log_path'])
        receipt = read_json(receipt_path)
        receipt['checkpoint_sha256'] = hashlib.sha256(Path(second['checkpoint_path']).read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        self.ledger.write_text(json.dumps(capture(spec_path)))
        result = self.verify()
        self.assertIn('checkpoint_reused_across_run_ids',{i['kind'] for i in result['issues']})
        self.assertFalse(result['statistical_use_allowed'])

    def test_reused_training_log_is_detected(self):
        spec_path = self.root/'runs/spec.json'
        spec = read_json(spec_path)
        first, second = spec['runs'][:2]
        Path(second['training_log_path']).write_bytes(Path(first['training_log_path']).read_bytes())
        receipt_path = Path(second['evaluation_log_path'])
        receipt = read_json(receipt_path)
        receipt['training_log_sha256'] = hashlib.sha256(Path(second['training_log_path']).read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        self.ledger.write_text(json.dumps(capture(spec_path)))
        self.assertIn('training_log_reused_across_run_ids',{i['kind'] for i in self.verify()['issues']})

    def test_repeated_metrics_from_same_run_are_allowed(self):
        rows = self.rows + [{**r,'metric':'macro_f1','value':.55} for r in self.rows]
        rows, ledger = make_ledger(self.root/'multi',rows)
        self.assertTrue(verify(ledger,self.manifests,rows)['statistical_use_allowed'])

    def test_wrong_run_id_seed_manifest_or_value_is_detected(self):
        for key,value,kind in [('run_id','missing','observation_run_missing'),
                               ('seed','2','observation_run_identity_mismatch'),
                               ('value',.99,'observation_not_in_source_results'),
                               ('manifest_sha256','a'*64,'observation_run_identity_mismatch')]:
            rows = deepcopy(self.rows)
            rows[0][key] = value
            result = verify(self.ledger,self.manifests,rows)
            self.assertIn(kind,{i['kind'] for i in result['issues']})

    def test_missing_run_id_and_changed_manifest_are_not_trusted(self):
        rows = [{k:v for k,v in r.items() if k!='run_id'} for r in self.rows]
        self.assertFalse(verify(self.ledger,self.manifests,rows)['statistical_use_allowed'])
        manifests = deepcopy(self.manifests)
        manifests['E0']['manifest_sha256']='a'*64
        self.assertIn('run_manifest_mismatch',{i['kind'] for i in verify(self.ledger,manifests,self.rows)['issues']})

    def test_receipt_identity_and_digest_checked_at_capture(self):
        spec = read_json(self.root/'runs/spec.json')
        path = Path(spec['runs'][0]['evaluation_log_path'])
        receipt = read_json(path)
        receipt['seed'] = 999
        path.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            capture(self.root/'runs/spec.json')

    def test_ledger_tamper_and_duplicate_run_id_rejected(self):
        ledger = read_json(self.ledger)
        ledger['runs'][0]['seed'] = 77
        self.ledger.write_text(json.dumps(ledger))
        with self.assertRaises(ValueError):
            self.verify()
        ledger['runs'].append(deepcopy(ledger['runs'][0]))
        self.rewrite_ledger(ledger)
        with self.assertRaises(ValueError):
            self.verify()

    def test_import_returns_provenance_and_rejects_edited_audit(self):
        csv_path = self.root/'combined.csv'
        write_csv(csv_path,self.rows)
        result = summarize(csv_path,self.a,self.b,self.audit,self.ledger)
        self.assertTrue(result['run_provenance']['statistical_use_allowed'])
        edited = deepcopy(self.audit)
        edited['status']='fake'
        with self.assertRaises(ValueError):
            summarize(csv_path,self.a,self.b,edited,self.ledger)

    def test_cli_capture_never_overwrites_existing_output(self):
        before = self.ledger.read_bytes()
        result = subprocess.run([sys.executable,str(ROOT/'scripts/run_records.py'),'capture',str(self.root/'runs/spec.json'),'--out',str(self.ledger)],capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(self.ledger.read_bytes(),before)

    def test_cli_check_and_import_link_original_observations(self):
        paths = {}
        for name, record in (('control',self.a),('experiment',self.b),('audit',self.audit)):
            paths[name] = self.root/(name+'.json')
            paths[name].write_text(json.dumps(record))
        csv_path = self.root/'combined.csv'
        write_csv(csv_path,self.rows)
        args = ['--control',str(paths['control']),'--experiment',str(paths['experiment'])]
        checked = subprocess.run([sys.executable,str(ROOT/'scripts/run_records.py'),'check',str(self.ledger),*args,'--results',str(csv_path)],capture_output=True)
        self.assertEqual(checked.returncode,0,checked.stderr)
        out = self.root/'summary.json'
        imported = subprocess.run([sys.executable,str(ROOT/'scripts/import_results.py'),str(csv_path),*args,
                                   '--audit',str(paths['audit']),'--run-records',str(self.ledger),'--out',str(out)],capture_output=True)
        self.assertEqual(imported.returncode,0,imported.stderr)
        self.assertEqual(read_json(out)['run_provenance']['status'],'linked_artifacts_no_reuse_detected')

    def test_empty_observations_and_malformed_run_do_not_pass(self):
        self.assertFalse(verify(self.ledger,self.manifests,[])['statistical_use_allowed'])
        ledger = read_json(self.ledger)
        ledger['runs'] = [None]
        self.rewrite_ledger(ledger)
        with self.assertRaises(ValueError):
            self.verify()


class VersionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root/'legacy.json'
        self.old = seal({'schema_version':1,'kind':'experiment_manifest','experiment_id':'E0','control_id':None,
                         'config':config(),'files':{'model.py':'a'*64},'skipped':[]})
        self.source.write_bytes(b'\xef\xbb\xbf'+json.dumps(self.old,indent=2).replace('\n','\r\n').encode())

    def test_legacy_version_is_reported_without_modifying_bytes(self):
        before = self.source.read_bytes()
        result = check(self.source)
        self.assertEqual(result['status'],'legacy_recheck_required')
        self.assertFalse(result['files_modified'])
        self.assertEqual(self.source.read_bytes(),before)

    def test_lossless_archive_keeps_original_seal_and_semantics(self):
        before = self.source.read_bytes()
        out = self.root/'archive.json'
        result = migrate(self.source,out)
        self.assertFalse(result['semantics_upgraded'])
        envelope = read_json(out)
        self.assertEqual(base64.b64decode(envelope['original_bytes_base64']),before)
        self.assertEqual(manifest(out),self.old)
        self.assertEqual(check(out)['status'],'legacy_recheck_required')
        self.assertEqual(self.source.read_bytes(),before)

    def test_migration_refuses_in_place_or_existing_output(self):
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            migrate(self.source,self.source)
        out = self.root/'archive.json'
        migrate(self.source,out)
        output_before = out.read_bytes()
        with self.assertRaises(FileExistsError):
            migrate(self.source,out)
        self.assertEqual(out.read_bytes(),output_before)
        self.assertEqual(self.source.read_bytes(),before)

    def test_archive_tampering_is_rejected(self):
        out = self.root/'archive.json'
        migrate(self.source,out)
        envelope = read_json(out)
        envelope['original_bytes_base64']=base64.b64encode(b'{}').decode()
        with self.assertRaises(ValueError):
            unwrap(envelope)

    def test_future_format_is_inspectable_but_not_migrated_or_consumed(self):
        future = {**self.old,'schema_version':999}
        future.pop('manifest_sha256')
        self.source.write_text(json.dumps(seal(future)))
        self.assertEqual(check(self.source)['status'],'unsupported_format')
        with self.assertRaises(ValueError):
            migrate(self.source,self.root/'archive.json')
        with self.assertRaises(ValueError):
            manifest(self.source)

    def test_rules_version_and_producer_are_separate_from_format(self):
        current = {**self.old,'schema_version':2,'rules_version':'2.0','producer':producer()}
        self.assertEqual(compatibility(current)['status'],'supported_current')
        current['rules_version']='999.0'
        self.assertEqual(compatibility(current)['status'],'unsupported_rules')
        self.assertEqual(len(producer()['scripts_sha256']),64)
        self.assertEqual(producer()['scripts_sha256'],scripts_digest())

    def test_invalid_bool_version_is_not_integer_version_one(self):
        self.assertEqual(compatibility({**self.old,'schema_version':True})['status'],'unsupported_format')

    def test_archive_rejects_bad_original_seal(self):
        old = deepcopy(self.old)
        old['experiment_id']='changed'
        self.source.write_text(json.dumps(old))
        with self.assertRaises(ValueError):
            migrate(self.source,self.root/'archive.json')

    def test_packaged_commit_stamp_is_accepted_only_with_matching_scripts(self):
        scripts = self.root/'bundle/scripts'
        shutil.copytree(ROOT/'scripts',scripts,ignore=shutil.ignore_patterns('__pycache__'))
        stamp = scripts.parent/'.tool-release.json'
        stamp.write_text(json.dumps({'scripts_sha256':scripts_digest(),'tool_commit':'a'*40}))
        code = 'import sys,json; sys.path.insert(0,sys.argv[1]); from _versions import producer; print(json.dumps(producer()))'
        def inspect():
            output = subprocess.run([sys.executable,'-c',code,str(scripts)],check=True,capture_output=True)
            return json.loads(output.stdout)
        self.assertEqual(inspect()['tool_commit'],'a'*40)
        with (scripts/'trace_config.py').open('a',encoding='utf-8') as handle:
            handle.write('\n# edited after packaging\n')
        self.assertIsNone(inspect()['tool_commit'])

    def test_cli_legacy_check_is_read_only_and_machine_readable(self):
        before = self.source.read_bytes()
        output = subprocess.run([sys.executable,str(ROOT/'scripts/record_versions.py'),'check',str(self.source)],capture_output=True)
        self.assertEqual(output.returncode,2)
        self.assertEqual(json.loads(output.stdout)['status'],'legacy_recheck_required')
        self.assertEqual(before,self.source.read_bytes())


if __name__ == '__main__':
    unittest.main()
