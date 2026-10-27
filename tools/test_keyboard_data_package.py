"""Read-only checks of the built keyboard data package, not an input/IME test."""
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET

import ki2build


@unittest.skipUnless(os.environ.get('KIKI_TEST_KEYBOARD_PACKAGE') == '1',
                     'set KIKI_TEST_KEYBOARD_PACKAGE=1')
class KeyboardPackageTests(unittest.TestCase):
    def test_korean_rules_paths_and_license(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / 'distro/recipes')['xkeyboard-config']
        package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipe, 'x86_64')
        source = repo / 'dist/sources/xkeyboard-config-2.46.tar.xz'
        with tempfile.TemporaryDirectory(prefix='kiki-keyboard-extract-') as tmp:
            target = Path(tmp) / 'root'
            ki2build.extract_package_rootfs(package, target)
            self.assertEqual((target / 'usr/share/X11/xkb').resolve(),
                             (target / 'usr/share/xkeyboard-config-2').resolve())
            self.assertTrue((target / 'usr/share/X11/xkb/symbols/kr').is_file())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '10c58218fb60d08fb1f7b30304deb3ba47613195aa8a08a81f1972775ccc3640')
        with tarfile.open(source, 'r:xz') as src, tarfile.open(package, 'r:gz') as pkg:
            prefix = 'rootfs/usr/share/xkeyboard-config-2/'
            korean = pkg.extractfile(prefix + 'symbols/kr').read()
            self.assertEqual(korean, src.extractfile('xkeyboard-config-2.46/symbols/kr').read())
            self.assertIn(b'Hangul', korean)
            for rules in ('base', 'evdev'):
                self.assertGreater(len(pkg.extractfile(prefix + 'rules/' + rules).read()), 100)
                registry = ET.fromstring(pkg.extractfile(prefix + 'rules/' + rules + '.xml').read())
                names = [node.text for node in registry.findall('./layoutList/layout/configItem/name')]
                self.assertIn('kr', names)
            legacy = pkg.getmember('rootfs/usr/share/X11/xkb')
            self.assertTrue(legacy.issym())
            self.assertEqual(legacy.linkname, '../xkeyboard-config-2')
            pc_link = pkg.getmember('rootfs/usr/share/pkgconfig/xkeyboard-config.pc')
            self.assertTrue(pc_link.issym())
            self.assertEqual(pc_link.linkname, 'xkeyboard-config-2.pc')
            pc = pkg.extractfile('rootfs/usr/share/pkgconfig/xkeyboard-config-2.pc').read()
            self.assertIn(b'Version: 2.46', pc)
            self.assertIn(b'/usr/share/xkeyboard-config-2', pc)
            self.assertNotIn(b'/tmp/', pc)
            self.assertEqual(pkg.extractfile('rootfs/usr/share/licenses/xkeyboard-config/COPYING').read(),
                             src.extractfile('xkeyboard-config-2.46/COPYING').read())
            for member in pkg.getmembers():
                if member.isfile() and member.name.startswith('rootfs/'):
                    self.assertEqual(member.mode, 0o644, member.name)
                    self.assertEqual((member.uid, member.gid), (0, 0), member.name)


if __name__ == '__main__':
    unittest.main()
