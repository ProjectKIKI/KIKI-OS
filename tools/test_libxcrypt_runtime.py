"""Opt-in test of the packaged password hashing library and ABI-2 alias."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ki2build


PROBE = r'''
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    void *library = dlopen("libcrypt.so.2", RTLD_NOW);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    void *symbol = dlsym(library, "crypt");
    if (!symbol) return 2;
    char *(*hash)(const char *, const char *) = symbol;
    const char *result = hash("kiki-runtime-probe", "$6$kiki$");
    if (!result || strncmp(result, "$6$kiki$", 8)) return 3;
    Dl_info info;
    if (!dladdr(symbol, &info)) return 4;
    printf("library=%s\nSHA512 crypt: OK\n", info.dli_fname);
    return 0;
}
'''


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_LIBXCRYPT_RUNTIME") == "1",
                     "set KIKI_TEST_LIBXCRYPT_RUNTIME=1 after building libxcrypt")
class LibxcryptRuntimeTests(unittest.TestCase):
    def test_abi_alias_loads_packaged_library_and_hashes(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-libxcrypt-runtime-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ("linux-headers", "glibc", "libxcrypt"):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            alias = root / "usr/lib/libcrypt.so.2"
            self.assertTrue(alias.is_symlink(), str(alias))
            self.assertTrue(alias.resolve(strict=True).is_relative_to(root))
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            directories = [root / path for path in ("usr/lib", "usr/lib64", "lib", "lib64")]

            def run(command):
                result = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            source, binary = work / "probe.c", work / "probe"
            source.write_text(PROBE)
            flags = ["cc", "--sysroot=" + str(root)]
            for directory in directories:
                flags += ["-B" + str(directory) + "/", "-L" + str(directory), "-Wl,-rpath-link," + str(directory)]
            run(flags + [str(source), "-ldl", "-o", str(binary)])
            output = run([str(loaders[0]), "--inhibit-cache", "--library-path",
                          ":".join(map(str, directories)), str(binary)])
            library_line = next(line for line in output.splitlines() if line.startswith("library="))
            self.assertTrue(Path(library_line.split("=", 1)[1]).resolve().is_relative_to(root), output)
            self.assertIn("SHA512 crypt: OK", output)
            print("KIKI packaged libxcrypt: ABI-2 alias and SHA512 hashing passed")


if __name__ == "__main__":
    unittest.main()
