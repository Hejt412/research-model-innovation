"""Portable bundle checks, without third-party dependencies or target imports."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _config_schema import validate_config


class BundleTests(unittest.TestCase):
    def test_internal_document_links_resolve(self):
        for file in ROOT.rglob('*.md'):
            if '.git' in file.parts:
                continue
            for link in re.findall(r'\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
                if '://' not in link and not link.startswith('#'):
                    self.assertTrue((file.parent / link.split('#')[0]).exists(), f'{file}: {link}')

    def test_template_is_explicitly_unknown_without_type_errors(self):
        template = json.loads((ROOT / 'assets' / 'effective_config_template.json').read_text(encoding='utf-8'))
        checked = validate_config(template)
        self.assertFalse(checked['complete'])
        self.assertTrue(checked['unknown'])
        self.assertEqual(checked['invalid'], [])


if __name__ == '__main__':
    unittest.main()
