import base64
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import tarfile
import io
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kiki_admin_backend", ROOT / "distro/sources/kiki-admin/usr/libexec/kiki-admin-backend.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)
KI2 = ROOT / "distro/sources/ki2ctl/usr/bin/ki2ctl"


class AdminTests(unittest.TestCase):
    def test_security_scan_requires_installed_content_and_fixed_target(self):
        with self.assertRaisesRegex(admin.AdminError,'security-audit'):self.backend.operation('security-scan')
        self.write('usr/libexec/kiki-security-scan',{})
        self.assertEqual(self.backend.operation('security-scan')[0],['/usr/libexec/kiki-security-scan'])
        with self.assertRaises(admin.AdminError):self.backend.operation('security-scan','/tmp/untrusted.xml')
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = admin.Backend(self.root, KI2)
        self.write("usr/share/ki2/package-groups.json", dict(schema="ki2-package-groups-v1", groups=[
            dict(id="desktop", name_ko="데스크톱", description_ko="GNOME 환경", requires=[],
                 packages=dict(mandatory=["shell"], default=["files"], optional=[]), services=dict(enable=[])),
            dict(id="internal", selectable=False, requires=[], packages=dict(mandatory=[], default=[], optional=[]))]))
        self.write("var/lib/ki2/installed.json", dict(schema="ki2-installed-v1", packages={
            "shell": dict(name="shell", version="1.9", release="1", package="shell-1.9-1.ki2")}, groups={}))
        self.write("etc/ki2/repos.d/main.repo", dict(name="main", url="https://packages.example.test/stable"))
        self.write("var/lib/ki2/repos/main/index." + platform.machine() + ".json", dict(repo_name="main", packages=[
            dict(name="shell", version="1.10", release="1", file="shell-1.10-1.ki2", dependencies=dict(runtime=[])),
            dict(name="files", version="2", release="1", file="files-2-1.ki2", dependencies=dict(runtime=["shell"]))]))

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_snapshot_uses_ki2_version_order_and_partial_group_state(self):
        result = self.backend.packages()
        self.assertEqual(result["updates"], 1)
        self.assertEqual(result["installed"][0]["available"], "1.10-1")
        self.assertEqual(len(result["groups"]), 1)
        self.assertFalse(result["groups"][0]["installed"])
        self.assertEqual((result["groups"][0]["present"], result["groups"][0]["total"]), (1, 2))
        self.assertTrue(result["groups"][0]["available"])
        self.assertFalse(result["repos"][0]["signed"])

    def test_planning_is_read_only_and_uses_dependency_closure(self):
        before = self.files()
        plan = self.backend.plan("group-install", "desktop")
        self.assertIn("files 2-1", plan["details"])
        self.assertIn("shell 1.10-1", plan["details"])
        self.assertEqual(before, self.files())
        self.assertEqual(plan, self.backend.plan("group-install", "desktop"))

    def test_stale_plan_changes_when_repository_or_installed_state_changes(self):
        original = self.backend.plan("upgrade")["token"]
        self.write("etc/ki2/repos.d/extra.repo", dict(name="extra", url="https://other.example.test"))
        self.assertNotEqual(original, self.backend.plan("upgrade")["token"])

    def test_dry_run_hooks_excludes_already_applied(self):
        self.write("var/lib/ki2/pending-hooks.json", dict(hooks=[
            dict(action="ldconfig", status="applied"), dict(action="glib-compile-schemas", status="pending")]))
        before = self.files()
        self.assertEqual(len(self.backend.packages()["hooks"]), 1)
        plan = self.backend.plan("hooks")
        self.assertIn("glib-compile-schemas", plan["details"])
        self.assertNotIn("ldconfig", plan["details"])
        self.assertEqual(before, self.files())

    def test_refresh_requires_repositories_and_signing_key(self):
        with self.assertRaisesRegex(admin.AdminError, "공개키"):
            self.backend.plan("refresh")
        path = self.root / "etc/ki2/trust/main.ed25519.pub"
        path.parent.mkdir(parents=True)
        path.write_text(base64.b64encode(bytes(range(32))).decode())
        self.assertIn("--require-signature", self.backend.plan("refresh")["details"])

    def test_service_repair_only_for_current_failed_unit(self):
        with patch.object(self.backend, "failed", return_value=([dict(unit="test.service")], "")):
            self.assertIn("test.service", self.backend.plan("restart", "test.service")["details"])
            for value in ["healthy.service", "../test.service", "--all", "test.service;reboot", "test.socket"]:
                with self.assertRaises(admin.AdminError):
                    self.backend.plan("restart", value)

    def test_arbitrary_commands_and_non_system_apply_are_rejected(self):
        for value in ["shell", "reboot", "remove", "exec"]:
            with self.assertRaises(admin.AdminError):
                self.backend.plan(value, "echo dangerous")
        with self.assertRaisesRegex(admin.AdminError, "관리자"):
            self.backend.apply("upgrade", "", "0" * 64)
        with self.assertRaises(admin.AdminError):
            self.backend.plan("group-install", "--root=/tmp")
        with self.assertRaises(admin.AdminError):
            self.backend.plan("group-install", "internal")

    def test_repository_registration_rejects_password_urls_and_untrusted_keys(self):
        for url in ["http://packages.example.test", "https://user:secret@example.test", "file:///tmp/repo", "https://example.test/?token=x"]:
            with self.assertRaises(admin.AdminError):
                self.backend.plan("repo-set", json.dumps(dict(name="test", url=url, key="/etc/ki2/trust/main.pub")))
        with self.assertRaises(admin.AdminError):
            self.backend.plan("repo-set", json.dumps(dict(name="../oops", url="https://example.test", key="/tmp/key")))
        with self.assertRaises(admin.AdminError):
            self.backend.plan("repo-set", json.dumps(dict(name="test", url="https://example.test", key="/tmp/key")))

    @unittest.skipUnless(os.name == "posix", "Linux KI2 filesystem lock")
    def test_cli_writer_cannot_race_with_administrator(self):
        with self.backend.ki2.mutation_lock(self.root):
            proc = subprocess.run([sys.executable, str(KI2), "--root", str(self.root), "repo", "set", "https://new.example.test", "--name", "new"], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("another KI2 operation", proc.stderr)
        self.assertFalse((self.root / "etc/ki2/repos.d/new.repo").exists())

    def test_journal_scope_is_bounded_and_argument_safe(self):
        with patch.object(admin, "command", return_value=dict(code=0, stdout="log", stderr="limited access")) as run:
            result = self.backend.logs("test.service")
        self.assertIn("--lines=200", run.call_args.args[0])
        self.assertIn("--unit=test.service", run.call_args.args[0])
        self.assertEqual(result["notice"], "limited access")
        with self.assertRaises(admin.AdminError):
            self.backend.logs("--directory=/root")
        self.assertIn("--lines=200", self.backend.plan("system-logs", "test.service")["details"])
        with self.assertRaises(admin.AdminError):
            self.backend.plan("system-logs", "--directory=/root")

    def test_group_without_repository_payload_is_marked_unavailable(self):
        self.write("var/lib/ki2/repos/main/index." + platform.machine() + ".json", dict(repo_name="main", packages=[]))
        group = self.backend.packages()["groups"][0]
        self.assertFalse(group["available"])
        self.assertIn("현재 저장소", group["unavailable_reason"])

    def test_diagnosis_distinguishes_unknown_from_healthy(self):
        snapshot = dict(observed_at="now", disks=[dict(mount="/", total=100, free=5)], failed=[dict(unit="broken.service")], repos=[], cached=False, hooks=[], warnings=["cannot read service state"])
        with patch.object(self.backend, "snapshot", return_value=snapshot):
            result = self.backend.diagnose()
        self.assertGreaterEqual(len(result["issues"]), 3)
        self.assertTrue(result["warnings"])
        self.assertNotIn("발견한 문제가 없습니다", result["summary"])

    def test_installer_directory_ownership_does_not_block_new_packages(self):
        k = self.backend.ki2
        (self.root / "usr/bin").mkdir(parents=True)
        package = self.root / "fixture.ki2"
        with tarfile.open(package, "w:gz") as archive:
            for path in ["rootfs/usr", "rootfs/usr/bin"]:
                info = tarfile.TarInfo(path); info.type = tarfile.DIRTYPE
                archive.addfile(info)
            item = tarfile.TarInfo("rootfs/usr/bin/new-app"); item.size = 3
            archive.addfile(item, io.BytesIO(b"new"))
        db = dict(packages={"base": dict(files=["/usr", "/usr/bin"])})
        plan = [(k.Repo("test", "file:///fixture"), dict(name="new-app"), package)]
        self.assertEqual(k.detect_file_conflicts(self.root, db, plan), [])
        (self.root / "usr/bin/new-app").write_text("existing")
        db["packages"]["base"]["files"].append("/usr/bin/new-app")
        self.assertTrue(k.detect_file_conflicts(self.root, db, plan))


if __name__ == "__main__":
    unittest.main()
