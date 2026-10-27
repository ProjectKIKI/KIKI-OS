"""Opt-in native libpng roundtrip and invalid-input test; no display required."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <png.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
  const unsigned char pixels[] = {0,32,96,255, 255,255,255,128,
                                  0,0,0,0, 3,17,29,255};
  png_image out = {0}; out.version = PNG_IMAGE_VERSION;
  out.width = 2; out.height = 2; out.format = PNG_FORMAT_RGBA;
  png_alloc_size_t size = 0;
  if (!png_image_write_to_memory(&out, NULL, &size, 0, pixels, 0, NULL)) return 1;
  void *buffer = malloc(size); if (!buffer) return 2;
  if (!png_image_write_to_memory(&out, buffer, &size, 0, pixels, 0, NULL)) return 3;
  png_image in = {0}; in.version = PNG_IMAGE_VERSION;
  if (!png_image_begin_read_from_memory(&in, buffer, size)) return 4;
  if (in.width != 2 || in.height != 2) return 5;
  in.format = PNG_FORMAT_RGBA;
  unsigned char actual[sizeof pixels];
  if (!png_image_finish_read(&in, NULL, actual, 0, NULL)) return 6;
  if (memcmp(pixels, actual, sizeof pixels)) return 7;
  png_image_free(&in);
  memset(&in, 0, sizeof in); in.version = PNG_IMAGE_VERSION;
  if (png_image_begin_read_from_memory(&in, buffer, 4)) return 8;
  png_image_free(&in);
  ((unsigned char*)buffer)[0] = 0;
  memset(&in, 0, sizeof in); in.version = PNG_IMAGE_VERSION;
  if (png_image_begin_read_from_memory(&in, buffer, size)) return 9;
  png_image_free(&in); png_image_free(&out); free(buffer);
  return strcmp(png_get_libpng_ver(NULL), "1.6.58") ? 10 : 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PNG") == "1",
                     "set KIKI_TEST_PNG=1 on Linux")
class PngRuntimeTests(unittest.TestCase):
    def test_target_roundtrip(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-png-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["libpng", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertTrue((root / "usr/share/licenses/libpng/LICENSE").is_file())
            self.assertFalse((root / "usr/lib/libpng16.la").exists())
            self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib/libpng16.so.16")]),
                                r"\((?:RPATH|RUNPATH)\)")
            dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            flags = ["cc", "--sysroot=" + str(root)]
            for path in dirs:
                flags += ["-B" + str(path) + "/", "-L" + str(path), "-Wl,-rpath-link," + str(path)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"), "-lpng16", "-lz", "-lm", "-o", str(work / "probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, dirs))]
            listing = run(loader + ["--list", str(work / "probe")])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            self.assertTrue({"libpng16.so.16", "libz.so.1", "libc.so.6"} <= resolved.keys())
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            run(loader + [str(work / "probe")])

if __name__ == "__main__":
    unittest.main()
