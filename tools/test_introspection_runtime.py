"""Opt-in packaged GIR tools and typelibs in an isolated target chroot."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ki2build

PROBE = r'''
import ctypes as c
libc = c.CDLL('libc.so.6')
libc.gnu_get_libc_version.restype = c.c_char_p
assert libc.gnu_get_libc_version() == b'2.39'
gi = c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_prepend_search_path.argtypes = [c.c_char_p]
gi.g_irepository_prepend_search_path(b'/tmp')
gi.g_irepository_get_default.restype = c.c_void_p
repo = gi.g_irepository_get_default()
gi.g_irepository_require.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int, c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype = c.c_void_p
gi.g_irepository_get_n_infos.argtypes = [c.c_void_p, c.c_char_p]
gi.g_irepository_get_n_infos.restype = c.c_int
gi.g_irepository_get_typelib_path.argtypes = [c.c_void_p, c.c_char_p]
gi.g_irepository_get_typelib_path.restype = c.c_char_p
for name in (b'GLib', b'GObject', b'Gio'):
    error = c.c_void_p()
    assert gi.g_irepository_require(repo, name, b'2.0', 0, c.byref(error)), name
    assert not error.value
    assert gi.g_irepository_get_n_infos(repo, name) > 0, name
assert gi.g_irepository_get_typelib_path(repo, b'GLib') == b'/tmp/GLib-2.0.typelib'
print('target compiler roundtrip and GLib/GObject/Gio typelibs passed')
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_INTROSPECTION') == '1',
                     'set KIKI_TEST_INTROSPECTION=1 on Linux as root')
class IntrospectionRuntimeTests(unittest.TestCase):
    def test_packaged_tools_and_typelibs(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-gi-runtime-') as tmp:
            root = Path(tmp) / 'root'
            for name in ki2build.dependency_closure(recipes, ['gobject-introspection'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            (root / 'tmp').mkdir(exist_ok=True)
            (root / 'probe.py').write_text(PROBE)
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            launcher = ['chroot', str(root), '/' + str(loaders[0].relative_to(root)),
                        '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']

            def run(*args):
                result = subprocess.run(launcher + list(args),
                                        env={'PATH': '/usr/sbin:/usr/bin:/bin', 'LC_ALL': 'C',
                                             'PYTHONDONTWRITEBYTECODE': '1'},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            self.assertIn('1.84.0', run('/usr/bin/python3.12', '-B', '/usr/bin/g-ir-scanner', '--version'))
            run('/usr/bin/g-ir-compiler', '/usr/share/gir-1.0/GLib-2.0.gir', '-o', '/tmp/GLib-2.0.typelib')
            self.assertGreater((root / 'tmp/GLib-2.0.typelib').stat().st_size, 0)
            self.assertIn('typelibs passed', run('/usr/bin/python3.12', '-I', '-B', '/probe.py'))


if __name__ == '__main__':
    unittest.main()
