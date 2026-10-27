import tempfile
import unittest
from pathlib import Path

import ki2graphics


class BrandAssetTests(unittest.TestCase):
    def test_selected_original_is_copied_without_modification(self):
        repo = Path(__file__).resolve().parents[1]
        source = repo / "assets/brand/kikios-kiki-wordmark-v1.png"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            ki2graphics.install_brand_asset(repo, target)
            self.assertEqual((target / "usr/share/pixmaps/kiki-installer.png").read_bytes(),
                             source.read_bytes())

    def test_missing_or_invalid_brand_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            output = Path(tmp) / "output"
            source = repo / "assets/brand/kikios-kiki-wordmark-v1.png"
            with self.assertRaises(ki2graphics.GraphicsError):
                ki2graphics.install_brand_asset(repo, output)
            source.parent.mkdir(parents=True)
            source.write_bytes(b"not a PNG")
            with self.assertRaises(ki2graphics.GraphicsError):
                ki2graphics.install_brand_asset(repo, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
