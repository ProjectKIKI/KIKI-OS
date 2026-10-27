from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kiki_console


class KikiConsoleTests(unittest.TestCase):
    def test_shell_filters_defaults_for_status_and_preserves_explicit_jobs(self):
        base = ["--repo-root", "/repo", "--arch", "x86_64", "--jobs", "8", "--build-plan", "plan.yaml"]
        with mock.patch.object(kiki_console, "command_status", return_value=0) as status:
            self.assertEqual(kiki_console.shell_dispatch("status --json", base), 0)
            self.assertTrue(status.call_args.args[0].json)
        with mock.patch.object(kiki_console, "command_plan", return_value=0) as plan:
            self.assertEqual(kiki_console.shell_dispatch("plan --jobs 3", base), 0)
            self.assertEqual(plan.call_args.args[0].jobs, 3)

    def test_build_jobs_forward_json_and_artifact_root(self):
        args = kiki_console.build_parser().parse_args(["jobs", "--artifact-root", "build/custom", "--json"])
        with mock.patch.object(kiki_console, "execute", return_value=0) as execute:
            kiki_console.command_build_jobs(args)
        command = execute.call_args.args[0]
        self.assertIn("list-jobs", command)
        self.assertIn("--json", command)
        self.assertIn(str(Path("build/custom")), command)
        self.assertFalse(execute.call_args.kwargs["announce"])

    def test_status_combines_stage_progress_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs/kiki-stage3-v3-plan.ko.md").write_text("- [x] 완료\n- [ ] 대기\n", encoding="utf-8")
            package_dir = root / "dist/ki2/packages/x86_64"
            package_dir.mkdir(parents=True)
            (package_dir / "demo.ki2").write_bytes(b"package")
            (root / "dist/ki2/repo").mkdir(parents=True)
            (root / "dist/ki2/repo/index.x86_64.json").write_text("{}\n", encoding="utf-8")
            (root / "distro/build-plans").mkdir(parents=True)
            (root / kiki_console.DEFAULT_PLAN).write_text("schema: test\n", encoding="utf-8")
            fake_git = {"branch": "feature", "upstream": "origin/feature", "ahead": 2, "behind": 0, "clean": False, "changed_files": 3}

            with mock.patch.object(kiki_console, "git_snapshot", return_value=fake_git):
                status = kiki_console.collect_status(root, "x86_64")

            self.assertEqual(status["stage3"], {"done": 1, "pending": 1, "total": 2})
            self.assertEqual(status["artifacts"]["packages"], 1)
            self.assertTrue(status["artifacts"]["repository_index"])
            self.assertTrue(status["default_plan_exists"])

    def test_artifact_snapshot_reads_recent_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / ".ki2osbuild/run-1/manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"status": "succeeded", "plan": "stage3-server-core"}), encoding="utf-8")

            artifacts = kiki_console.artifact_snapshot(root, "x86_64")

            self.assertEqual(artifacts["recent_run"]["status"], "succeeded")
            self.assertEqual(artifacts["recent_run"]["plan"], "stage3-server-core")

    def test_build_command_excludes_iso_and_iso_command_includes_it(self):
        parser = kiki_console.build_parser()
        build_args = parser.parse_args(["build", "--repo-root", "/repo", "--jobs", "4", "--dry-run", "--build-dir", "/tmp/work", "--rootfs-dir", "/tmp/rootfs"])
        iso_args = parser.parse_args(["iso", "--repo-root", "/repo", "--jobs", "4", "--yes"])

        build = kiki_console.osbuild_command(build_args, "run")
        iso = kiki_console.osbuild_command(iso_args, "run", include_iso=True)

        self.assertNotIn("--iso", build)
        self.assertIn("--dry-run", build)
        self.assertIn("--build-dir", build)
        self.assertIn(str(Path("/tmp/work")), build)
        self.assertIn("--rootfs-dir", build)
        self.assertIn(str(Path("/tmp/rootfs")), build)
        self.assertIn("--iso", iso)

    def test_noninteractive_iso_requires_explicit_yes(self):
        args = kiki_console.build_parser().parse_args(["iso", "--repo-root", "/repo"])
        with mock.patch.object(kiki_console.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(kiki_console.ConsoleError, "--yes"):
                kiki_console.command_iso(args)

    def test_iso_tool_is_warning_for_preflight_and_failure_for_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.yaml"
            plan.write_text("schema: test\n", encoding="utf-8")
            passed = kiki_console.Check("명령", "pass", "통과")
            with (
                mock.patch.object(kiki_console, "REQUIRED_TOOLS", ()),
                mock.patch.object(kiki_console, "ISO_TOOL_GROUPS", (("missing-tool",),)),
                mock.patch.object(kiki_console.shutil, "which", return_value=None),
                mock.patch.object(kiki_console, "run_check", return_value=passed),
            ):
                preflight = kiki_console.doctor_checks(root, "x86_64", plan, include_iso=False)
                iso = kiki_console.doctor_checks(root, "x86_64", plan, include_iso=True)

            self.assertIn("warn", [check.status for check in preflight])
            self.assertIn("fail", [check.status for check in iso])

    def test_status_human_output_is_compact(self):
        data = {
            "git": {"branch": "main", "upstream": "origin/main", "ahead": 0, "behind": 0, "clean": True, "changed_files": 0},
            "stage3": {"done": 17, "pending": 4, "total": 21},
            "default_plan": kiki_console.DEFAULT_PLAN,
            "default_plan_exists": True,
            "artifacts": {"packages": 3, "package_bytes": 1024, "repository_index": True, "rootfs": [], "isos": [], "recent_run": None},
        }
        output = io.StringIO()

        kiki_console.print_status(data, output)

        self.assertIn("Stage 3      17/21", output.getvalue())
        self.assertIn("패키지       3개", output.getvalue())


if __name__ == "__main__":
    unittest.main()
