"""Regression checks for the installer's 82% timezone failure."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from zoneinfo import ZoneInfo

import ki2bootiso
import ki2build

ROOT = Path(__file__).resolve().parents[1]


class TimezoneTests(unittest.TestCase):
    def test_package_in_minimal_group_and_tui(self):
        groups = json.loads((ROOT / 'distro/sources/ki2ctl/usr/share/ki2/package-groups.json').read_text())
        minimal = next(g for g in groups['groups'] if g['id'] == 'minimal')
        self.assertIn('tzdata', minimal['packages']['mandatory'])
        recipe = ki2build.load_recipes(ROOT / 'distro/recipes')['tzdata']
        self.assertEqual(recipe.source['sha256'], '11810413345fc7805017e27ea9fa4885fd74cd61b2911711ad038f5d28d71474')
        self.assertIn('"tzdata"', (ROOT / 'cmd/kiki-installer-tui/main.go').read_text())

    def test_media_guard_precedes_formatting(self):
        source = ki2bootiso.INIT_C
        guard = source.split('static int ensure_selected_profile_packages(', 1)[1].split('\n}', 1)[0]
        self.assertIn('package_exists_in_index(index_path, "tzdata")', guard)
        self.assertIn('selected_add("tzdata")', guard)
        install = source.split('static void run_guided_package_installer_with_request(', 1)[1]
        self.assertLess(install.index('ensure_selected_profile_packages(index_path)'), install.index('write_guided_gpt(target'))
        self.assertLess(install.index('ensure_selected_profile_packages(index_path)'), install.index('format_esp_partition(esp_part)'))

    def test_built_timezone_and_actual_installer_script(self):
        root = os.environ.get('KIKI_TZDATA_ROOT')
        if not root:
            self.skipTest('Set KIKI_TZDATA_ROOT to a built tzdata payload')
        zones = Path(root) / 'usr/share/zoneinfo'
        for name, offset in [('Asia/Seoul', 9), ('Etc/UTC', 0), ('America/New_York', -5)]:
            with (zones / name).open('rb') as stream:
                zone = ZoneInfo.from_file(stream)
            self.assertEqual(datetime.datetime(2026, 1, 1, tzinfo=zone).utcoffset(), datetime.timedelta(hours=offset))
        body = ki2bootiso.INIT_C.split('static int write_target_localization_and_ai(void)', 1)[1]
        script = json.loads(re.search(r'"test -f .*ln -sfnT .*"', body).group(0))
        with tempfile.TemporaryDirectory(prefix='kiki-timezone-test-') as tmp:
            link = Path(tmp) / 'localtime'
            script = script.replace('/etc/localtime', '"$2"')
            def apply(name):
                return subprocess.run(['/bin/sh', '-c', script, 'kiki-set-timezone', str(zones / name), str(link)], timeout=10).returncode
            self.assertEqual(apply('Asia/Seoul'), 0)
            self.assertEqual(link.read_bytes(), (zones / 'Asia/Seoul').read_bytes())
            self.assertNotEqual(apply('Invalid/Timezone'), 0)
            self.assertEqual(link.read_bytes(), (zones / 'Asia/Seoul').read_bytes())


if __name__ == '__main__':
    unittest.main()
