"""Read-only audit of the actual protocol package against pinned upstream XML."""
import hashlib
import os
from pathlib import Path
import tarfile
import unittest
import xml.etree.ElementTree as ET

import ki2build


@unittest.skipUnless(os.environ.get('KIKI_TEST_PROTOCOLS_PACKAGE') == '1',
                     'set KIKI_TEST_PROTOCOLS_PACKAGE=1')
class ProtocolPackageTests(unittest.TestCase):
    def test_xml_headers_and_metadata(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes['wayland-protocols'], 'x86_64')
        source = repo / 'dist/sources/wayland-protocols-1.49.tar.xz'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         'ec4c8f74942d6dff7ace8b4ce4764f0ef9ff618a935d974ea77edee2ad240b14')
        with tarfile.open(source, 'r:xz') as src, tarfile.open(package, 'r:gz') as pkg:
            root = 'wayland-protocols-1.49/'
            source_xml = {m.name[len(root):]: m for m in src.getmembers()
                          if m.isfile() and m.name.startswith(root) and m.name.endswith('.xml')
                          and m.name[len(root):].split('/')[0] in ('stable','staging','unstable','experimental')}
            expected_xml = {n for n in source_xml if not n.startswith('experimental/')}
            prefix = 'rootfs/usr/share/wayland-protocols/'
            actual_xml = {m.name[len(prefix):] for m in pkg.getmembers()
                          if m.isfile() and m.name.startswith(prefix) and m.name.endswith('.xml')}
            self.assertEqual(actual_xml, expected_xml)
            for relative in sorted(expected_xml):
                with self.subTest(xml=relative):
                    data = pkg.extractfile(prefix + relative).read()
                    self.assertEqual(data, src.extractfile(source_xml[relative]).read())
                    self.assertEqual(ET.fromstring(data).tag, 'protocol')
            header_prefix = 'rootfs/usr/include/wayland-protocols/'
            # Shipped source, but intentionally absent from this release's
            # experimental_protocols build table: no header is generated.
            unbuilt = 'experimental/xx-fractional-scale/xx-fractional-scale-v2.xml'
            self.assertIn(unbuilt, source_xml)
            self.assertNotIn(b"'xx-fractional-scale':", src.extractfile(root + 'meson.build').read())
            expected_headers = {Path(n).stem + '-enum.h' for n in source_xml if n != unbuilt}
            actual_headers = {m.name[len(header_prefix):] for m in pkg.getmembers()
                              if m.isfile() and m.name.startswith(header_prefix)}
            self.assertEqual(actual_headers, expected_headers)
            for name in actual_headers:
                data = pkg.extractfile(header_prefix + name).read()
                self.assertGreater(len(data), 100)
                self.assertNotIn(b'/tmp/kiki-', data)
            pc = pkg.extractfile('rootfs/usr/share/pkgconfig/wayland-protocols.pc').read().decode()
            self.assertIn('Version: 1.49', pc)
            self.assertIn('prefix=/usr', pc)
            self.assertNotIn('/tmp/', pc)
            self.assertEqual(pkg.extractfile('rootfs/usr/share/licenses/wayland-protocols/COPYING').read(),
                             src.extractfile(root + 'COPYING').read())
            for member in pkg.getmembers():
                if member.isfile() and member.name.startswith('rootfs/'):
                    self.assertEqual(member.mode, 0o644, member.name)
                    self.assertEqual((member.uid, member.gid), (0, 0), member.name)
            print('verified XML:', len(actual_xml), 'enum headers:', len(actual_headers))


if __name__ == '__main__':
    unittest.main()
