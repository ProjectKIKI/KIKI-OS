"""Opt-in internationalized domain conversion through packaged KIKI libidn2."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <idn2.h>
#include <string.h>
int main(int argc, char **argv) {
  if (argc != 3) return 1;
  uint8_t *ascii = NULL;
  char *unicode = NULL;
  if (idn2_lookup_u8((const uint8_t*)argv[1], &ascii,
                    IDN2_NONTRANSITIONAL | IDN2_USE_STD3_ASCII_RULES)) return 2;
  if (strcmp((const char*)ascii, argv[2])) return 3;
  if (idn2_to_unicode_8z8z((const char*)ascii, &unicode, 0)) return 4;
  if (strcmp(unicode, argv[1])) return 5;
  idn2_free(ascii); idn2_free(unicode);
  ascii = NULL;
  int invalid = idn2_lookup_u8((const uint8_t*)"-invalid.example", &ascii,
                             IDN2_NONTRANSITIONAL | IDN2_USE_STD3_ASCII_RULES);
  idn2_free(ascii);
  return invalid == IDN2_OK ? 6 : 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_IDN2") == "1",
                     "set KIKI_TEST_IDN2=1 on Linux")
class Idn2RuntimeTests(unittest.TestCase):
    def test_domains_with_packaged_libraries(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-idn2-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["libidn2","linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            for file in ("usr/lib/libidn2.so.0","usr/bin/idn2"):
                self.assertNotRegex(run(["readelf","-d",str(root / file)]), r"\((?:RPATH|RUNPATH)\)")
            dirs = [root / p for p in ("usr/lib","usr/lib64","lib","lib64")]
            flags = ["cc","--sysroot="+str(root)]
            for path in dirs:
                flags += ["-B"+str(path)+"/","-L"+str(path),"-Wl,-rpath-link,"+str(path)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"),"-lidn2","-o",str(work / "probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]),"--inhibit-cache","--library-path",":".join(map(str,dirs))]
            listing = run(loader + ["--list",str(work / "probe")])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(",listing,re.MULTILINE))
            self.assertTrue({"libidn2.so.0","libunistring.so.5","libc.so.6"} <= resolved.keys())
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            for domain in ("한국.한국","한글.example","서울.example","bücher.example"):
                expected = ".".join("xn--"+label.encode("punycode").decode("ascii")
                                    if not label.isascii() else label for label in domain.split("."))
                run(loader + [str(work / "probe"),domain,expected])
            print("KIKI IDN2: 4 domain round trips and invalid leading-hyphen rejection passed")

if __name__ == "__main__":
    unittest.main()
