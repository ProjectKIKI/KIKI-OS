"""Target Pango layout/rendering integration; not a VM or GTK UI test."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import ki2build

PROBE = r'''
#include <pango/pangocairo.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
int main(void) {
  if (strcmp(pango_version_string(), "1.57.1")) return 1;
  cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 480, 240);
  cairo_t *cr = cairo_create(surface);
  cairo_set_source_rgb(cr, 0, 32.0/255, 96.0/255); cairo_paint(cr);
  PangoLayout *layout = pango_cairo_create_layout(cr);
  PangoFontDescription *desc = pango_font_description_from_string("Noto Sans CJK KR 18");
  pango_layout_set_font_description(layout, desc);
  PangoContext *context = pango_layout_get_context(layout);
  pango_context_set_language(context, pango_language_from_string("ko"));
  PangoFont *font = pango_context_load_font(context, desc);
  if (!font) return 2;
  PangoFontDescription *actual = pango_font_describe(font);
  if (!strstr(pango_font_description_get_family(actual), "Noto Sans CJK")) return 3;
  pango_font_description_free(actual); g_object_unref(font);
  pango_layout_set_text(layout, "한글 설치 진행 상태", -1);
  if (pango_layout_get_unknown_glyphs_count(layout)) return 4;
  int width, height;
  pango_layout_get_pixel_size(layout, &width, &height);
  if (width <= 0 || height <= 0 || width >= 480) return 5;
  cairo_set_source_rgb(cr, 1, 1, 1);
  pango_cairo_show_layout(cr, layout);
  pango_layout_set_width(layout, 160 * PANGO_SCALE);
  pango_layout_set_wrap(layout, PANGO_WRAP_WORD_CHAR);
  pango_layout_set_text(layout, "한글 설치 진행 상태와 패키지 설치 완료 정보를 확인합니다.", -1);
  if (pango_layout_get_line_count(layout) < 2 || pango_layout_get_unknown_glyphs_count(layout)) return 6;
  cairo_move_to(cr, 0, 50); pango_cairo_show_layout(cr, layout);
  pango_layout_set_height(layout, -1);
  pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
  if (!pango_layout_is_ellipsized(layout) || pango_layout_get_line_count(layout) != 1) return 7;
  cairo_move_to(cr, 200, 50); pango_cairo_show_layout(cr, layout);
  GError *error = NULL; PangoAttrList *attrs = NULL; char *text = NULL;
  if (!pango_parse_markup("<b>설치 완료</b>", -1, 0, &attrs, &text, NULL, &error)) return 8;
  if (strcmp(text, "설치 완료")) return 9;
  pango_attr_list_unref(attrs); g_free(text);
  if (pango_parse_markup("<b>잘못된 태그", -1, 0, NULL, NULL, NULL, &error) || !error) return 10;
  g_error_free(error);
  cairo_surface_flush(surface);
  uint8_t *data = cairo_image_surface_get_data(surface);
  int stride = cairo_image_surface_get_stride(surface), changed = 0;
  for (int y=0; y<240; y++) for (int x=0; x<480; x++)
    if (((uint32_t *)(data+y*stride))[x] != 0xff002060) changed++;
  if (changed < 100 || cairo_status(cr) || cairo_surface_status(surface)) return 11;
  if (cairo_surface_write_to_png(surface, "/pango.png")) return 12;
  pango_font_description_free(desc); g_object_unref(layout);
  cairo_destroy(cr); cairo_surface_destroy(surface);
  puts("Korean layout, wrapping, ellipsis, markup and rendering passed");
  return 0;
}
'''

GIR_PROBE = r'''
import ctypes as c
gi = c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_get_default.restype = c.c_void_p
repo = gi.g_irepository_get_default()
gi.g_irepository_require.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int, c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype = c.c_void_p
gi.g_irepository_get_n_infos.argtypes = [c.c_void_p, c.c_char_p]
gi.g_irepository_get_n_infos.restype = c.c_int
for name in (b'Pango', b'PangoCairo', b'PangoFc', b'PangoFT2', b'PangoOT'):
    error = c.c_void_p()
    assert gi.g_irepository_require(repo, name, b'1.0', 0, c.byref(error)), name
    assert not error.value
    assert gi.g_irepository_get_n_infos(repo, name) > 0, name
print('Pango typelibs passed')
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_PANGO') == '1',
                     'set KIKI_TEST_PANGO=1 on Linux as root')
class PangoRuntimeTests(unittest.TestCase):
    def test_korean_layout_and_typelibs(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-pango-runtime-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in ki2build.dependency_closure(recipes, ['pango', 'linux-headers'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={'PATH': '/usr/sbin:/usr/bin:/bin', 'LC_ALL': 'C'},
                                        capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            flags = ['cc', '--sysroot=' + str(root)]
            for sub in ('usr/lib', 'usr/lib64', 'lib', 'lib64'):
                path = str(root / sub)
                flags += ['-B' + path + '/', '-L' + path, '-Wl,-rpath-link,' + path]
            for sub in ('usr/include/pango-1.0', 'usr/include/cairo', 'usr/include/harfbuzz',
                        'usr/include/glib-2.0', 'usr/lib/glib-2.0/include', 'usr/include/freetype2'):
                flags += ['-I' + str(root / sub)]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-lpangocairo-1.0', '-lpango-1.0', '-lcairo',
                         '-lgobject-2.0', '-lglib-2.0', '-o', str(root / 'probe')])
            fonts = root / 'usr/share/fonts/test'
            fonts.mkdir(parents=True)
            shutil.copyfile(repo / 'build/ki2/host-graphics/rootfs/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc', fonts / 'NotoSansCJK-Regular.ttc')
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ['chroot', str(root), '/' + str(loaders[0].relative_to(root)),
                    '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
            self.assertIn('libpango-1.0.so.0 => /', run(base + ['--list', '/probe']))
            self.assertIn('rendering passed', run(base + ['/probe']))
            self.assertTrue((root / 'pango.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            (root / 'gir.py').write_text(GIR_PROBE)
            self.assertIn('typelibs passed', run(base + ['/usr/bin/python3.12', '-I', '-B', '/gir.py']))


if __name__ == '__main__':
    unittest.main()
