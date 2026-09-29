"""Exercise static helpers against isolated fixtures; never run fixture code."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class StaticHelpersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='research-skill-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / '科研 project'
        self.repo.mkdir()
        self.marker = self.base / 'EXECUTED.txt'
        self.code = (
            'from pathlib import Path\n'
            f'Path({str(self.marker)!r}).write_text("ERROR")\n'
            'raise RuntimeError("This project must never be imported")\n'
            'import torch.nn as layers\n'
            'class Base(layers.Module):\n'
            '    def __init__(self, dim=8):\n'
            '        self.proj = layers.Linear(dim, 2)\n'
            '    def forward(self, x):\n'
            '        return self.proj(x)\n'
            'class Derived(Base):\n'
            '    pass\n'
            'learning_rate = 0.001\n'
            'args = parser.add_argument("--seed", default=42)\n')
        (self.repo / 'model.py').write_text(self.code, encoding='utf-8')
        (self.repo / 'bad.py').write_text('def broken(:\n', encoding='utf-8')
        (self.repo / 'config.yaml').write_text('train:\n  epochs: 30\n  shots: 5\n', encoding='utf-8')
        (self.repo / '.venv').mkdir()
        (self.repo / '.venv' / 'hidden.py').write_text('class Hidden: pass', encoding='utf-8')

    def run_tool(self, name, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                                capture_output=True, encoding='utf-8')
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists(), 'Project code was executed!')
        return result

    def test_scan_exclusions_and_unicode(self):
        (self.repo / 'large.py').write_text('a' * 1000)
        data = json.loads(self.run_tool('scan_project.py', self.repo, '--max-bytes', 900).stdout)
        self.assertIn('model.py', [item['path'] for item in data['files']])
        self.assertNotIn('.venv/hidden.py', [item['path'] for item in data['files']])
        self.assertIn('large.py', [item['path'] for item in data['skipped']])

    def test_models_aliases_errors_and_unknown_parameters(self):
        output = self.base / 'reports' / 'models.json'
        self.run_tool('analyze_models.py', self.repo, '--out', output)
        data = json.loads(output.read_text(encoding='utf-8'))
        rows = {row['class']: row for row in data['models']}
        self.assertEqual(set(rows), {'Base', 'Derived'})
        self.assertEqual(rows['Base']['bases'], ['torch.nn.Module'])
        self.assertIsNone(rows['Base']['parameters_total'])
        self.assertEqual(rows['Base']['assignments'][0]['target'], 'self.proj')
        self.assertTrue(any(item['path'] == 'bad.py' for item in data['errors']))

    def test_comparison_detects_semantics_and_ignores_spacing(self):
        before, same, after = [self.base / n for n in ('before.json', 'same.json', 'after.json')]
        self.run_tool('analyze_models.py', self.repo, '--out', before)
        (self.repo / 'model.py').write_text('\n\n' + self.code, encoding='utf-8')
        self.run_tool('analyze_models.py', self.repo, '--out', same)
        equal = json.loads(self.run_tool('compare_models.py', before, same).stdout)
        self.assertTrue(all(not row['class_source_changed'] for row in equal['comparisons']))
        self.assertEqual(len(equal['class_source_unchanged']), 2)
        (self.repo / 'model.py').write_text(self.code.replace('Linear(dim, 2)', 'Linear(dim, 3)'), encoding='utf-8')
        self.run_tool('analyze_models.py', self.repo, '--out', after)
        delta = json.loads(self.run_tool('compare_models.py', before, after).stdout)
        changed = [row for row in delta['comparisons'] if row['class_source_changed']]
        self.assertEqual(len(changed), 1)
        self.assertIn('Linear(dim, 3)', changed[0]['assignments_added'][0])
        self.assertTrue(delta['input_errors']['before'])

    def test_config_provenance_without_execution(self):
        data = json.loads(self.run_tool('extract_experiment_config.py', self.repo).stdout)
        self.assertIn('config.yaml', data['config_files'])
        self.assertTrue(any(row.get('target') == 'learning_rate' for row in data['evidence']))
        self.assertTrue(any(row['file'] == 'config.yaml' and row['line'] == 2 for row in data['evidence']))
        self.assertTrue(any('--seed' in str(row) for row in data['evidence']))
        self.assertTrue(data['errors'])

    def test_invalid_inputs(self):
        self.run_tool('scan_project.py', self.repo / 'absent', success=False)
        self.run_tool('analyze_models.py', self.repo, '--max-bytes', 0, success=False)
        invalid = self.base / 'invalid.json'
        invalid.write_text('{}')
        self.run_tool('compare_models.py', invalid, invalid, success=False)
        invalid.write_text('[]')
        result = self.run_tool('compare_models.py', invalid, invalid, success=False)
        self.assertNotIn('Traceback', result.stderr)

    def test_all_scripts_parse(self):
        for script in SCRIPTS.glob('*.py'):
            ast.parse(script.read_text(encoding='utf-8'), filename=str(script))

    def test_imported_helper_changes_are_detected(self):
        (self.repo / 'model.py').write_text('from helper import transform\nclass Model:\n    def forward(self, x):\n        return transform(x)\n')
        helper = self.repo / 'helper.py'
        helper.write_text('def transform(x):\n    return x\n')
        before, after = self.base / 'before.json', self.base / 'after.json'
        self.run_tool('analyze_models.py', self.repo, '--out', before)
        helper.write_text('def transform(x):\n    return x * 2\n')
        self.run_tool('analyze_models.py', self.repo, '--out', after)
        report = json.loads(self.run_tool('compare_models.py', before, after).stdout)
        row = report['comparisons'][0]
        self.assertFalse(row['class_source_changed'])
        self.assertEqual(row['status'], 'dependency_source_changed')
        self.assertEqual(row['dependency_files_changed'], ['helper.py'])
        self.assertFalse(row['runtime_equivalence_verified'])

    def test_transitive_relative_imports_and_cycles(self):
        package = self.repo / 'pkg'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / 'model.py').write_text('from .helper import f\nclass Model:\n    def forward(self, x):\n        return f(x)\n')
        (package / 'helper.py').write_text('from . import tail\ndef f(x):\n    return tail.f(x)\n')
        (package / 'tail.py').write_text('from . import helper\ndef f(x):\n    return x\n')
        data = json.loads(self.run_tool('analyze_models.py', self.repo).stdout)
        row = next(row for row in data['models'] if row['file'] == 'pkg/model.py')
        self.assertTrue({'pkg/__init__.py', 'pkg/helper.py', 'pkg/tail.py'}.issubset(row['dependencies']['files']))

    def test_peer_selectors_and_missing_selector(self):
        report = self.base / 'models.json'
        self.run_tool('analyze_models.py', self.repo, '--out', report)
        value = json.loads(self.run_tool('compare_models.py', report, '--left-model', 'model.py::Base', '--right-model', 'model.py::Derived').stdout)
        self.assertEqual(value['mode'], 'peer_models')
        self.assertEqual(len(value['comparisons']), 1)
        self.assertTrue(value['comparisons'][0]['assignments_removed'])
        self.run_tool('compare_models.py', report, '--left-model', 'absent', success=False)

    def test_legacy_reports_never_claim_behavior_unchanged(self):
        report = self.base / 'legacy.json'
        self.run_tool('analyze_models.py', self.repo, '--out', report)
        data = json.loads(report.read_text())
        data['schema_version'] = 1
        for row in data['models']:
            row.pop('dependencies')
        report.write_text(json.dumps(data))
        value = json.loads(self.run_tool('compare_models.py', report, report).stdout)
        self.assertTrue(all(r['status'] == 'dependencies_unverified' for r in value['comparisons']))
        self.assertNotIn('unchanged', value)

    def test_nested_function_does_not_pollute_module_alias_or_forward(self):
        (self.repo / 'model.py').write_text('import torch.nn as nn\ndef unrelated():\n    import other as nn\nclass Model(nn.Module):\n    def forward(self, x):\n        def never_called():\n            return hidden_training_call()\n        return x\n')
        data = json.loads(self.run_tool('analyze_models.py', self.repo).stdout)
        model = data['models'][0]
        self.assertEqual(model['bases'], ['torch.nn.Module'])
        self.assertEqual(model['methods'][0]['calls_in_source_order'], [])
        self.assertEqual(len(model['methods'][0]['returns']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
