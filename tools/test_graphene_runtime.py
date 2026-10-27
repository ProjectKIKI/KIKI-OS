"""Isolated target Graphene numeric and introspection smoke tests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ki2build

PROBE = r'''
#include <graphene.h>
#include <math.h>
static int near(float a, float b) { return fabsf(a-b) < 0.0001f; }
int main(void) {
  graphene_matrix_t m, inverse, singular;
  graphene_point3d_t translation = {10, -5, 3}, input = {2, 4, 8}, output, restored;
  graphene_matrix_init_translate(&m, &translation);
  graphene_matrix_transform_point3d(&m, &input, &output);
  if (!near(output.x, 12) || !near(output.y, -1) || !near(output.z, 11)) return 1;
  if (!graphene_matrix_inverse(&m, &inverse)) return 2;
  graphene_matrix_transform_point3d(&inverse, &output, &restored);
  if (!near(restored.x, input.x) || !near(restored.y, input.y) || !near(restored.z, input.z)) return 3;
  graphene_matrix_init_scale(&singular, 0, 1, 1);
  if (graphene_matrix_inverse(&singular, &inverse)) return 4;
  graphene_vec3_t a, b, cross;
  graphene_vec3_init(&a, 1, 0, 0); graphene_vec3_init(&b, 0, 1, 0);
  graphene_vec3_cross(&a, &b, &cross);
  if (!near(graphene_vec3_get_z(&cross), 1) || !near(graphene_vec3_dot(&a, &b), 0)) return 5;
  graphene_rect_t r, s, overlap;
  graphene_rect_init(&r, 0, 0, 20, 10); graphene_rect_init(&s, 10, 5, 20, 10);
  if (!graphene_rect_intersection(&r, &s, &overlap)) return 6;
  if (!near(overlap.origin.x, 10) || !near(overlap.origin.y, 5) ||
      !near(overlap.size.width, 10) || !near(overlap.size.height, 5)) return 7;
  graphene_rect_init(&s, 100, 100, 2, 2);
  if (graphene_rect_intersection(&r, &s, &overlap)) return 8;
  return 0;
}
'''

GIR = r'''
import ctypes as c
gi = c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_get_default.restype = c.c_void_p
repo = gi.g_irepository_get_default()
gi.g_irepository_require.argtypes = [c.c_void_p,c.c_char_p,c.c_char_p,c.c_int,c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype = c.c_void_p
error = c.c_void_p()
assert gi.g_irepository_require(repo,b'Graphene',b'1.0',0,c.byref(error))
assert not error.value
gi.g_irepository_find_by_name.argtypes = [c.c_void_p,c.c_char_p,c.c_char_p]
gi.g_irepository_find_by_name.restype = c.c_void_p
gi.g_base_info_unref.argtypes = [c.c_void_p]
for name in (b'Matrix',b'Vec3',b'Rect'):
    info = gi.g_irepository_find_by_name(repo,b'Graphene',name)
    assert info, name
    gi.g_base_info_unref(info)
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_GRAPHENE') == '1',
                     'set KIKI_TEST_GRAPHENE=1 on Linux as root')
class GrapheneRuntimeTests(unittest.TestCase):
    def test_numeric_operations_and_gir(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-graphene-runtime-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in ki2build.dependency_closure(recipes, ['graphene', 'linux-headers'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            flags = ['cc', '--sysroot=' + str(root)]
            for sub in ('usr/lib', 'usr/lib64', 'lib', 'lib64'):
                path = str(root / sub)
                flags += ['-B'+path+'/', '-L'+path, '-Wl,-rpath-link,'+path]
            for sub in ('usr/include/graphene-1.0', 'usr/lib/graphene-1.0/include'):
                flags += ['-I'+str(root / sub)]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-lgraphene-1.0', '-lm', '-o', str(root / 'probe')])
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ['chroot', str(root), '/'+str(loaders[0].relative_to(root)),
                    '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
            self.assertIn('libgraphene-1.0.so.0 => /', run(base + ['--list', '/probe']))
            self.assertNotRegex(run(['readelf','-d',str(root / 'usr/lib/libgraphene-1.0.so.0')]),
                                r'\((?:RPATH|RUNPATH)\)')
            run(base + ['/probe'])
            (root / 'gir.py').write_text(GIR)
            run(base + ['/usr/bin/python3.12', '-I', '-B', '/gir.py'])


if __name__ == '__main__':
    unittest.main()
