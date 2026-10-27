"""Opt-in PAM dispatch test with temporary policies, never system pam.d."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
#include <security/pam_appl.h>
#include <string.h>
static int conversation(int n, const struct pam_message **m,
                        struct pam_response **r, void *d) {
  (void)n; (void)m; (void)r; (void)d;
  return PAM_CONV_ERR;
}
int main(int argc, char **argv) {
  if (argc != 3) return 1;
  struct pam_conv conv = {conversation, 0};
  pam_handle_t *handle = 0;
  if (pam_start_confdir(argv[2], "synthetic-test", &conv, argv[1], &handle) != PAM_SUCCESS) return 2;
  int rc = pam_authenticate(handle, 0);
  int ok = strcmp(argv[2], "allow") == 0 ? rc == PAM_SUCCESS : rc != PAM_SUCCESS;
  if (pam_end(handle, rc) != PAM_SUCCESS) return 3;
  return ok ? 0 : 4;
}
'''

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PAM") == "1",
                     "set KIKI_TEST_PAM=1 on Linux")
class PamRuntimeTests(unittest.TestCase):
    def test_isolated_allow_deny_policies(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-pam-runtime-") as tmp:
            work = Path(tmp); root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["linux-pam", "linux-headers"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            flags = ["cc", "--sysroot="+str(root)]
            dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            for p in dirs:
                flags += ["-B"+str(p)+"/", "-L"+str(p), "-Wl,-rpath-link,"+str(p)]
            source = work / "probe.c"; source.write_text(PROBE)
            binary = work / "probe"
            run(flags + [str(source), "-lpam", "-o", str(binary)])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, dirs))]
            listing = run(loader + ["--list", str(binary)])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            self.assertIn("libpam.so.0", resolved)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            policies = work / "policies"; policies.mkdir()
            for service, module in (("allow", "pam_permit.so"), ("deny", "pam_deny.so"), ("missing", "missing.so")):
                module_path = root / "usr/lib/security" / module
                (policies / service).write_text("auth required " + str(module_path) + "\n")
                run(loader + [str(binary), str(policies), service])
            print("KIKI PAM: explicit temporary allow/deny/missing-module policies passed; not password/login validation")

if __name__ == "__main__":
    unittest.main()
