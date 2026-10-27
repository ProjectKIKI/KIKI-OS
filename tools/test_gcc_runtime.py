"""Opt-in shared C++ exception test using packaged KIKI runtimes, not host ones."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


LIBRARY = r'''
#include <stdexcept>
struct Guard { int *count; ~Guard() { ++*count; } };
extern "C" void raise_from_library(int *count) {
    Guard guard{count};
    throw std::runtime_error("KIKI shared exception");
}
extern "C" int catch_in_library(void (*callback)()) {
    try { callback(); } catch (const std::runtime_error &error) {
        return error.what()[0] == 'K' ? 42 : 1;
    }
    return 2;
}
'''

CLIENT = r'''
#include <stdexcept>
#include <cstring>
extern "C" void raise_from_library(int *);
extern "C" int catch_in_library(void (*)());
void callback() { throw std::runtime_error("KIKI reverse exception"); }
int main() {
    int destroyed = 0;
    try { raise_from_library(&destroyed); return 1; }
    catch (const std::runtime_error &error) {
        if (std::strcmp(error.what(), "KIKI shared exception")) return 2;
    }
    if (destroyed != 1) return 3;
    return catch_in_library(callback) == 42 ? 0 : 4;
}
'''


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_GCC_RUNTIME") == "1",
                     "set KIKI_TEST_GCC_RUNTIME=1 on Linux after building libgcc")
class GccRuntimeTests(unittest.TestCase):
    def test_exceptions_cross_shared_library_boundary_both_directions(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        # The probe is compiled here: glibc headers also need Linux UAPI headers.
        ordered = ki2build.dependency_closure(recipes, ["libgcc", "libstdcxx", "linux-headers"],
                                              "x86_64", include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix="kiki-gcc-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ordered:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1, str(loaders))
            directories = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}

            def run(command):
                result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            flags = ["g++", "-std=c++11", "--sysroot=" + str(root), "-shared-libgcc"]
            for directory in directories:
                flags += ["-B" + str(directory) + "/", "-L" + str(directory),
                          "-Wl,-rpath-link," + str(directory)]
            (work / "library.cc").write_text(LIBRARY)
            (work / "client.cc").write_text(CLIENT)
            run(flags + ["-shared", "-fPIC", str(work / "library.cc"),
                         "-Wl,-soname,libkiki-exception-probe.so", "-o", str(work / "libkiki-exception-probe.so")])
            run(flags + [str(work / "client.cc"), "-L" + str(work),
                         "-lkiki-exception-probe", "-o", str(work / "probe")])
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path",
                      ":".join(map(str, [work] + directories))]
            listing = run(loader + ["--list", str(work / "probe")])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            for soname in ("libstdc++.so.6", "libgcc_s.so.1", "libc.so.6"):
                self.assertIn(soname, resolved, listing)
                self.assertTrue(Path(resolved[soname]).resolve().is_relative_to(root), listing)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(work), listing)
            run(loader + [str(work / "probe")])
            print("KIKI packaged C++ runtime: bidirectional exceptions and RAII passed")


if __name__ == "__main__":
    unittest.main()
