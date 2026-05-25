import json
import tempfile
import unittest
from pathlib import Path

import ki2publish


class Ki2PublishTests(unittest.TestCase):
    def test_publish_copies_artifacts_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            target = Path(tmp) / "public"
            (root / "dist/ki2/repo").mkdir(parents=True)
            (root / "dist/ki2/packages/x86_64").mkdir(parents=True)
            (root / "dist/iso").mkdir(parents=True)
            (root / "dist/ki2/repo/index.x86_64.json").write_text("{}\n", encoding="utf-8")
            (root / "dist/ki2/packages/x86_64/base.ki2").write_text("pkg", encoding="utf-8")
            (root / "dist/iso/kiki.iso").write_text("iso", encoding="utf-8")

            manifest = ki2publish.publish(root, target, "x86_64")

            self.assertEqual(manifest["schema"], "ki2-publish-v1")
            self.assertTrue((target / "repo/index.x86_64.json").exists())
            self.assertTrue((target / "packages/base.ki2").exists())
            self.assertTrue((target / "iso/kiki.iso").exists())
            written = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(written["items"]["packages"]["files"], 1)


if __name__ == "__main__":
    unittest.main()
