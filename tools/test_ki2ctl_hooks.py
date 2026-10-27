import argparse
import os
import io
import tarfile
import importlib.machinery
import importlib.util
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/ki2ctl/usr/bin/ki2ctl"
SCRIPT = Path(os.environ.get("KIKI_TEST_KI2CTL_SCRIPT", str(SCRIPT))).resolve()
loader = importlib.machinery.SourceFileLoader("ki2ctl_hooks_test", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
ctl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ctl
loader.exec_module(ctl)


class HookTests(unittest.TestCase):
    def test_generated_info_index_is_not_owned_or_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            directory = root / "usr/share/info"
            directory.mkdir(parents=True)
            index = directory / "dir"
            index.write_text("existing shared index")
            packages = []
            for name in ("first", "second"):
                package = Path(tmp) / (name + ".ki2")
                with tarfile.open(package, "w:gz") as archive:
                    for relative, data in (("usr/share/info/dir", b"package-local index"),
                                           ("usr/share/info/" + name + ".info", b"manual")):
                        member = tarfile.TarInfo("rootfs/" + relative)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
                packages.append((ctl.Repo(name="test", url="test"), {"name": name}, package))
                entries = ctl.package_payload_entries(package)
                self.assertNotIn(ctl.GENERATED_INFO_INDEX, [e["path"] for e in entries])
            db = {"packages": {"legacy": {"files": [ctl.GENERATED_INFO_INDEX]}}}
            self.assertNotIn(ctl.GENERATED_INFO_INDEX, ctl.file_owner_sets(db))
            self.assertEqual(ctl.detect_file_conflicts(root, db, packages), [])
            for _, _, package in packages:
                files = ctl.extract_package(package, root)
                self.assertNotIn(ctl.GENERATED_INFO_INDEX, files)
                self.assertIn("info-index-rebuild", ctl.detect_post_install_hooks(files))
            self.assertEqual(index.read_text(), "existing shared index")

    def test_info_hook_detection_and_deferral(self):
        self.assertEqual(ctl.detect_post_install_hooks(
            ["/usr/share/info/one.info.gz", "/usr/share/info/dir"]), ["info-index-rebuild"])
        self.assertEqual(ctl.detect_post_install_hooks(["/usr/share/info/README"]), [])
        with patch.object(ctl, "rebuild_info_index") as rebuild:
            self.assertFalse(ctl.run_hook_action("info-index-rebuild", Path("/offline"), False))
            self.assertFalse(ctl.run_hook_action("info-index-rebuild", Path("/"), True))
            rebuild.assert_not_called()
            self.assertTrue(ctl.run_hook_action("info-index-rebuild", Path("/"), False))
            rebuild.assert_called_once_with(Path("/"))

    @unittest.skipUnless(shutil.which("install-info"), "requires GNU install-info")
    def test_info_install_remove_and_missing_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "usr/share/info"
            directory.mkdir(parents=True)
            for name in ("first", "second"):
                (directory / (name + ".info")).write_text(
                    "INFO-DIR-SECTION Tests\nSTART-INFO-DIR-ENTRY\n"
                    f"* {name}: ({name}). Test.\nEND-INFO-DIR-ENTRY\n"
                    f"\x1f\nFile: {name}.info, Node: Top\nTest.\n")
            ctl.rebuild_info_index(root)
            before = (directory / "dir").read_bytes()
            self.assertIn(b"* first:", before)
            self.assertIn(b"* second:", before)
            with patch.object(ctl.shutil, "which", return_value=None):
                with self.assertRaises(ctl.Ki2CtlError):
                    ctl.rebuild_info_index(root)
            self.assertEqual((directory / "dir").read_bytes(), before)
            (directory / "first.info").unlink()
            ctl.rebuild_info_index(root)
            self.assertNotIn(b"* first:", (directory / "dir").read_bytes())
            self.assertIn(b"* second:", (directory / "dir").read_bytes())
            (directory / "second.info").unlink()
            ctl.rebuild_info_index(root)
            self.assertNotIn(b"* second:", (directory / "dir").read_bytes())

    def test_schema_hooks_requeue_after_application(self):
        files = ["/usr/share/glib-2.0/schemas/test.gschema.xml"]
        self.assertEqual(ctl.detect_post_install_hooks(files), ["glib-compile-schemas"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctl.record_pending_hooks(root, "schemas", files)
            ctl.record_pending_hooks(root, "schemas", files)
            data = ctl.load_pending_hooks(root)
            self.assertEqual(len(data["hooks"]), 1)
            data["hooks"][0]["status"] = "applied"
            ctl.save_pending_hooks(root, data)
            ctl.record_pending_hooks(root, "schemas", files)
            data = ctl.load_pending_hooks(root)
            self.assertEqual([h["status"] for h in data["hooks"]], ["applied", "pending"])
            ctl.record_pending_hooks(root, "schemas", files, phase="post-remove")
            self.assertEqual(ctl.load_pending_hooks(root)["hooks"][-1]["phase"], "post-remove")

    def test_command_failure_and_missing_tool_are_not_success(self):
        with patch.object(ctl.shutil, "which", return_value=None):
            with self.assertRaises(ctl.Ki2CtlError):
                ctl.run_hook_action("glib-compile-schemas", Path("/"), False)
        with patch.object(ctl.shutil, "which", return_value="/fake/compiler"), patch.object(ctl.subprocess, "run") as run:
            run.side_effect = subprocess.CalledProcessError(1, "compiler")
            with self.assertRaises(ctl.Ki2CtlError):
                ctl.run_hook_action("glib-compile-schemas", Path("/"), False)
            run.side_effect = None
            self.assertTrue(ctl.run_hook_action("glib-compile-schemas", Path("/"), False))
            self.assertTrue(run.call_args.kwargs["check"])
            run.reset_mock()
            self.assertFalse(ctl.run_hook_action("glib-compile-schemas", Path("/offline"), False))
            self.assertFalse(ctl.run_hook_action("glib-compile-schemas", Path("/"), True))
            run.assert_not_called()

    def test_failed_hook_persists_and_retry_can_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctl.record_pending_hooks(root, "schemas", ["/usr/share/glib-2.0/schemas/test.xml"])
            args = argparse.Namespace(root=root, dry_run=False)
            with patch.object(ctl, "run_hook_action", side_effect=ctl.Ki2CtlError("injected failure")):
                with self.assertRaises(ctl.Ki2CtlError):
                    ctl.command_hooks_apply(args)
            self.assertEqual(ctl.load_pending_hooks(root)["hooks"][0]["status"], "failed")
            with patch.object(ctl, "run_hook_action", return_value=True):
                ctl.command_hooks_apply(args)
            item = ctl.load_pending_hooks(root)["hooks"][0]
            self.assertEqual(item["status"], "applied")
            self.assertNotIn("last_error", item)


if __name__ == "__main__":
    unittest.main()
