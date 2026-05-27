import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2iso


class Ki2IsoTests(unittest.TestCase):
    def test_iso_default_output_uses_date_and_revision_stamp(self):
        root = Path("/repo")
        build_info = {"stamp": ki2iso.format_iso_build_stamp("2026-05-26", "42")}

        output = ki2iso.default_iso_output(root, "stage2", "x86_64", build_info)

        self.assertEqual(output, root / "dist/iso/kiki-stage2-x86_64-20260526-rev42.iso")

    def test_iso_release_name_prefers_repository_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "metadata.x86_64.json").write_text('{"channel":"stage2"}\n', encoding="utf-8")

            self.assertEqual(ki2iso.iso_release_name(repo, "x86_64", "bootstrap-stage1"), "stage2")
            self.assertEqual(ki2iso.iso_release_name(repo, "x86_64", "bootstrap-stage1", "testing"), "testing")

    def test_prepare_iso_tree_writes_manifest_repo_and_rootfs_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            tree = root / "iso-tree"
            (rootfs / "etc").mkdir(parents=True)
            (repo / "packages").mkdir(parents=True)
            (rootfs / "etc/os-release").write_text("ID=kiki-test\n", encoding="utf-8")
            (repo / "index.x86_64.json").write_text('{"packages":[]}\n', encoding="utf-8")

            manifest = ki2iso.prepare_iso_tree(
                rootfs,
                repo,
                tree,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST",
            )

            self.assertEqual(manifest["schema"], "ki2-iso-v1")
            self.assertFalse(manifest["bootable"])
            self.assertTrue((tree / "kiki/repo/index.x86_64.json").exists())
            self.assertTrue((tree / "README.txt").exists())

            manifest_file = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_file["profile"], "bootstrap-stage1")

            with tarfile.open(tree / "kiki/rootfs.tar.gz", "r:gz") as tar:
                self.assertIn("etc/os-release", tar.getnames())


if __name__ == "__main__":
    unittest.main()
