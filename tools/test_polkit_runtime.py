"""Target loader/CLI smoke tests. Never start a daemon or request authorization."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_POLKIT") == "1",
                     "set KIKI_TEST_POLKIT=1 on Linux")
class PolkitRuntimeTests(unittest.TestCase):
    def test_tools_use_target_libraries(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-polkit-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["polkit"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            # Direct loader invocation does not activate setuid semantics.
            # Remove special bits from these disposable copies as defence in depth.
            for path in ("usr/bin/pkexec", "usr/lib/polkit-1/polkit-agent-helper-1"):
                (root / path).chmod(0o755)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, dirs))]
            environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                           "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + str(root / "nonexistent-bus")}
            def run(command):
                result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr
            tools = ("usr/bin/pkcheck", "usr/bin/pkaction", "usr/bin/pkexec", "usr/bin/pkttyagent")
            binaries = tools + ("usr/lib/polkit-1/polkitd", "usr/lib/polkit-1/polkit-agent-helper-1")
            for relative in binaries:
                with self.subTest(binary=relative):
                    binary = root / relative
                    listing = run(loader + ["--list", str(binary)])
                    resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
                    self.assertIn("libc.so.6", resolved)
                    for path in resolved.values():
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
                    self.assertNotRegex(run(["readelf", "-d", str(binary)]), r"RPATH|RUNPATH")
                    if relative in tools:
                        self.assertIn("127", run(loader + [str(binary), "--version"]))
            print("Polkit: 6 ELF dependency checks, 4 CLI versions passed; no live daemon/PAM approval tested")

if __name__ == "__main__":
    unittest.main()
