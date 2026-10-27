"""Opt-in packaged Unicode normalization tests, including all Hangul syllables."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <uninorm.h>
int main(void) {
  for (uint32_t s = 0xac00; s <= 0xd7a3; s++) {
    uint32_t index = s - 0xac00;
    uint32_t expected[3] = {0x1100 + index / 588,
                           0x1161 + (index % 588) / 28,
                           0x11a7 + index % 28};
    size_t n = 0, count = index % 28 ? 3 : 2;
    uint32_t *decomposed = u32_normalize(UNINORM_NFD, &s, 1, NULL, &n);
    if (!decomposed || n != count || memcmp(decomposed, expected, count * 4)) return 1;
    size_t m = 0;
    uint32_t *composed = u32_normalize(UNINORM_NFC, decomposed, n, NULL, &m);
    if (!composed || m != 1 || composed[0] != s) return 2;
    free(decomposed); free(composed);
  }
  const uint8_t decomposed[] = {0x65,0xcc,0x81};
  const uint8_t expected[] = {0xc3,0xa9};
  size_t n = 0;
  uint8_t *result = u8_normalize(UNINORM_NFC, decomposed, sizeof decomposed, NULL, &n);
  if (!result || n != sizeof expected || memcmp(result, expected, n)) return 3;
  free(result);
  return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_UNISTRING") == "1",
                     "set KIKI_TEST_UNISTRING=1 on Linux")
class UnistringRuntimeTests(unittest.TestCase):
    def test_packaged_hangul_normalization(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-unistring-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["libunistring", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertFalse((root / "usr/lib/libunistring.la").exists())
            self.assertNotRegex(run(["readelf","-d",str(root / "usr/lib/libunistring.so.5")]),
                                r"\((?:RPATH|RUNPATH)\)")
            dirs = [root / p for p in ("usr/lib","usr/lib64","lib","lib64")]
            flags = ["cc", "--sysroot=" + str(root)]
            for path in dirs:
                flags += ["-B"+str(path)+"/", "-L"+str(path), "-Wl,-rpath-link,"+str(path)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"), "-lunistring", "-o", str(work / "probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str,dirs))]
            listing = run(loader + ["--list", str(work / "probe")])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            self.assertTrue({"libunistring.so.5", "libc.so.6"} <= resolved.keys())
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            run(loader + [str(work / "probe")])
            print("KIKI Unicode: 11172 Hangul NFD/NFC round trips and UTF-8 NFC passed")

if __name__ == "__main__":
    unittest.main()
