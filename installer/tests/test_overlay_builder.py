import hashlib
import importlib.util
import os
import tarfile
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts/build_alpine_overlay.py"
SPEC = importlib.util.spec_from_file_location("overlay_builder", MODULE_PATH)
overlay_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay_builder)


class OverlayBuilderTests(unittest.TestCase):
    def test_output_is_deterministic_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            (root / "usr/local/bin").mkdir(parents=True)
            script = root / "usr/local/bin/kiki-install"
            script.write_text("#!/bin/sh\n", encoding="utf-8")
            output = Path(directory) / "overlay.tar.gz"
            overlay_builder.build_overlay(root, output)
            first = hashlib.sha256(output.read_bytes()).hexdigest()
            os.utime(script, (2_000_000_000, 2_000_000_000))
            overlay_builder.build_overlay(root, output)
            second = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(first, second)
            with tarfile.open(output, "r:gz") as archive:
                member = archive.getmember("usr/local/bin/kiki-install")
                self.assertEqual(member.mtime, 0)
                self.assertEqual(member.uid, 0)
                self.assertEqual(member.mode, 0o755)


if __name__ == "__main__":
    unittest.main()
