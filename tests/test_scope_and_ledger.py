"""Synthetic scope semantics and repeated evidence merges; no project execution."""
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from literature_ledger import merge
from trace_config import trace, value, Unresolved
from _versions import RULES_VERSION, compatibility
import ast


def empty():
    return {'schema_version':1,'papers':[],'claims':[],'searches':[]}


def paper(identity='P1', name='A'):
    return {'id':identity,'title':'Synthetic '+name,'authors':['Fixture Author'],
            'doi':'10.0000/'+name.lower(),'url':'https://example.org/'+name.lower(),
            'version':'fixture','access':'methods','checked_at':'2026-09-29'}


def claim(identity='C1', source='P1'):
    return {'id':identity,'paper_id':source,'text':'Synthetic claim',
            'kind':'mechanism','locator':'fixture section'}


class ScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model, self.factory = self.root/'model.py', self.root/'factory.py'
        self.model.write_text('raise RuntimeError("never import")\nclass Model:\n def __init__(self,width=64,flag=False): pass\n')

    def trace_body(self, body):
        self.factory.write_text('raise RuntimeError("never import")\ndef factory(cfg):\n '+body+'\n')
        return trace(self.factory,'factory',self.model,'Model',{'width':32,'nested':{'width':48}})

    def test_all_comprehension_scopes_are_unknown(self):
        for expression in (
            '[Model(width=cfg["width"]) for cfg in [{"width":99}]]',
            '{Model(width=cfg["width"]) for cfg in [{"width":99}]}',
            '{"model":Model(width=cfg["width"]) for cfg in [{"width":99}]}',
            '(Model(width=cfg["width"]) for cfg in [{"width":99}])',
        ):
            with self.subTest(expression=expression):
                report = self.trace_body('return '+expression)
                self.assertTrue(report['uncertain_factory_context'])
                self.assertTrue(report['scope_limitations'])
                self.assertTrue(all(r['constructor_input_status']=='unknown' for r in report['parameters']))

    def test_scope_oracle_uses_inner_binding(self):
        cfg={'width':32}
        actual=[cfg['width'] for cfg in [{'width':99}]]
        self.assertEqual(actual,[99])
        self.assertEqual(cfg['width'],32)
        report=self.trace_body('return [Model(width=cfg["width"]) for cfg in [{"width":99}]]')
        self.assertIsNone(report['parameters'][0]['constructor_input'])

    def test_nested_and_filtered_comprehensions_stay_unknown(self):
        for expression in (
            '[[Model(width=cfg["width"]) for cfg in group] for group in [[{"width":99}]]]',
            '[Model(width=cfg["width"]) for cfg in [{"width":99}] if cfg["width"]]',
        ):
            report=self.trace_body('return '+expression)
            self.assertTrue(report['scope_limitations'])
            self.assertEqual(report['parameters'][0]['constructor_input_status'],'unknown')

    def test_assignment_containing_comprehension_is_unknown(self):
        report=self.trace_body('models=[Model(width=cfg["width"]) for cfg in [{"width":99}]]; return models')
        self.assertEqual(report['parameters'][0]['constructor_input_status'],'unknown')

    def test_fixed_keyword_comprehension_still_resolves(self):
        report=self.trace_body('keys=("width",); return Model(**{key:cfg[key] for key in keys})')
        self.assertFalse(report['scope_limitations'])
        self.assertEqual(report['parameters'][0]['constructor_input'],32)

    def test_dict_attribute_never_becomes_key_access(self):
        with self.assertRaises(AttributeError):
            {'width':32}.width
        report=self.trace_body('return Model(width=cfg.width)')
        self.assertEqual(report['parameters'][0]['constructor_input_status'],'unknown')
        self.assertIn('unverified_attribute_access',{r['reason'] for r in report['possible_side_effects']})

    def test_nested_attribute_and_alias_are_unknown(self):
        for body in ('return Model(width=cfg.nested.width)',
                     'options=cfg; return Model(width=options.width)',
                     'return Model(width=cfg["nested"].width)'):
            with self.subTest(body=body):
                self.assertEqual(self.trace_body(body)['parameters'][0]['constructor_input_status'],'unknown')

    def test_dict_subscript_and_get_match_python(self):
        cfg={'width':32,'nested':{'width':48}}
        for expression, expected in (('cfg["width"]',cfg['width']),
                                     ('cfg.get("width",64)',cfg.get('width',64)),
                                     ('cfg["nested"]["width"]',cfg['nested']['width'])):
            report=self.trace_body('return Model(width='+expression+')')
            self.assertEqual(report['parameters'][0]['constructor_input'],expected)

    def test_attribute_in_another_argument_taints_the_call(self):
        report=self.trace_body('return Model(width=cfg["width"],flag=options.enabled)')
        self.assertTrue(all(r['constructor_input_status']=='unknown' for r in report['parameters']))

    def test_literal_attribute_evaluator_is_unresolved(self):
        for expression in ('cfg.width','cfg.nested.width'):
            with self.assertRaises(Unresolved):
                value(ast.parse(expression,mode='eval').body,{'cfg':{'width':32,'nested':{'width':48}}})


