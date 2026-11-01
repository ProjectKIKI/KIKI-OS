import json
import tempfile
import unittest
import os
import hashlib
from unittest import mock
from pathlib import Path

import ki2installcatalog as catalog


class InstallerCatalogTests(unittest.TestCase):
    def test_iso_catalog_override_controls_generated_backend_and_media_hash(self):
        data=catalog.load()
        data['groups'].append(dict(id='web-custom',name_ko='웹 그룹',name_en='Web group',description_ko='웹 편집본',requires=[],packages=dict(mandatory=[],default=[],optional=[]),services=dict(enable=[])))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'catalog.json';path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            with mock.patch.dict(os.environ,{'KI2_PACKAGE_GROUPS_FILE':str(path)}):
                self.assertIn('catalog_web_custom',catalog.backend_c())
                result=catalog.media_catalog(dict(packages=[]))
                self.assertEqual(result['catalog_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertIn('web-custom',[g['id'] for g in result['groups']])

    def test_generated_frontends_are_current(self):
        for path, content in catalog.generated().items():
            self.assertEqual(path.read_text(encoding='utf-8'), content, str(path))

    def test_desktop_does_not_depend_on_ai_and_disables_tty1(self):
        data = catalog.load()
        desktop = catalog.expand(data, ['desktop-gnome'])
        self.assertIn('kiki-gnome-desktop', desktop['packages'])
        self.assertNotIn('kiki-kmscon', desktop['packages'])
        self.assertNotIn('getty@tty1.service', desktop['enable'])
        self.assertIn('getty@tty1.service', desktop['disable'])
        self.assertEqual(desktop['default_target'], 'graphical.target')

    def test_transitive_missing_package_disables_profile_and_group(self):
        data = catalog.load()
        roots = catalog.expand(data, ['desktop-gnome'])['packages']
        index = dict(packages=[dict(name=n, size=10, dependencies=dict(runtime=['missing-renderer'] if n == 'kiki-gnome-desktop' else [])) for n in roots])
        result = catalog.media_catalog(index)
        for section in ('profiles', 'groups'):
            item = next(p for p in result[section] if p['id'] == 'desktop-gnome')
            self.assertFalse(item['available'])
            self.assertIn('missing-renderer', item['missing'][0])
        index['packages'].append(dict(name='missing-renderer', size=5, dependencies=dict(runtime=[])))
        result = catalog.media_catalog(index)
        item = next(p for p in result['profiles'] if p['id'] == 'desktop-gnome')
        self.assertTrue(item['available'])
        self.assertEqual(item['packages'], len(roots) + 1)
        self.assertEqual(item['download_bytes'], len(roots) * 10 + 5)
        self.assertIn('[profile desktop-gnome]\navailable=true', catalog.media_ini(result))


if __name__ == '__main__':
    unittest.main()
