import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "ki2build.py"


class Ki2BuildTests(unittest.TestCase):
    def run_ki2(self, root, *args):
        command = [sys.executable, str(SCRIPT), "--repo-root", str(root), *args]
        return subprocess.run(command, text=True, capture_output=True, check=True)

    def test_local_build_repo_and_rootfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "distro/recipes").mkdir(parents=True)
            (root / "distro/profiles").mkdir(parents=True)
            (root / "distro/sources/base/etc").mkdir(parents=True)
            (root / "distro/sources/middle").mkdir(parents=True)
            (root / "distro/sources/app/usr/bin").mkdir(parents=True)
            (root / "distro/sources/app-tools/usr/bin").mkdir(parents=True)

            (root / "distro/sources/base/etc/os-release").write_text("ID=kiki-test\n", encoding="utf-8")
            (root / "distro/sources/app/usr/bin/hello").write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            (root / "distro/sources/app-tools/usr/bin/tool").write_text("#!/bin/sh\necho tool\n", encoding="utf-8")

            (root / "distro/recipes/local.toml").write_text(
                """
[[recipe]]
name = "base"
version = "1"
release = 1
summary = "base files"
license = "MIT"
architectures = ["all"]
[recipe.source]
type = "local"
path = "distro/sources/base"
[recipe.dependencies]
build = []
runtime = []
[recipe.build]
system = "copy"

[[recipe]]
name = "middle"
version = "1"
release = 1
summary = "middle dependency"
license = "MIT"
architectures = ["all"]
[recipe.source]
type = "local"
path = "distro/sources/middle"
[recipe.dependencies]
build = []
runtime = ["base"]
[recipe.build]
system = "copy"

[[recipe]]
name = "app-tools"
version = "1"
release = 1
summary = "prefix collision package"
license = "MIT"
architectures = ["all"]
[recipe.source]
type = "local"
path = "distro/sources/app-tools"
[recipe.dependencies]
build = []
runtime = []
[recipe.build]
system = "copy"

[[recipe]]
name = "app"
version = "1"
release = 1
summary = "test app"
license = "MIT"
architectures = ["all"]
[recipe.source]
type = "local"
path = "distro/sources/app"
[recipe.dependencies]
build = []
runtime = ["middle"]
[recipe.build]
system = "copy"
""",
                encoding="utf-8",
            )
            (root / "distro/profiles/test.toml").write_text(
                """
[profile]
name = "test"
packages = ["app-tools", "app"]
""",
                encoding="utf-8",
            )

            self.run_ki2(root, "validate", "--profile", "distro/profiles/test.toml", "--max-packages", "4")
            plan = self.run_ki2(root, "plan", "--profile", "distro/profiles/test.toml").stdout
            self.assertIn("01. app-tools", plan)
            self.assertIn("02. base", plan)
            self.assertIn("03. middle", plan)
            self.assertIn("04. app", plan)

            self.run_ki2(root, "build", "--profile", "distro/profiles/test.toml")
            package = root / "dist/ki2/packages/x86_64/app-1-1.x86_64.ki2"
            self.assertTrue(package.exists())
            self.assertEqual(
                (root / "build/ki2/x86_64/sysroot/etc/os-release").read_text(encoding="utf-8"),
                "ID=kiki-test\n",
            )
            with tarfile.open(package, "r:gz") as tar:
                info = tar.getmember("rootfs/usr/bin/hello")
                self.assertEqual(info.mode, 0o755)
                manifest_file = tar.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                manifest = json.loads(manifest_file.read().decode("utf-8"))
                self.assertEqual(manifest["dependencies"]["runtime"], ["middle"])
                self.assertEqual(manifest["dependencies"]["build"], [])

            state_path = root / "build/ki2/x86_64/build-state.json"
            state_path.unlink()
            rebuild = self.run_ki2(root, "build", "--profile", "distro/profiles/test.toml").stdout
            self.assertIn("[skip] app: artifact cache hit", rebuild)
            restored_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(set(restored_state), {"app", "app-tools", "base", "middle"})

            self.run_ki2(root, "repo-index")
            index = json.loads((root / "dist/ki2/repo/index.x86_64.json").read_text(encoding="utf-8"))
            self.assertEqual([item["name"] for item in index["packages"]], ["app", "app-tools", "base", "middle"])
            app_index = next(item for item in index["packages"] if item["name"] == "app")
            self.assertEqual(app_index["dependencies"]["runtime"], ["middle"])

            self.run_ki2(
                root,
                "rootfs",
                "--profile",
                "distro/profiles/test.toml",
                "--rootfs-dir",
                "dist/rootfs",
            )
            self.assertEqual((root / "dist/rootfs/usr/bin/hello").read_text(encoding="utf-8"), "#!/bin/sh\necho hello\n")
            self.assertEqual((root / "dist/rootfs/usr/bin/tool").read_text(encoding="utf-8"), "#!/bin/sh\necho tool\n")


if __name__ == "__main__":
    unittest.main()
