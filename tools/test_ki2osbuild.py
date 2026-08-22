import json
import tempfile
import unittest
from pathlib import Path

import ki2osbuild


class Ki2OsBuildTests(unittest.TestCase):
    def test_default_stage2_plan_generates_expected_steps_without_iso(self):
        repo_root = Path(__file__).resolve().parents[1]
        args = ki2osbuild.build_parser().parse_args(
            [
                "plan",
                "--repo-root",
                str(repo_root),
                "--build-plan",
                "distro/build-plans/stage2-kube-compute-containerd.yaml",
                "--jobs",
                "4",
                "--toolchain-id",
                "test-toolchain",
            ]
        )
        ctx = ki2osbuild.make_context(args)
        steps = ki2osbuild.build_steps(ctx)
        commands = [" ".join(step.command) for step in steps]

        self.assertTrue(any("tools/ki2build.py" in command and "validate" in command for command in commands))
        self.assertTrue(any("tools/ki2build.py" in command and "build" in command and "--allow-unpinned" in command for command in commands))
        self.assertTrue(any("tools/ki2repo.py" in command and "generate --channel stage2-v2 --sign-key" in command for command in commands))
        self.assertTrue(any("tools/ki2build.py" in command and "rootfs" in command and "--clean-rootfs" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-kubernetes" in command and "--strict-production" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-package-manager" in command for command in commands))
        self.assertFalse(any("tools/ki2bootiso.py" in command for command in commands))

    def test_iso_flag_adds_bootable_iso_step(self):
        repo_root = Path(__file__).resolve().parents[1]
        args = ki2osbuild.build_parser().parse_args(
            [
                "plan",
                "--repo-root",
                str(repo_root),
                "--build-plan",
                "distro/build-plans/stage2-kube-compute-containerd.yaml",
                "--iso",
            ]
        )
        ctx = ki2osbuild.make_context(args)
        commands = [" ".join(step.command) for step in ki2osbuild.build_steps(ctx)]

        self.assertTrue(any("tools/ki2bootiso.py" in command and "--mode installer" in command for command in commands))

    def test_dry_run_writes_manifest_without_executing_steps(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            args = ki2osbuild.build_parser().parse_args(
                [
                    "run",
                    "--repo-root",
                    str(repo_root),
                    "--build-plan",
                    "distro/build-plans/stage2-kube-compute-containerd.yaml",
                    "--run-dir",
                    tmp,
                    "--skip-build",
                    "--skip-verify",
                    "--dry-run",
                ]
            )

            ki2osbuild.command_run(args)

            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "kiki-os-build-run-v1")
            self.assertEqual(manifest["status"], "succeeded")
            self.assertTrue(manifest["dry_run"])
            self.assertTrue(manifest["steps"])
            self.assertTrue(all(step["status"] in {"dry-run", "skipped"} for step in manifest["steps"]))


if __name__ == "__main__":
    unittest.main()
