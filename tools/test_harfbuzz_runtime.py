"""Opt-in target shaping test, including composed/decomposed Korean text."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import ki2build

GIR_PROBE = r'''
import ctypes as c
gi = c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_get_default.restype = c.c_void_p
repo = gi.g_irepository_get_default()
gi.g_irepository_require.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int, c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype = c.c_void_p
error = c.c_void_p()
assert gi.g_irepository_require(repo, b'HarfBuzz', b'0.0', 0, c.byref(error))
assert not error.value
gi.g_irepository_find_by_name.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
gi.g_irepository_find_by_name.restype = c.c_void_p
# Unlike blob_destroy (introspectable=0), this API is in the typelib.
info = gi.g_irepository_find_by_name(repo, b'HarfBuzz', b'aat_layout_has_positioning')
assert info
gi.g_function_info_get_symbol.argtypes = [c.c_void_p]
gi.g_function_info_get_symbol.restype = c.c_char_p
assert gi.g_function_info_get_symbol(info) == b'hb_aat_layout_has_positioning'
hb = c.CDLL('libharfbuzz.so.0')
hb.hb_version_string.restype = c.c_char_p
assert hb.hb_version_string() == b'14.4.0'
gi.g_base_info_unref.argtypes = [c.c_void_p]
gi.g_base_info_unref(info)
print('HarfBuzz typelib and version symbol passed')
'''

PROBE = r"""
#include <hb.h>
#include <hb-ft.h>
#include <ft2build.h>
#include FT_FREETYPE_H
static int shape(hb_font_t *font, const uint32_t *text, int len,
                 hb_codepoint_t *glyph, hb_position_t *advance) {
  hb_buffer_t *buffer = hb_buffer_create();
  hb_buffer_add_utf32(buffer, text, len, 0, len);
  hb_buffer_set_direction(buffer, HB_DIRECTION_LTR);
  hb_buffer_set_script(buffer, HB_SCRIPT_HANGUL);
  hb_buffer_set_language(buffer, hb_language_from_string("ko", -1));
  hb_shape(font, buffer, 0, 0);
  unsigned count;
  hb_glyph_info_t *info = hb_buffer_get_glyph_infos(buffer, &count);
  hb_glyph_position_t *pos = hb_buffer_get_glyph_positions(buffer, 0);
  int good = count == 1 && info[0].codepoint && pos[0].x_advance > 0;
  if (good) { *glyph = info[0].codepoint; *advance = pos[0].x_advance; }
  hb_buffer_destroy(buffer); return good;
}
int main(void) {
  FT_Library lib; FT_Face face;
  if (FT_Init_FreeType(&lib) || FT_New_Face(lib, "/font.ttc", 0, &face)) return 1;
  if (FT_Set_Pixel_Sizes(face, 0, 24)) return 2;
  hb_font_t *font = hb_ft_font_create_referenced(face);
  for (uint32_t code = 0xAC00; code <= 0xD7A3; ++code) {
    uint32_t index = code - 0xAC00;
    uint32_t nfd[] = {0x1100 + index/588, 0x1161 + (index%588)/28, 0x11A7 + index%28};
    hb_codepoint_t a, b; hb_position_t x, y;
    if (!shape(font, &code, 1, &a, &x) || !shape(font, nfd, index%28 ? 3 : 2, &b, &y)) return 3;
    if (a != b || x != y) return 4;
  }
  if (FT_Load_Char(face, 0xD55C, FT_LOAD_RENDER | FT_LOAD_FORCE_AUTOHINT)) return 5;
  hb_font_destroy(font); FT_Done_Face(face); FT_Done_FreeType(lib); return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_HARFBUZZ") == "1",
                     "set KIKI_TEST_HARFBUZZ=1 on Linux as root")
class HarfBuzzRuntimeTests(unittest.TestCase):
    def test_target_korean_normalization(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-harfbuzz-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["harfbuzz", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            flags = ["cc", "--sysroot=" + str(root)]
            for sub in ("usr/lib", "usr/lib64", "lib", "lib64"):
                path = str(root / sub)
                flags += ["-B" + path + "/", "-L" + path, "-Wl,-rpath-link," + path]
            for sub in ("usr/include/harfbuzz", "usr/include/freetype2"):
                flags += ["-I" + str(root / sub)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"), "-lharfbuzz", "-lfreetype", "-o", str(root / "probe")])
            shutil.copyfile(repo / "build/ki2/host-graphics/rootfs/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", root / "font.ttc")
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            command = ["chroot", str(root), "/" + str(loaders[0].relative_to(root)),
                       "--inhibit-cache", "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn("libharfbuzz.so.0 => /", run(command + ["--list", "/probe"]))
            self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib/libharfbuzz.so.0")]),
                                r"\((?:RPATH|RUNPATH)\)")
            # Inspect all installed HarfBuzz shared libraries and CLI tools;
            # --list resolves dependencies without performing a tool's action.
            candidates = list((root / "usr/lib").glob("libharfbuzz*.so*"))
            candidates += list((root / "usr/bin").glob("hb-*"))
            checked = 0
            for path in candidates:
                if path.is_symlink() or not path.is_file():
                    continue
                with path.open("rb") as stream:
                    if stream.read(4) != b"\x7fELF":
                        continue
                self.assertNotRegex(run(["readelf", "-d", str(path)]), r"\((?:RPATH|RUNPATH)\)")
                run(command + ["--list", "/" + str(path.relative_to(root))])
                checked += 1
            self.assertGreaterEqual(checked, 4)
            self.assertIn("14.4.0", run(command + ["/usr/bin/hb-shape", "--version"]))
            run(command + ["/probe"])
            self.assertTrue((root / "usr/share/gir-1.0/HarfBuzz-0.0.gir").is_file())
            self.assertTrue((root / "usr/lib/girepository-1.0/HarfBuzz-0.0.typelib").is_file())
            (root / "gir-probe.py").write_text(GIR_PROBE)
            self.assertIn("typelib and version symbol passed",
                          run(command + ["/usr/bin/python3.12", "-I", "-B", "/gir-probe.py"]))

if __name__ == "__main__":
    unittest.main()
