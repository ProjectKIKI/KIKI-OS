"""Compile upstream libthai regression drivers against packaged target libraries."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_THAI') == '1',
                     'set KIKI_TEST_THAI=1 on Linux as root')
class ThaiRuntimeTests(unittest.TestCase):
    def test_upstream_drivers(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        source = repo / 'dist/sources/libthai-0.1.30.tar.xz'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         'ddba8b53dfe584c3253766030218a88825488a51a7deef041d096e715af64bdd')
        with tempfile.TemporaryDirectory(prefix='kiki-thai-runtime-') as tmp:
            root = Path(tmp) / 'root'
            for name in ki2build.dependency_closure(recipes, ['libthai', 'linux-headers'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)

            def run(command):
                result = subprocess.run(command, env={'PATH': '/usr/sbin:/usr/bin:/bin', 'LC_ALL': 'C'},
                                        capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ['chroot', str(root), '/' + str(loaders[0].relative_to(root)),
                    '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
            self.assertGreater((root / 'usr/share/libthai/thbrk.tri').stat().st_size, 0)
            for library in ['libthai.so.0', 'libdatrie.so.1']:
                self.assertNotRegex(run(['readelf', '-d', str(root / 'usr/lib' / library)]).decode(),
                                    r'\((?:RPATH|RUNPATH)\)')
            cases = ['test_thctype', 'test_thcell', 'test_thinp', 'test_thrend',
                     'test_thstr', 'test_thwchar', 'test_thbrk', 'test_thwbrk']
            with tarfile.open(source, 'r:xz') as archive:
                for case in cases:
                    with self.subTest(driver=case):
                        driver = Path(tmp) / (case + '.c')
                        driver.write_bytes(archive.extractfile('libthai-0.1.30/tests/' + case + '.c').read())
                        run(['cc', '--sysroot=' + str(root), '-std=gnu11',
                             '-B' + str(root / 'usr/lib64') + '/', '-B' + str(root / 'lib64') + '/',
                             '-I' + str(root / 'usr/include'), '-L' + str(root / 'usr/lib'),
                             '-L' + str(root / 'usr/lib64'), '-L' + str(root / 'lib64'),
                             '-Wl,-rpath-link,' + str(root / 'usr/lib'),
                             str(driver), '-lthai', '-ldatrie', '-o', str(root / case)])
                        linked = run(base + ['--list', '/' + case])
                        self.assertIn(b'libthai.so.0 => /', linked)
                        run(base + ['/' + case])


if __name__ == '__main__':
    unittest.main()
