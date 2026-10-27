"""Root-only target sysusers/tmpfiles test; never change host accounts or start services."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_POLKIT_ACCOUNTS") == "1",
                     "set KIKI_TEST_POLKIT_ACCOUNTS=1 as Linux root")
class PolkitAccountTests(unittest.TestCase):
    def test_target_account_and_rules_permissions(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-polkit-accounts-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["polkit"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            paths = ":".join(str(root / p) for p in ("usr/lib", "usr/lib64", "lib", "lib64", "usr/lib/systemd"))
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", paths]
            def run(tool, config):
                result = subprocess.run(loader + [str(root / "usr/bin" / tool),
                                        "--root=" + str(root)] +
                                        (["--create"] if tool == "systemd-tmpfiles" else []) +
                                        [str(root / config)],
                                        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run("systemd-sysusers", "usr/lib/sysusers.d/polkit.conf")
            passwd = (root / "etc/passwd").read_text()
            group = (root / "etc/group").read_text()
            users = [line.split(":") for line in passwd.splitlines() if line.startswith("polkitd:")]
            groups = [line.split(":") for line in group.splitlines() if line.startswith("polkitd:")]
            self.assertEqual(len(users), 1)
            self.assertEqual(len(groups), 1)
            uid, gid = int(users[0][2]), int(users[0][3])
            self.assertNotEqual(uid, 0)
            self.assertNotEqual(gid, 0)
            self.assertEqual(gid, int(groups[0][2]))
            self.assertTrue(users[0][6].endswith("/nologin"))
            shadow = [line.split(":") for line in (root / "etc/shadow").read_text().splitlines()
                      if line.startswith("polkitd:")]
            self.assertEqual(len(shadow), 1)
            self.assertTrue(shadow[0][1].startswith(("!", "*")))
            rules = root / "etc/polkit-1/rules.d"
            # Exercise correction of overly permissive state, only in this fixture.
            rules.chmod(0o777)
            run("systemd-tmpfiles", "usr/lib/tmpfiles.d/polkit-tmpfiles.conf")
            info = rules.stat()
            self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (0, gid, 0o750))
            run("systemd-sysusers", "usr/lib/sysusers.d/polkit.conf")
            run("systemd-tmpfiles", "usr/lib/tmpfiles.d/polkit-tmpfiles.conf")
            self.assertEqual((root / "etc/passwd").read_text(), passwd)
            self.assertEqual((root / "etc/group").read_text(), group)
            self.assertEqual(rules.stat().st_gid, gid)
            print("Polkit target sysusers/tmpfiles: locked non-root account, rules permissions and idempotence passed")

if __name__ == "__main__":
    unittest.main()
