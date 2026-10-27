"""Actual packaged Python/ki2ctl/hooks inside a disposable chroot."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_TARGET_HOOKS") == "1",
                     "set KIKI_TEST_TARGET_HOOKS=1 as Linux root")
class TargetHookTests(unittest.TestCase):
    def test_info_hook_apply_failure_retry(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-target-hooks-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["ki2ctl"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            (root / "dev").mkdir(exist_ok=True)
            (root / "dev/null").write_bytes(b"")  # I/O fixture only, no mounted devices.
            def run(arguments, success=True):
                result = subprocess.run(["chroot", str(root)] + arguments,
                                        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=30)
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr
            run(["/sbin/ldconfig", "/usr/lib", "/usr/lib64", "/lib", "/lib64"])
            cli = ["/usr/bin/python3.12", "-B", "/usr/bin/ki2ctl"]
            self.assertIn("ki2ctl", run(cli + ["--version"]))
            docs = root / "usr/share/info"
            docs.mkdir(parents=True, exist_ok=True)
            for name in ("first", "second"):
                (docs / (name + ".info")).write_text(
                    "INFO-DIR-SECTION Test\nSTART-INFO-DIR-ENTRY\n"
                    f"* {name}: ({name}). Test.\nEND-INFO-DIR-ENTRY\n"
                    f"\x1f\nFile: {name}.info, Node: Top\nTest.\n")
            queue = root / "var/lib/ki2/pending-hooks.json"
            queue.parent.mkdir(parents=True, exist_ok=True)
            pending = {"schema": "ki2-pending-hooks-v1", "hooks": [
                {"action": "info-index-rebuild", "package": "fixture", "phase": "post-install",
                 "status": "pending", "created_at": "2026-09-09T00:00:00+00:00"}]}
            queue.write_text(json.dumps(pending))
            before = queue.read_bytes()
            run(cli + ["hooks", "apply", "--dry-run"])
            self.assertEqual(queue.read_bytes(), before)
            run(cli + ["hooks", "apply"])
            self.assertEqual(json.loads(queue.read_text())["hooks"][0]["status"], "applied")
            index = docs / "dir"
            for name in ("first", "second"):
                self.assertIn("* " + name + ":", index.read_text())
            before_index = index.read_bytes()
            queue.write_text(json.dumps(pending))
            tool = root / "usr/bin/install-info"
            hidden = root / "usr/bin/install-info.test-hidden"
            tool.rename(hidden)
            try:
                self.assertIn("missing command", run(cli + ["hooks", "apply"], success=False))
                self.assertEqual(json.loads(queue.read_text())["hooks"][0]["status"], "failed")
                self.assertEqual(index.read_bytes(), before_index)
            finally:
                hidden.rename(tool)
            run(cli + ["hooks", "apply"])
            hook = json.loads(queue.read_text())["hooks"][0]
            self.assertEqual(hook["status"], "applied")
            self.assertNotIn("last_error", hook)
            self.assertEqual(index.read_bytes(), before_index)
            print("Target Python/ki2ctl: dry-run, real Info apply, missing-tool failure and retry passed")

if __name__ == "__main__":
    unittest.main()