class LedgerMergeTests(unittest.TestCase):
    def aliased(self):
        left,right=empty(),empty()
        left['papers']=[paper()]
        right['papers']=[paper('P2')]
        right['claims']=[claim(source='P2')]
        return merge(left,right)

    def assert_blocked(self, record):
        self.assertTrue(record['claim_audit'])
        self.assertTrue(all(row['status'] in ('paper_identity_conflict','claim_identity_conflict')
                            and row['url'] is None and row['paper_id'] is None for row in record['claim_audit']))

    def test_reused_alias_cannot_redirect_new_paper_claim(self):
        incoming=empty()
        incoming['papers']=[paper('P2','B')]
        incoming['claims']=[claim('C-new','P2')]
        result=merge(self.aliased(),incoming)
        self.assertTrue(result['conflicts'])
        new=next(c for c in result['claims'] if c['id']=='C-new')
        self.assertEqual(new['paper_id'],'P2')
        self.assert_blocked(result)
        self.assertEqual(merge(result,incoming),result)

    def test_safe_alias_keeps_original_claim_identity(self):
        result=self.aliased()
        self.assertEqual(result['claims'][0]['paper_id'],'P1')
        self.assertEqual(result['claims'][0]['source_paper_id'],'P2')
        self.assertEqual(result['claim_audit'][0]['url'],'https://example.org/a')

    def test_import_existing_ledger_preserves_aliases_and_claims(self):
        before=self.aliased()
        result=merge(empty(),before)
        self.assertEqual(result,before)
        self.assertEqual(merge(result,before),result)

    def test_conflicts_survive_either_merge_side_and_repetition(self):
        left,right=empty(),empty()
        left['papers']=[paper()]
        left['claims']=[claim()]
        right['papers']=[paper(name='B')]
        conflicted=merge(left,right)
        for first,second in ((empty(),conflicted),(conflicted,empty())):
            result=merge(first,second)
            self.assertEqual(result['conflicts'],conflicted['conflicts'])
            self.assert_blocked(result)
            self.assertEqual(merge(result,conflicted),result)

    def test_valid_alias_chain_and_later_claim(self):
        result=self.aliased()
        incoming=empty()
        incoming['aliases']={'P3':'P2'}
        result=merge(result,incoming)
        incoming=empty()
        incoming['claims']=[claim('C3','P3')]
        result=merge(result,incoming)
        self.assertEqual(result['claims'][-1]['paper_id'],'P1')
        self.assertEqual(result['claims'][-1]['source_paper_id'],'P3')
        self.assertTrue(all(r['status']=='resolved' for r in result['alias_audit']))
        self.assertEqual(merge(empty(),result),result)

    def test_cycles_and_missing_targets_are_retained_and_blocked(self):
        for aliases in ({'P2':'P3','P3':'P2'}, {'P2':'missing'}, {'P2':'P2'}):
            with self.subTest(aliases=aliases):
                incoming=empty()
                incoming['aliases']=aliases
                incoming['claims']=[claim(source='P2')]
                result=merge(empty(),incoming)
                self.assertEqual(result['aliases'],aliases)
                self.assert_blocked(result)
                self.assertTrue(all(r['status']!='resolved' for r in result['alias_audit']))
                self.assertEqual(merge(empty(),result),result)

    def test_competing_alias_targets_preserve_both_assertions(self):
        left,right=empty(),empty()
        left['papers']=[paper('P1','A')]
        right['papers']=[paper('P3','B')]
        left['aliases']={'P2':'P1'}
        right['aliases']={'P2':'P3'}
        right['claims']=[claim(source='P2')]
        for a,b in ((left,right),(right,left)):
            result=merge(a,b)
            conflict=next(c for c in result['conflicts'] if c['reason']=='alias_target_conflict')
            self.assertEqual(conflict['targets'],['P1','P3'])
            self.assert_blocked(result)
            self.assertEqual(merge(empty(),result)['conflicts'],result['conflicts'])

    def test_alias_cannot_shadow_canonical_paper_id(self):
        incoming=empty()
        incoming['papers']=[paper('P1','A'),paper('P2','B')]
        incoming['aliases']={'P2':'P1'}
        incoming['claims']=[claim(source='P2')]
        result=merge(empty(),incoming)
        self.assertTrue(result['conflicts'])
        self.assert_blocked(result)

    def test_claim_conflict_is_preserved_and_audited(self):
        left,right=empty(),empty()
        left['papers']=[paper()]
        left['claims']=[claim()]
        right['claims']=[{**claim(),'text':'Conflicting synthetic assertion'}]
        result=merge(left,right)
        self.assert_blocked(result)
        reimported=merge(empty(),result)
        self.assertEqual(result['conflicts'],reimported['conflicts'])
        self.assert_blocked(reimported)

    def test_claim_only_import_does_not_resolve_a_disputed_alias(self):
        base=self.aliased()
        conflict=empty()
        conflict['papers']=[paper('P2','B')]
        base=merge(base,conflict)
        incoming=empty()
        incoming['claims']=[claim('C-later','P2')]
        result=merge(base,incoming)
        self.assertEqual(result['claims'][-1]['paper_id'],'P2')
        self.assert_blocked(result)

    def test_input_records_are_never_modified(self):
        left,right=self.aliased(),empty()
        right['papers']=[paper('P2','B')]
        originals=deepcopy((left,right))
        merge(left,right)
        self.assertEqual((left,right),originals)

    def test_batch_permutations_never_hide_conflict_or_link_wrong_source(self):
        alias=self.aliased()
        reused,observation=empty(),empty()
        reused['papers']=[paper('P2','B')]
        observation['claims']=[claim('C-new','P2')]
        for batches in permutations((alias,reused,observation)):
            with self.subTest(order=[b['papers'] for b in batches]):
                result=empty()
                for batch in batches:
                    result=merge(result,batch)
                self.assertTrue(result['conflicts'] or any(r['status']!='resolved' for r in result['alias_audit']))
                self.assert_blocked(result)

    def test_alias_input_validation(self):
        for aliases in ([],{'P2':None},{'P2':''}):
            with self.assertRaises(ValueError):
                merge(empty(),{**empty(),'aliases':aliases})

    def test_cli_round_trip_keeps_existing_conflicts(self):
        left,right=empty(),empty()
        left['papers']=[paper()]
        left['claims']=[claim()]
        right['papers']=[paper(name='B')]
        incoming=merge(left,right)
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/name for name in ('base.json','incoming.json','out.json')]
            for path,data in zip(paths,(empty(),incoming)):
                path.write_text(json.dumps(data),encoding='utf-8')
            run=subprocess.run([sys.executable,str(ROOT/'scripts/literature_ledger.py'),'merge',
                                str(paths[0]),str(paths[1]),'--out',str(paths[2])],capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(paths[2].read_text(encoding='utf-8'))
            self.assertEqual(result['conflicts'],incoming['conflicts'])
            self.assert_blocked(result)

    def test_previous_rule_versions_require_recheck(self):
        for version in ('2.0','2.1'):
            self.assertNotEqual(version,RULES_VERSION)
            self.assertEqual(compatibility({'kind':'config_flow_evidence','schema_version':1,
                                           'rules_version':version})['status'],'legacy_recheck_required')


if __name__=='__main__':
    unittest.main()
