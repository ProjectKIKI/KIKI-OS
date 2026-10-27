"""Opt-in chrooted FreeType test using the existing installer Korean font."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <ft2build.h>
#include FT_FREETYPE_H
#include <stdio.h>
int main(void) {
  FT_Library lib; FT_Face face, bad;
  if (FT_Init_FreeType(&lib)) return 1;
  int major, minor, patch;
  FT_Library_Version(lib, &major, &minor, &patch);
  if (major != 2 || minor != 14 || patch != 3) return 2;
  const unsigned char invalid[] = {0,1,2,3};
  if (!FT_New_Memory_Face(lib, invalid, sizeof invalid, 0, &bad)) return 3;
  if (FT_New_Face(lib, "/font.ttc", 0, &face)) return 4;
  if (FT_Select_Charmap(face, FT_ENCODING_UNICODE)) return 5;
  if (FT_Set_Pixel_Sizes(face, 0, 24)) return 6;
  for (unsigned long code = 0xAC00; code <= 0xD7A3; ++code) {
    if (!FT_Get_Char_Index(face, code)) return 7;
    if (FT_Load_Char(face, code, FT_LOAD_RENDER)) return 8;
    FT_Bitmap *b = &face->glyph->bitmap;
    if (!b->width || !b->rows || !b->buffer || b->pitch <= 0) return 9;
    unsigned long ink = 0;
    for (unsigned int y = 0; y < b->rows; ++y)
      for (unsigned int x = 0; x < b->width; ++x) ink += b->buffer[y*b->pitch+x];
    if (!ink) return 10;
  }
  printf("FreeType %d.%d.%d: 11172 Hangul syllables rasterized (%s)\n",
         major, minor, patch, face->family_name);
  FT_Done_Face(face); FT_Done_FreeType(lib); return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_FREETYPE") == "1",
                     "set KIKI_TEST_FREETYPE=1 on Linux as root")
class FreeTypeRuntimeTests(unittest.TestCase):
    def test_hangul_in_target_chroot(self):
        self.assertEqual(os.geteuid(), 0, "chroot test requires root")
        repo = Path(__file__).resolve().parents[1]
        font = repo / "build/ki2/host-graphics/rootfs/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"
        self.assertTrue(font.is_file(), "existing installer Korean font is required")
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-freetype-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["freetype", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertTrue((root / "usr/share/licenses/freetype/FTL.TXT").is_file())
            self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib/libfreetype.so.6")]),
                                r"\((?:RPATH|RUNPATH)\)")
            dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            flags = ["cc", "--sysroot=" + str(root), "-I" + str(root / "usr/include/freetype2")]
            for path in dirs:
                flags += ["-B" + str(path) + "/", "-L" + str(path), "-Wl,-rpath-link," + str(path)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"), "-lfreetype", "-o", str(root / "probe")])
            shutil.copyfile(font, root / "font.ttc")
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            command = ["chroot", str(root), "/" + str(loaders[0].relative_to(root)),
                       "--inhibit-cache", "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64"]
            listing = run(command + ["--list", "/probe"])
            for library in ("libfreetype.so.6", "libpng16.so.16", "libz.so.1", "libc.so.6"):
                self.assertIn(library + " => /", listing)
            self.assertIn("11172 Hangul syllables rasterized", run(command + ["/probe"]))

if __name__ == "__main__":
    unittest.main()
