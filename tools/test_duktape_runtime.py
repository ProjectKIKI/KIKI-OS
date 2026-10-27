"""Opt-in target-library JavaScript smoke test, not a Polkit policy test."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
#include <duktape.h>
#include <string.h>
int main(void) {
    duk_context *ctx = duk_create_heap_default();
    if (!ctx) return 1;
    if (duk_peval_string(ctx, "JSON.stringify({allowed: [1,2,3].indexOf(2)>=0, n:Math.sqrt(81)})")) return 2;
    if (strcmp(duk_get_string(ctx, -1), "{\"allowed\":true,\"n\":9}")) return 3;
    duk_pop(ctx);
    if (duk_peval_string(ctx, "'\\uD55C\\uAE00'.length === 2") || !duk_get_boolean(ctx, -1)) return 4;
    duk_pop(ctx);
    if (!duk_peval_string(ctx, "throw new Error('expected')")) return 5;
    duk_pop(ctx);
    if (!duk_peval_string(ctx, "function (")) return 6;
    duk_pop(ctx);
    if (duk_peval_string(ctx, "6 * 7") || duk_get_int(ctx, -1) != 42) return 7;
    duk_destroy_heap(ctx);
    return 0;
}
'''

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_DUKTAPE") == "1",
                     "set KIKI_TEST_DUKTAPE=1 on Linux")
class DuktapeRuntimeTests(unittest.TestCase):
    def test_target_engine_and_error_recovery(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-duktape-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["duktape", "linux-headers"],
                                                   "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            flags = ["cc", "--sysroot=" + str(root), "-Wall", "-Wextra", "-Werror"]
            for p in dirs:
                flags += ["-B" + str(p) + "/", "-L" + str(p), "-Wl,-rpath-link," + str(p)]
            source = work / "probe.c"
            source.write_text(PROBE)
            binary = work / "probe"
            run(flags + [str(source), "-lduktape", "-lm", "-o", str(binary)])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, dirs))]
            listing = run(loader + ["--list", str(binary)])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            self.assertIn("libduktape.so.207", resolved)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            dynamic = run(["readelf", "-d", str(root / "usr/lib/libduktape.so.207")])
            self.assertNotRegex(dynamic, r"RPATH|RUNPATH")
            run(loader + [str(binary)])
            print("KIKI Duktape: JSON/math/Unicode/error recovery passed; Polkit integration not tested")

if __name__ == "__main__":
    unittest.main()
