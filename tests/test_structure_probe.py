"""Only pure exported numbers and inert adapters; no tensor/model execution."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'assets/verify_structure.py'
module_spec = importlib.util.spec_from_file_location('verify_structure_fixture', SCRIPT)
probe = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(probe)


def spec():
    return {'schema_version':1,'probe_kwargs':{},
            'cases':[{'id':'a','input_shapes':{'x':[1,2]},'expected_outputs':{'logits':[1,2]}}],
            'comparison':{'atol':0.001,'rtol':0.01}}


def observation():
    outputs={'logits':{'shape':[1,2],'values':[1.0,2.0]}}
    return {'setup':{k:True for k in probe.SETUP},
            'cases':[{'id':'a','inputs':{'x':{'shape':[1,2],'sha256':'a'*64}},
                      'baseline':deepcopy(outputs),'disabled':deepcopy(outputs),
                      'enabled':{'logits':{'shape':[1,2],'values':[5.0,7.0]}}}]}


class StructureProbeTests(unittest.TestCase):
    def failed(self, data):
        report=probe.check_outputs(spec(),data)
        self.assertEqual(report['status'],'failed_or_unconfirmed')
        self.assertTrue(report['issues'])
        return report

    def test_valid_sampled_outputs_do_not_prove_setup_or_performance(self):
        report=probe.check_outputs(spec(),observation())
        self.assertEqual(report['status'],'passed_sampled_checks')
        self.assertEqual(report['cases'][0]['disabled_baseline_equivalence'],'within_tolerance')
        for key in ('setup_verified','training_absence_verified','performance_improvement_verified','dependency_closure_verified'):
            self.assertIs(report[key],False)

    def test_disabled_difference_is_detected(self):
        data=observation()
        data['cases'][0]['disabled']['logits']['values']=[1.1,2]
        report=self.failed(data)
        self.assertEqual(report['cases'][0]['disabled_baseline_equivalence'],'different')

    def test_declared_relative_and_absolute_tolerance(self):
        data=observation()
        data['cases'][0]['baseline']['logits']['values']=[0,100]
        data['cases'][0]['disabled']['logits']['values']=[0.0005,100.9]
        self.assertEqual(probe.check_outputs(spec(),data)['status'],'passed_sampled_checks')
        data['cases'][0]['disabled']['logits']['values'][0]=0.002
        self.failed(data)

    def test_shape_and_flat_element_count_are_checked(self):
        for shape,values in (([2,1],[1,2]),([1,2],[1]),([True,2],[1,2])):
            data=observation()
            data['cases'][0]['enabled']['logits']={'shape':shape,'values':values}
            self.failed(data)

    def test_nonfinite_nonnumeric_and_bool_values_rejected(self):
        for value in (float('inf'),float('nan'),True,'1',None,10**1000):
            with self.subTest(value_type=type(value).__name__):
                data=observation()
                data['cases'][0]['enabled']['logits']['values'][0]=value
                self.failed(data)

    def test_missing_and_unexpected_outputs_block(self):
        for variant in probe.VARIANTS:
            data=observation()
            data['cases'][0][variant]={}
            self.failed(data)
            data=observation()
            data['cases'][0][variant]['extra']={'shape':[],'values':[1]}
            self.failed(data)

    def test_missing_extra_and_duplicate_cases_block(self):
        for cases in ([],[observation()['cases'][0],observation()['cases'][0]],
                      [observation()['cases'][0],{**observation()['cases'][0],'id':'extra'}]):
            data=observation()
            data['cases']=deepcopy(cases)
            self.failed(data)

    def test_each_setup_declaration_must_be_true(self):
        for key in probe.SETUP:
            for value in (False,1,None):
                data=observation()
                data['setup'][key]=value
                self.failed(data)

    def test_inputs_need_matching_shapes_and_real_digest_format(self):
        for inputs in ({},{'x':{'shape':[2,1],'sha256':'a'*64}},
                       {'x':{'shape':[1,2],'sha256':'declared'}},
                       {'x':{'shape':[1,2],'sha256':'z'*64}}):
            data=observation()
            data['cases'][0]['inputs']=inputs
            self.failed(data)

    def test_scalar_outputs_supported(self):
        plan=spec()
        plan['cases'][0]['expected_outputs']={'logits':[]}
        data=observation()
        for variant in probe.VARIANTS:
            data['cases'][0][variant]={'logits':{'shape':[],'values':[2.0]}}
        self.assertEqual(probe.check_outputs(plan,data)['status'],'passed_sampled_checks')

    def test_multiple_cases_and_outputs_all_checked(self):
        plan=spec()
        plan['cases'].append({**deepcopy(plan['cases'][0]),'id':'b'})
        plan['cases'][1]['expected_outputs']['aux']=[]
        data=observation()
        second=deepcopy(data['cases'][0])
        second['id']='b'
        for variant in probe.VARIANTS:
            second[variant]['aux']={'shape':[],'values':[0]}
        data['cases'].append(second)
        self.assertEqual(probe.check_outputs(plan,data)['status'],'passed_sampled_checks')
        data['cases'][1]['disabled']['aux']['values']=[10]
        self.assertEqual(probe.check_outputs(plan,data)['status'],'failed_or_unconfirmed')

    def test_checker_does_not_modify_inputs(self):
        plan,data=spec(),observation()
        originals=deepcopy((plan,data))
        probe.check_outputs(plan,data)
        self.assertEqual((plan,data),originals)

    def test_invalid_specs_rejected(self):
        for update in ({'schema_version':True},{'probe_kwargs':[]},{'cases':[]},
                       {'comparison':{'atol':-1,'rtol':0}},
                       {'comparison':{'atol':True,'rtol':0}},
                       {'comparison':{'atol':float('inf'),'rtol':0}}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                probe.validate_spec({**spec(),**update})

    def test_duplicate_planned_case_and_unknown_template_rejected(self):
        plan=spec()
        plan['cases'].append(deepcopy(plan['cases'][0]))
        with self.assertRaises(ValueError):
            probe.validate_spec(plan)
        with self.assertRaises(ValueError):
            probe.validate_spec(json.loads((ROOT/'assets/structure_probe_spec_template.json').read_text()))

    def test_no_equivalence_claim_when_baseline_descriptor_invalid(self):
        data=observation()
        data['cases'][0]['baseline']['logits']['values']=[]
        report=self.failed(data)
        self.assertEqual(report['cases'][0]['disabled_baseline_equivalence'],'not_assessed')

    def run_cli(self, root, enabled=True):
        command=[sys.executable,str(SCRIPT),'--adapter','adapter:collect','--spec',str(root/'spec.json'),
                 '--out',str(root/'out.json')]
        if enabled:
            command.append('--execute-reviewed-probe')
        environment=dict(os.environ)
        environment['PYTHONPATH']=str(root)+os.pathsep+environment.get('PYTHONPATH','')
        return subprocess.run(command,cwd=root,env=environment,capture_output=True)

    def test_cli_without_opt_in_never_imports_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'adapter.py').write_text('from pathlib import Path\nPath("IMPORTED").touch()\n')
            (root/'spec.json').write_text(json.dumps(spec()))
            result=self.run_cli(root,False)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((root/'IMPORTED').exists())
            self.assertFalse((root/'out.json').exists())

    def test_invalid_spec_is_rejected_before_adapter_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'adapter.py').write_text('from pathlib import Path\nPath("IMPORTED").touch()\n')
            (root/'spec.json').write_text('{}')
            self.assertNotEqual(self.run_cli(root).returncode,0)
            self.assertFalse((root/'IMPORTED').exists())

    def test_cli_synthetic_adapter_called_once_and_spec_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'spec.json').write_text(json.dumps(spec()))
            (root/'observations.json').write_text(json.dumps(observation()))
            (root/'adapter.py').write_text(
                'import json\nfrom pathlib import Path\ndef collect(spec):\n'
                ' assert not Path("CALLED").exists()\n Path("CALLED").touch()\n'
                ' spec["comparison"]["atol"]=999\n'
                ' return json.loads(Path("observations.json").read_text())\n')
            result=self.run_cli(root)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads((root/'out.json').read_text(encoding='utf-8'))
            self.assertEqual(report['comparison']['atol'],0.001)
            self.assertEqual(report['inputs']['a']['x']['sha256'],'a'*64)
            self.assertEqual(len(report['probe_script_sha256']),64)
            self.assertTrue(report['source_files'])

    def test_cli_failed_comparison_saved_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'spec.json').write_text(json.dumps(spec()))
            data=observation()
            data['cases'][0]['disabled']['logits']['values']=[9,9]
            (root/'observations.json').write_text(json.dumps(data))
            (root/'adapter.py').write_text('import json\nfrom pathlib import Path\ndef collect(spec):\n return json.loads(Path("observations.json").read_text())\n')
            result=self.run_cli(root)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertEqual(json.loads((root/'out.json').read_text(encoding='utf-8'))['status'],'failed_or_unconfirmed')

    def test_strict_json_rejects_duplicates_and_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.json'
            for content in ('{"id":1,"id":2}','{"x":NaN}'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    probe.load_json(path)


if __name__=='__main__':
    unittest.main()
