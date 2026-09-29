"""Compare static reports with harmless Python functions, never target imports."""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _records import manifest, seal
from _versions import RULES_VERSION, compatibility, require_readable
from record_versions import check, migrate
from trace_config import trace


# These functions are argument-binding oracles only; no model is constructed.
def positional_default(self, width=64, /, **extra):
    return {'width': width}, extra, ()


def positional_required(self, width, /, **extra):
    return {'width': width}, extra, ()


def ordinary(self, width=64, *, flag=False):
    return {'width': width, 'flag': flag}, {}, ()


def variadic(self, width=64, *values, flag=False, **extra):
    return {'width': width, 'flag': flag}, extra, values


def keyword_required(self, *, width):
    return {'width': width}, {}, ()


class CallSemanticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.factory, self.model = self.root/'factory.py', self.root/'model.py'

    def report(self, oracle, body):
        signature = inspect.signature(oracle)
        self.model.write_text('raise RuntimeError("never import model")\nclass Model:\n'
                              f' def __init__{signature}: pass\n', encoding='utf-8')
        self.factory.write_text('raise RuntimeError("never import factory")\ndef factory(cfg):\n'
                                + textwrap.indent(body, ' ') + '\n', encoding='utf-8')
        return trace(self.factory, 'factory', self.model, 'Model', {'width': 32})

    def compare(self, oracle, expression, args=(), kwargs=None):
        kwargs = kwargs or {}
        # Executing this tiny fixture gives an independent language-level
        # reference, including inspect edge cases on older Python versions.
        named, extra, variadic_values = oracle(None, *args, **kwargs)
        report = self.report(oracle, 'return ' + expression)
        self.assertEqual(report['binding_issues'], [])
        self.assertFalse(report['unknown_unpack'])
        self.assertFalse(report['uncertain_factory_context'])
        for row in report['parameters']:
            self.assertEqual(row['constructor_input_status'], 'static_value')
        self.assertEqual({r['parameter']: r['constructor_input'] for r in report['parameters']}, named)
        self.assertEqual({k: v['constructor_input'] for k, v in report['extra_keyword_arguments'].items()}, extra)
        self.assertEqual(tuple(v['constructor_input'] for v in report['variadic_positional_arguments']), variadic_values)
        return report

    def test_same_line_rebinding_precedes_return(self):
        report = self.report(ordinary, 'cfg={"width":99}; return Model(width=cfg["width"])')
        width = report['parameters'][0]
        self.assertEqual(width['constructor_input'], 99)
        self.assertTrue(width['declared_input_mismatch'])
        self.assertGreater(width['factory_col_offset'], 1)

    def test_same_line_key_mapping_precedes_return(self):
        report = self.report(ordinary, 'keys=("width",); cfg={"width":99}; return Model(**{k:cfg[k] for k in keys})')
        self.assertEqual(report['parameters'][0]['constructor_input'], 99)

    def test_same_line_mutation_is_unknown(self):
        report = self.report(ordinary, 'ignored=mutate(cfg); return Model(width=cfg["width"])')
        self.assertTrue(report['uncertain_factory_context'])
        self.assertEqual(report['parameters'][0]['constructor_input_status'], 'unknown')

    def test_same_line_assignment_after_call_does_not_change_input(self):
        report = self.report(ordinary, 'model=Model(width=cfg["width"]); cfg={"width":99}; return model')
        self.assertEqual(report['parameters'][0]['constructor_input'], 32)

    def test_one_line_factory(self):
        self.model.write_text('class Model:\n def __init__(self,width=64): pass\n')
        self.factory.write_text('def factory(cfg): cfg={"width":99}; return Model(width=cfg["width"])\n')
        report = trace(self.factory, 'factory', self.model, 'Model', {'width':32})
        self.assertEqual(report['parameters'][0]['constructor_input'], 99)

    def test_positional_only_default_and_same_name_extra(self):
        report = self.compare(positional_default, 'Model(**{"width":32})', kwargs={'width':32})
        self.assertEqual(report['parameters'][0]['constructor_input'], 64)
        self.assertEqual(report['extra_keyword_arguments']['width']['constructor_input'], 32)

    def test_positional_only_explicit_and_same_name_extra(self):
        self.compare(positional_required, 'Model(48, width=32)', args=(48,), kwargs={'width':32})

    def test_positional_only_instance_name_in_extra(self):
        self.compare(positional_default, 'Model(**{"self":7})', kwargs={'self':7})

    def test_required_positional_only_not_filled_by_extra(self):
        with self.assertRaises(TypeError):
            positional_required(None, width=32)
        report = self.report(positional_required, 'return Model(width=32)')
        self.assertTrue(report['binding_issues'])
        self.assertEqual(report['parameters'][0]['constructor_input_status'], 'unknown')

    def test_normal_positional_and_keyword_duplicate_rejected(self):
        with self.assertRaises(TypeError):
            ordinary(None, 48, width=32)
        self.assertTrue(self.report(ordinary, 'return Model(48,width=32)')['binding_issues'])

    def test_duplicate_keyword_unpack_rejected(self):
        self.assertIn('duplicate_keyword:width', self.report(ordinary, 'return Model(width=48,**{"width":32})')['binding_issues'])

    def test_keyword_only_required_and_default(self):
        self.compare(keyword_required, 'Model(width=32)', kwargs={'width':32})
        self.compare(ordinary, 'Model(flag=True)', kwargs={'flag':True})
        self.assertTrue(self.report(keyword_required, 'return Model()')['binding_issues'])

    def test_extra_keyword_allowed_and_disallowed(self):
        self.compare(variadic, 'Model(other=[1,2])', kwargs={'other':[1,2]})
        self.assertIn('unexpected_keyword:other', self.report(ordinary, 'return Model(other=1)')['binding_issues'])

    def test_known_stars_and_variadic_values(self):
        self.compare(variadic, 'Model(*[48,7,8],flag=True,**{"other":{"x":2}})',
                     args=(48,7,8), kwargs={'flag':True,'other':{'x':2}})

    def test_tuple_default_preserves_python_type(self):
        def fixture(self, width=(1,2)):
            return {'width':width}, {}, ()
        self.compare(fixture, 'Model()')

    def test_unknown_unpack_never_confirms_defaults(self):
        for expression in ('Model(**unknown)', 'Model(*unknown)'):
            with self.subTest(expression=expression):
                report = self.report(ordinary, 'return '+expression)
                self.assertTrue(report['unknown_unpack'])
                self.assertTrue(all(r['constructor_input_status']=='unknown' for r in report['parameters']))

    def test_standard_signature_binding_reference(self):
        for oracle, expression, args, kwargs in (
            (ordinary,'Model(48,flag=True)',(48,),{'flag':True}),
            (variadic,'Model(48,7,flag=True,other=2)',(48,7),{'flag':True,'other':2}),
            (keyword_required,'Model(width=32)',(),{'width':32}),
        ):
            with self.subTest(oracle=oracle.__name__):
                bound = inspect.signature(oracle).bind(None,*args,**kwargs)
                bound.apply_defaults()
                report = self.compare(oracle, expression, args, kwargs)
                for row in report['parameters']:
                    self.assertEqual(row['constructor_input'],bound.arguments[row['parameter']])


