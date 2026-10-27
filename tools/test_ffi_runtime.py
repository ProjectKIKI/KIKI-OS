"""Opt-in KIKI libffi call and executable closure smoke test."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <ffi.h>
static double combine(int a, double b) { return a + b; }
static void callback(ffi_cif *cif, void *result, void **args, void *user) {
  (void)cif;
  *(double*)result = *(int*)args[0] + *(double*)args[1] + *(double*)user;
}
int main(void) {
  ffi_cif cif;
  ffi_type *types[] = {&ffi_type_sint, &ffi_type_double};
  if (ffi_prep_cif(&cif, FFI_DEFAULT_ABI, 2, &ffi_type_double, types) != FFI_OK) return 1;
  int a = 7; double b = 2.5, result = 0, extra = 1.25;
  void *args[] = {&a, &b};
  ffi_call(&cif, FFI_FN(combine), &result, args);
  if (result != 9.5) return 2;
  void *code = 0;
  ffi_closure *closure = ffi_closure_alloc(sizeof(ffi_closure), &code);
  if (!closure) return 3;
  if (ffi_prep_closure_loc(closure, &cif, callback, &extra, code) != FFI_OK) return 4;
  double (*function)(int, double) = (double (*)(int, double))code;
  result = function(a, b);
  ffi_closure_free(closure);
  return result == 10.75 ? 0 : 5;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_FFI") == "1",
                     "set KIKI_TEST_FFI=1 on Linux")
class FfiRuntimeTests(unittest.TestCase):
    def test_call_and_closure(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-ffi-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["libffi","linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertFalse((root / "usr/lib/libffi.la").exists())
            self.assertNotRegex(run(["readelf","-d",str(root / "usr/lib/libffi.so.8")]),
                                r"\((?:RPATH|RUNPATH)\)")
            dirs = [root / p for p in ("usr/lib","usr/lib64","lib","lib64")]
            flags = ["cc","--sysroot="+str(root)]
            for path in dirs:
                flags += ["-B"+str(path)+"/","-L"+str(path),"-Wl,-rpath-link,"+str(path)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"),"-lffi","-o",str(work / "probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]),"--inhibit-cache","--library-path",":".join(map(str,dirs))]
            listing = run(loader + ["--list",str(work / "probe")])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(",listing,re.MULTILINE))
            self.assertTrue({"libffi.so.8","libc.so.6"} <= resolved.keys())
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            run(loader + [str(work / "probe")])
            print("KIKI libffi: mixed int/double ffi_call and closure callback passed")

if __name__ == "__main__":
    unittest.main()
