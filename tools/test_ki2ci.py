import tempfile
import unittest
from pathlib import Path

import ki2ci


class Ki2CiTests(unittest.TestCase):
    def test_pipeline_registry_contains_expected_pipelines(self):
        self.assertEqual(
            ki2ci.pipeline_names(),
            [
                "smoke",
                "bootstrap",
                "minimal-systemd",
                "stage2",
                "security",
                "iso",
                "bootiso",
                "installer-iso",
                "publish",
                "release",
            ],
        )

    def test_smoke_pipeline_uses_scoped_go_test(self):
        config = ki2ci.CiConfig(
            repo_root=Path("/repo"),
            artifact_root=Path("/repo/build/ki2ci"),
            arch="x86_64",
            jobs=4,
            toolchain_id="test-toolchain",
            publish_dir=Path("/repo/dist/publish"),
        )

        steps = ki2ci.pipeline_steps(config, "smoke")
        commands = [" ".join(step.command) for step in steps]

        self.assertIn("go test ./cmd/... ./internal/...", commands[0])
        self.assertTrue(any("distro/profiles/world.toml" in command for command in commands))
        self.assertTrue(any("distro/profiles/kiki-kube-compute.yaml" in command for command in commands))
        self.assertTrue(any("distro/profiles/kiki-kube-compute-containerd.yaml" in command for command in commands))
        self.assertTrue(any("tools/test_ki2repo.py" in command for command in commands))
        self.assertTrue(any("tools/test_ki2stage2.py" in command for command in commands))

    def test_stage2_pipeline_generates_signed_repository_metadata_without_iso(self):
        config = ki2ci.CiConfig(
            repo_root=Path("/repo"),
            artifact_root=Path("/repo/build/ki2ci"),
            arch="x86_64",
            jobs=4,
            toolchain_id="test-toolchain",
            publish_dir=Path("/repo/dist/publish"),
        )

        commands = [" ".join(step.command) for step in ki2ci.pipeline_steps(config, "stage2")]

        self.assertTrue(any("tools/ki2build.py" in command and "repo-index" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-kubernetes" in command for command in commands))
        self.assertTrue(any("tools/ki2repo.py" in command and "keygen" in command and "stage2-v2-repo.hmac" in command for command in commands))
        self.assertTrue(any("tools/ki2repo.py" in command and "generate --channel stage2-v2 --sign-key" in command for command in commands))
        self.assertTrue(any("tools/ki2repo.py" in command and "verify --key" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "--require-signed-metadata" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "--strict-production" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-binary-smoke" in command for command in commands))
        self.assertTrue(any("go run ./cmd/kiki-installer-tui" in command and "--write" in command and "kiki-kube-compute-containerd.install-plan.yaml" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-install-plan" in command and "--runtime containerd" in command for command in commands))
        self.assertTrue(any("tools/ki2build.py" in command and "rootfs" in command and "kiki-kube-compute.yaml" in command and "--clean-rootfs" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-installed-rootfs" in command and "--runtime cri-o" in command for command in commands))
        self.assertTrue(any("tools/ki2build.py" in command and "rootfs" in command and "kiki-kube-compute-containerd.yaml" in command and "--clean-rootfs" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-installed-rootfs" in command and "--runtime containerd" in command for command in commands))
        self.assertTrue(any("tools/ki2stage2.py" in command and "verify-package-manager" in command for command in commands))
        self.assertTrue(any("tools/ki2repo.py" in command and "summary" in command for command in commands))
        self.assertFalse(any("tools/ki2bootiso.py --repo-root" in command for command in commands))

    def test_job_store_round_trips_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ki2ci.JobStore(Path(tmp))
            job = store.create("smoke")

            loaded = store.read(job["id"])
            self.assertEqual(loaded["pipeline"], "smoke")
            self.assertEqual(loaded["status"], "pending")
            self.assertEqual(len(store.list()), 1)
            self.assertTrue(store.log_path(job["id"]).exists())

    def test_overview_collects_repo_state(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            config = ki2ci.CiConfig(
                repo_root=repo_root,
                artifact_root=Path(tmp),
                arch="x86_64",
                jobs=2,
                toolchain_id="test-toolchain",
                publish_dir=Path(tmp) / "publish",
            )
            store = ki2ci.JobStore(Path(tmp))

            overview = ki2ci.collect_overview(config, store)

            self.assertGreaterEqual(overview["package_count"], 40)
            self.assertGreaterEqual(overview["profile_count"], 1)
            self.assertIn("unpinned_count", overview["security"])

    def test_collect_artifacts_includes_hyperv_disk_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            iso_root = repo_root / "dist" / "iso"
            iso_root.mkdir(parents=True)
            (iso_root / "kiki.iso").write_bytes(b"iso")
            (iso_root / "kiki.vhdx").write_bytes(b"vhdx")
            config = ki2ci.CiConfig(
                repo_root=repo_root,
                artifact_root=Path(tmp) / "jobs",
                arch="x86_64",
                jobs=2,
                toolchain_id="test-toolchain",
                publish_dir=Path(tmp) / "publish",
            )

            artifacts = ki2ci.collect_artifacts(config)

            self.assertEqual([item["name"] for item in artifacts["isos"]], ["kiki.iso"])
            self.assertEqual([item["name"] for item in artifacts["disk_images"]], ["kiki.vhdx"])

    def test_web_pages_render(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            config = ki2ci.CiConfig(
                repo_root=repo_root,
                artifact_root=Path(tmp),
                arch="x86_64",
                jobs=2,
                toolchain_id="test-toolchain",
                publish_dir=Path(tmp) / "publish",
            )
            server = ki2ci.BuildServer(config)
            handler = ki2ci.make_handler(server)
            instance = object.__new__(handler)

            page_methods = [
                "dashboard_page",
                "jobs_page",
                "packages_page",
                "profiles_page",
                "artifacts_page",
                "security_page",
                "deploy_page",
            ]
            for method_name in page_methods:
                with self.subTest(method=method_name):
                    body = getattr(instance, method_name)()
                    self.assertIn(b"KIKI", body)


if __name__ == "__main__":
    unittest.main()
