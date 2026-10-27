"""Target xmllint validation, including the pinned Wayland protocol."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_LIBXML2') == '1',
                     'set KIKI_TEST_LIBXML2=1 on Linux as root')
class LibxmlRuntimeTests(unittest.TestCase):
    def test_dtd_and_unicode(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-xml-runtime-') as tmp:
            root = Path(tmp) / 'root'
            for name in ki2build.dependency_closure(recipes, ['libxml2'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ['chroot', str(root), '/' + str(loaders[0].relative_to(root)),
                    '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64', '/usr/bin/xmllint']

            def run(args, expected=0):
                result = subprocess.run(base + args, env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result

            self.assertIn('21504', run(['--version']).stderr)
            (root / 'sample.dtd').write_text('<!ELEMENT root (item+)><!ELEMENT item (#PCDATA)>')
            (root / 'good.xml').write_text('<root><item>한글 설치 확인</item></root>', encoding='utf-8')
            run(['--noout', '--dtdvalid', '/sample.dtd', '/good.xml'])
            self.assertEqual(run(['--xpath', 'string(/root/item)', '/good.xml']).stdout.strip(), '한글 설치 확인')
            (root / 'invalid.xml').write_text('<root><unexpected/></root>')
            self.assertIn('does not validate', run(['--noout','--dtdvalid','/sample.dtd','/invalid.xml'], 3).stderr)
            (root / 'broken.xml').write_text('<root><item></root>')
            self.assertIn('parser error', run(['--noout','/broken.xml'], 4).stderr)
            source = repo / 'dist/sources/wayland-1.24.0.tar.xz'
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             '82892487a01ad67b334eca83b54317a7c86a03a89cfadacfef5211f11a5d0536')
            with tarfile.open(source, 'r:xz') as archive:
                for name in ('wayland.xml', 'wayland.dtd'):
                    (root / name).write_bytes(archive.extractfile('wayland-1.24.0/protocol/' + name).read())
            run(['--noout','--dtdvalid','/wayland.dtd','/wayland.xml'])


if __name__ == '__main__':
    unittest.main()
