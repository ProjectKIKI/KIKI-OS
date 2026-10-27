import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import ki2build

class InfoIndexTests(unittest.TestCase):
    def test_failure_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = root / "usr/share/info"
            info.mkdir(parents=True)
            (info / "a.info").write_text("fixture")
            (info / "dir").write_text("previous")
            with patch.object(ki2build.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ki2build.Ki2Error, "install-info"):
                    ki2build.refresh_rootfs_info_index(root)
            with patch.object(ki2build.shutil, "which", return_value="/fixture/install-info"), patch.object(
                    ki2build.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "install-info")):
                with self.assertRaisesRegex(ki2build.Ki2Error, "rebuild failed"):
                    ki2build.refresh_rootfs_info_index(root)
            self.assertEqual((info / "dir").read_text(), "previous")
            self.assertFalse(list(info.glob(".ki2-info-*")))

    @unittest.skipUnless(shutil.which("install-info"), "requires GNU install-info")
    def test_real_merge_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = root / "usr/share/info"
            info.mkdir(parents=True)
            for name in ("first", "second"):
                (info / (name + ".info")).write_text(
                    "INFO-DIR-SECTION Test manuals\nSTART-INFO-DIR-ENTRY\n"
                    f"* {name}: ({name}). Test manual.\nEND-INFO-DIR-ENTRY\n"
                    f"\x1f\nFile: {name}.info, Node: Top\n\nTest content.\n")
            (info / "dir").write_text("old index")
            ki2build.refresh_rootfs_info_index(root)
            result = (info / "dir").read_bytes()
            for name in (b"first", b"second"):
                self.assertIn(b"* " + name + b":", result)
            ki2build.refresh_rootfs_info_index(root)
            self.assertEqual((info / "dir").read_bytes(), result)

if __name__ == "__main__":
    unittest.main()
