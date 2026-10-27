"""Opt-in packaged tool startup checks; no device enumeration or forwarding."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_LIBUSBMUXD') == '1',
                     'set KIKI_TEST_LIBUSBMUXD=1 on Linux')
class LibusbmuxdRuntimeTests(unittest.TestCase):
    def test_packaged_tools_help_version_and_target_linkage(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        names = ki2build.dependency_closure(recipes, ['libusbmuxd'], 'x86_64', include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix='kiki-usbmux-runtime-') as tmp:
            root = Path(tmp) / 'root'
            for name in names:
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            # Shared-only development packages must not export stale libtool paths.
            for stem in ('libusbmuxd-2.0', 'libimobiledevice-glue-1.0', 'libplist-2.0', 'libplist++-2.0'):
                self.assertFalse((root / 'usr/lib' / (stem + '.la')).exists())
                self.assertTrue((root / 'usr/lib' / (stem + '.so')).is_file())
                self.assertTrue((root / 'usr/lib/pkgconfig' / (stem + '.pc')).is_file())
            env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
            def run(command):
                result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            paths = ':'.join(str(root / p) for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64'))
            loader = [str(loaders[0]), '--inhibit-cache', '--library-path', paths]
            for name in ('usr/lib/libusbmuxd-2.0.so.7', 'usr/bin/iproxy', 'usr/bin/inetcat'):
                self.assertNotRegex(run(['readelf', '-d', str(root / name)]), r'\((?:RPATH|RUNPATH)\)')
            for name in ('iproxy', 'inetcat'):
                binary = str(root / 'usr/bin' / name)
                listing = run(loader + ['--list', binary])
                resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(', listing, re.MULTILINE))
                for soname in ('libusbmuxd-2.0.so.7', 'libimobiledevice-glue-1.0.so.0', 'libc.so.6'):
                    self.assertIn(soname, resolved)
                for path in resolved.values():
                    self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
                self.assertIn(name + ' 2.1.1', run(loader + [binary, '-v']))
                self.assertIn('Usage:', run(loader + [binary, '-h']))
            print('KIKI iproxy/inetcat: help, version, target linkage and RPATH checks passed')


if __name__ == '__main__':
    unittest.main()
