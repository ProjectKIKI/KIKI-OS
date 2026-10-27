"""Opt-in package-only GnuTLS trust/IDNA smoke test; no network or mounts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <gnutls/gnutls.h>
#include <stdio.h>
#include <string.h>
int main(void) {
  gnutls_certificate_credentials_t cred;
  gnutls_datum_t name = {0};
  if (gnutls_global_init() < 0) return 1;
  if (!gnutls_check_version("3.8.13")) return 2;
  if (gnutls_certificate_allocate_credentials(&cred) < 0) return 3;
  int count = gnutls_certificate_set_x509_system_trust(cred);
  if (count <= 0) return 4;
  const char *domain = "한국.한국";
  if (gnutls_idna_map(domain, strlen(domain), &name, 0) < 0) return 5;
  const char *expected = "xn--3e0b707e.xn--3e0b707e";
  if (name.size != strlen(expected) || memcmp(name.data, expected, name.size)) return 6;
  printf("trust-count=%d\n", count);
  gnutls_free(name.data);
  gnutls_certificate_free_credentials(cred);
  gnutls_global_deinit();
  return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_GNUTLS") == "1",
                     "set KIKI_TEST_GNUTLS=1 as Linux root")
class GnuTLSRuntimeTests(unittest.TestCase):
    def test_packaged_trust_and_idna(self):
        self.assertEqual(os.geteuid(), 0, "chroot requires Linux root")
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-gnutls-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["gnutls", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            for file in ("usr/lib/libgnutls.so.30", "usr/lib/libgnutlsxx.so.30",
                         "usr/bin/gnutls-cli", "usr/bin/certtool"):
                self.assertNotRegex(run(["readelf", "-d", str(root / file)]), r"\((?:RPATH|RUNPATH)\)")
            (root / "tmp").mkdir(exist_ok=True)
            source = root / "tmp/probe.c"
            source.write_text(PROBE, encoding="utf-8")
            flags = ["cc", "--sysroot="+str(root)]
            for path in ("usr/lib", "usr/lib64", "lib", "lib64"):
                flags += ["-B"+str(root / path)+"/", "-L"+str(root / path),
                          "-Wl,-rpath-link,"+str(root / path)]
            run(flags + [str(source), "-lgnutls", "-o", str(root / "tmp/probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = "/" + str(loaders[0].relative_to(root))
            command = ["chroot", str(root), loader, "--inhibit-cache", "--library-path",
                       "/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn("3.8.13", run(command + ["/usr/bin/gnutls-cli", "--version"]))
            self.assertIn("3.8.13", run(command + ["/usr/bin/certtool", "--version"]))
            count = (root / "etc/ssl/certs/ca-certificates.crt").read_bytes().count(b"-----BEGIN CERTIFICATE-----")
            self.assertGreater(count, 0)
            self.assertEqual(run(command + ["/tmp/probe"]).strip(), "trust-count="+str(count))
            print("KIKI GnuTLS: packaged CLI, %d system trust anchors and Korean IDNA passed" % count)

if __name__ == "__main__":
    unittest.main()
