"""Audit built protocol artifacts against their pinned sources without X access."""
import hashlib
import os
from pathlib import Path
import tarfile
import unittest

import ki2build


@unittest.skipUnless(os.environ.get('KIKI_TEST_XORG_PROTOCOLS') == '1',
                     'set KIKI_TEST_XORG_PROTOCOLS=1')
class ProtocolPackagesTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[1]
        self.recipes = ki2build.load_recipes(self.repo / 'distro/recipes')

    def package(self, name):
        return tarfile.open(self.repo / 'dist/ki2/packages/x86_64' /
                            ki2build.package_filename(self.recipes[name], 'x86_64'), 'r:gz')

    def test_xorg_headers_and_all_licenses(self):
        path = self.repo / 'dist/sources/xorgproto-2025.1.tar.xz'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '56898c716c0578df8a2d828c9c3e5c528277705c0484381a81960fe1a67668e8')
        with tarfile.open(path, 'r:xz') as src, self.package('xorgproto') as pkg:
            root = 'xorgproto-2025.1/'
            headers = [m for m in pkg.getmembers() if m.isfile() and
                       m.name.startswith('rootfs/usr/include/')]
            self.assertGreater(len(headers), 100)
            for member in headers:
                relative = member.name.removeprefix('rootfs/usr/')
                data = pkg.extractfile(member).read()
                if relative == 'include/X11/Xpoll.h':
                    # Generated portability header: not identical to its .in template.
                    self.assertIn(b'XFD_SETSIZE', data)
                    self.assertNotIn(b'@', data)
                else:
                    self.assertEqual(data, src.extractfile(root + relative).read(), relative)
            expected = {Path(m.name).name for m in src.getmembers() if m.isfile()
                        and m.name.startswith(root + 'COPYING-')}
            prefix = 'rootfs/usr/share/licenses/xorgproto/'
            actual = {m.name[len(prefix):] for m in pkg.getmembers()
                      if m.isfile() and m.name.startswith(prefix)}
            self.assertEqual(actual, expected)
            for name in expected:
                self.assertEqual(pkg.extractfile(prefix + name).read(), src.extractfile(root + name).read())
            for name in ('xproto', 'kbproto', 'inputproto', 'xwaylandproto'):
                data = pkg.extractfile('rootfs/usr/share/pkgconfig/' + name + '.pc').read()
                self.assertIn(b'prefix=/usr', data)
                self.assertNotIn(b'/tmp/', data)
            print('Xorg headers:', len(headers), 'licenses:', len(actual))

    def test_xcb_xml_and_python_sources(self):
        path = self.repo / 'dist/sources/xcb-proto-1.17.0.tar.xz'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '2c1bacd2110f4799f74de6ebb714b94cf6f80fb112316b1219480fd22562148c')
        with tarfile.open(path, 'r:xz') as src, self.package('xcb-proto') as pkg:
            root = 'xcb-proto-1.17.0/'
            for subdir, prefix, suffixes in (
                ('src/', 'rootfs/usr/share/xcb/', ('.xml', '.xsd')),
                ('xcbgen/', 'rootfs/usr/lib/python3.12/site-packages/xcbgen/', ('.py',)),
            ):
                expected = {m.name[len(root + subdir):] for m in src.getmembers()
                            if m.isfile() and m.name.startswith(root + subdir) and m.name.endswith(suffixes)}
                actual = {m.name[len(prefix):] for m in pkg.getmembers()
                          if m.isfile() and m.name.startswith(prefix) and m.name.endswith(suffixes)}
                self.assertEqual(actual, expected)
                self.assertTrue(expected)
                for name in expected:
                    self.assertEqual(pkg.extractfile(prefix + name).read(),
                                     src.extractfile(root + subdir + name).read())
                print('XCB', subdir, len(actual))
            pc = pkg.extractfile('rootfs/usr/share/pkgconfig/xcb-proto.pc').read()
            self.assertIn(b'Version: 1.17.0', pc)
            self.assertIn(b'prefix=/usr\n', pc)
            self.assertIn(b'PYTHON_PREFIX=${prefix}\n', pc)
            self.assertIn(b'pythondir=${pc_sysrootdir}${PYTHON_PREFIX}/lib/python3.12/site-packages\n', pc)
            self.assertNotIn(b'/tmp/', pc)
            self.assertEqual(pkg.extractfile('rootfs/usr/share/licenses/xcb-proto/COPYING').read(),
                             src.extractfile(root + 'COPYING').read())


if __name__ == '__main__':
    unittest.main()