class VersionPrecedenceTests(unittest.TestCase):
    def test_old_and_current_format_rules_matrix(self):
        for schema in (1,2):
            for rules in (None,False,[],{},999,'999.0','2.0',RULES_VERSION):
                with self.subTest(schema=schema,rules=rules):
                    record={'kind':'experiment_manifest','schema_version':schema,
                            'rules_version':rules,'producer':{'scripts_sha256':'a'*64}}
                    expected = ('supported_current' if schema==2 and rules==RULES_VERSION
                                else 'legacy_recheck_required' if rules in ('2.0',RULES_VERSION)
                                else 'unsupported_rules')
                    self.assertEqual(compatibility(record)['status'],expected)
                    if expected=='unsupported_rules':
                        with self.assertRaises(ValueError):
                            require_readable(record)

    def test_missing_rules_remains_legacy(self):
        for schema in (1,2):
            self.assertEqual(compatibility({'kind':'experiment_manifest','schema_version':schema})['status'],
                             'legacy_recheck_required')

    def test_unknown_rules_old_manifest_cannot_be_archived_or_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'old.json', Path(directory)/'archive.json'
            source.write_text(json.dumps(seal({'schema_version':1,'kind':'experiment_manifest','rules_version':'999.0'})))
            original=source.read_bytes()
            self.assertEqual(check(source)['status'],'unsupported_rules')
            with self.assertRaises(ValueError):
                migrate(source,output)
            with self.assertRaises(ValueError):
                manifest(source)
            self.assertEqual(source.read_bytes(),original)
            self.assertFalse(output.exists())

    def test_unknown_format_still_has_first_priority(self):
        self.assertEqual(compatibility({'kind':'experiment_manifest','schema_version':999,
                                        'rules_version':'999.0'})['status'],'unsupported_format')


if __name__ == '__main__':
    unittest.main()
