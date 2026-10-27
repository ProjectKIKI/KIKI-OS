import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ki2graphics


class GotkPackagingTests(unittest.TestCase):
    def test_runtime_absolute_links_become_payload_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "usr/share/fontconfig/sample.conf"
            source.parent.mkdir(parents=True)
            source.write_text("font")
            link = root / "etc/fonts/conf.d/sample.conf"
            link.parent.mkdir(parents=True)
            link.symlink_to("/usr/share/fontconfig/sample.conf")
            ki2graphics.relativize_runtime_links(root)
            self.assertEqual(link.resolve(), source)
            self.assertEqual(link.read_text(), "font")

    def test_default_selects_scratch_pad_go_ui(self):
        self.assertEqual(ki2graphics.parser().parse_args(["prepare"]).installer_ui, "gotk")

    def test_opt_in_builds_live_at_existing_path(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ki2graphics, "run") as run:
            root = Path(tmp)
            binary = root / "stage/usr/bin/kiki-installer-gtk"
            ki2graphics.build_installer(root, binary, "gotk")
            run.assert_called_once_with(["make", "-C", str(root / "cmd/kiki-installer-gotk"),
                                         f"OUTPUT={binary}", "LIVE=true"])

    def test_unknown_backend_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ki2graphics.GraphicsError):
                ki2graphics.build_installer(Path(tmp), Path(tmp) / "binary", "unknown")
