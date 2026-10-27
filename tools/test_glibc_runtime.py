"""Opt-in C/thread smoke test using the packaged KIKI libc and loader."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


PROBE = r'''
#include <gnu/libc-version.h>
#include <pthread.h>
#include <stdio.h>
static void *worker(void *value) { *(int *)value = 42; return NULL; }
int main(void) {
    pthread_t thread;
    int value = 0;
    if (pthread_create(&thread, NULL, worker, &value)) return 1;
    if (pthread_join(thread, NULL)) return 2;
    printf("glibc=%s thread=%d\n", gnu_get_libc_version(), value);
    return value == 42 ? 0 : 3;
}
'''


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_GLIBC_RUNTIME") == "1",
                     "set KIKI_TEST_GLIBC_RUNTIME=1 on Linux after building glibc")
class GlibcRuntimeTests(unittest.TestCase):
    def test_packaged_loader_libc_and_threads_without_host_libraries(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-glibc-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ("linux-headers", "glibc"):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1, str(loaders))
            directories = [root / path for path in ("usr/lib", "usr/lib64", "lib", "lib64")]

            def run(command):
                result = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            source = work / "probe.c"
            source.write_text(PROBE)
            flags = ["cc", "--sysroot=" + str(root), "-pthread"]
            for directory in directories:
                flags += ["-B" + str(directory) + "/", "-L" + str(directory), "-Wl,-rpath-link," + str(directory)]
            probe = work / "probe"
            run(flags + [str(source), "-o", str(probe)])
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, directories))]
            listing = run(loader + ["--list", str(probe)])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            self.assertIn("libc.so.6", resolved, listing)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            dynamic = run(["readelf", "-d", resolved["libc.so.6"]])
            self.assertNotIn("libselinux", dynamic)
            self.assertNotRegex(dynamic, r"\((?:RPATH|RUNPATH)\)")
            output = run(loader + [str(probe)])
            self.assertEqual(output.strip(), f"glibc={recipes['glibc'].version} thread=42")
            print("KIKI packaged glibc: loader, C runtime and pthread smoke passed")


if __name__ == "__main__":
    unittest.main()
