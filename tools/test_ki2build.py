import json
import os
import importlib.util
import io
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "ki2build.py"
SPEC = importlib.util.spec_from_file_location("ki2build", SCRIPT)
ki2build = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ki2build
SPEC.loader.exec_module(ki2build)


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
            (root / "distro/sources/base/etc/sudoers.d").mkdir(parents=True)
            (root / "distro/sources/base/lib64").mkdir(parents=True)
            (root / "distro/sources/base/root").mkdir(parents=True)
            (root / "distro/sources/base/tmp").mkdir(parents=True)
            (root / "distro/sources/base/var/tmp").mkdir(parents=True)
            (root / "distro/sources/base/usr/bin").mkdir(parents=True)
            (root / "distro/sources/base/usr/lib/systemd/system").mkdir(parents=True)
            (root / "distro/sources/middle").mkdir(parents=True)
            (root / "distro/sources/app/usr/bin").mkdir(parents=True)
            (root / "distro/sources/app-tools/usr/bin").mkdir(parents=True)

            (root / "distro/sources/base/etc/os-release").write_text("ID=kiki-test\n", encoding="utf-8")
            (root / "distro/sources/base/etc/shadow").write_text("root:*:1:0:99999:7:::\n", encoding="utf-8")
            (root / "distro/sources/base/etc/sudoers").write_text("%sudo ALL=(ALL:ALL) ALL\n", encoding="utf-8")
            (root / "distro/sources/base/etc/sudoers.d/kiki-admin").write_text("%sudo ALL=(ALL:ALL) ALL\n", encoding="utf-8")
            (root / "distro/sources/base/usr/bin/sudo").write_text("#!/bin/sh\n", encoding="utf-8")
            loader_source = root / "distro/sources/base/lib64/ld-linux-x86-64.so.2"
            loader_source.write_bytes(b"fake-loader")
            loader_source.chmod(0o644)
            unit_source = root / "distro/sources/base/usr/lib/systemd/system/test.service"
            unit_source.write_text(
                "[Service]\nExecStart=/usr/bin/true\n\n[Install]\nWantedBy=multi-user.target\nAlias=test-alias.service\nAlso=helper.service\n",
                encoding="utf-8",
            )
            unit_source.chmod(0o777)
            (root / "distro/sources/base/usr/lib/systemd/system/helper.service").write_text(
                "[Service]\nExecStart=/usr/bin/true\n\n[Install]\nWantedBy=sysinit.target\n",
                encoding="utf-8",
            )
            hello_source = root / "distro/sources/app/usr/bin/hello"
            hello_source.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
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

[profile.services]
enable = ["test.service"]
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
                self.assertEqual(info.uid, 0)
                self.assertEqual(info.gid, 0)
                self.assertEqual(info.uname, "root")
                self.assertEqual(info.gname, "root")
                manifest_file = tar.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                manifest = json.loads(manifest_file.read().decode("utf-8"))
                self.assertEqual(manifest["dependencies"]["runtime"], ["middle"])
                self.assertEqual(manifest["dependencies"]["build"], [])
                self.assertEqual(manifest["payload"]["rootfs_prefix"], "rootfs/")
                self.assertTrue(manifest["payload"]["contains_os_tree"])
                self.assertEqual(manifest["payload"]["file_count"], 1)
                hello_file = next(item for item in manifest["files"] if item["path"] == "/usr/bin/hello")
                self.assertEqual(hello_file["type"], "file")
                self.assertEqual(hello_file["mode"], "0o755")
                self.assertEqual(hello_file["size"], hello_source.stat().st_size)

            with tarfile.open(root / "dist/ki2/packages/x86_64/base-1-1.x86_64.ki2", "r:gz") as tar:
                self.assertEqual(tar.getmember("rootfs/etc/shadow").mode, 0o600)
                self.assertEqual(tar.getmember("rootfs/etc/sudoers").mode, 0o440)
                self.assertEqual(tar.getmember("rootfs/etc/sudoers.d").mode, 0o750)
                self.assertEqual(tar.getmember("rootfs/etc/sudoers.d/kiki-admin").mode, 0o440)
                self.assertEqual(tar.getmember("rootfs/usr/bin/sudo").mode, 0o4755)
                self.assertEqual(tar.getmember("rootfs/root").mode, 0o700)
                self.assertEqual(tar.getmember("rootfs/tmp").mode, 0o1777)
                self.assertEqual(tar.getmember("rootfs/var/tmp").mode, 0o1777)
                self.assertEqual(tar.getmember("rootfs/lib64/ld-linux-x86-64.so.2").mode, 0o755)
                self.assertEqual(tar.getmember("rootfs/usr/lib/systemd/system/test.service").mode, 0o644)

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
            self.assertEqual(app_index["file_count"], 1)

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
            self.assertTrue((root / "dist/rootfs/etc/systemd/system/multi-user.target.wants/test.service").exists())
            self.assertTrue((root / "dist/rootfs/etc/systemd/system/sysinit.target.wants/helper.service").exists())
            self.assertTrue((root / "dist/rootfs/etc/systemd/system/test-alias.service").exists())

    def test_kernel_config_fragments_are_merged_and_keyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "distro/recipes").mkdir(parents=True)
            (root / "distro/profiles").mkdir(parents=True)
            (root / "distro/sources/kernel").mkdir(parents=True)
            (root / "distro/kernel").mkdir(parents=True)
            fragment = root / "distro/kernel/vm.config"
            fragment.write_text("CONFIG_BLK_DEV_INITRD=y\n", encoding="utf-8")

            (root / "distro/recipes/kernel.toml").write_text(
                """
[[recipe]]
name = "linux"
version = "1"
release = 1
summary = "test kernel"
license = "GPL-2.0-only"
architectures = ["x86_64"]
[recipe.source]
type = "local"
path = "distro/sources/kernel"
[recipe.dependencies]
build = []
runtime = []
[recipe.build]
system = "kernel"
config_fragments = ["distro/kernel/vm.config"]
""",
                encoding="utf-8",
            )
            (root / "distro/profiles/kernel.toml").write_text(
                """
[profile]
name = "kernel"
packages = ["linux"]
""",
                encoding="utf-8",
            )

            first = self.run_ki2(root, "build", "--dry-run", "--profile", "distro/profiles/kernel.toml").stdout
            self.assertIn("merge_config.sh", first)
            self.assertIn("olddefconfig", first)
            self.assertIn("distro/kernel/vm.config", first.replace("\\", "/"))
            first_key = re.search(r"key=([0-9a-f]+)", first)
            self.assertIsNotNone(first_key)

            fragment.write_text("CONFIG_BLK_DEV_INITRD=y\nCONFIG_DEVTMPFS=y\n", encoding="utf-8")
            second = self.run_ki2(root, "build", "--dry-run", "--profile", "distro/profiles/kernel.toml").stdout
            second_key = re.search(r"key=([0-9a-f]+)", second)
            self.assertIsNotNone(second_key)
            self.assertNotEqual(first_key.group(1), second_key.group(1))

    def test_patches_are_printed_and_keyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "distro/recipes").mkdir(parents=True)
            (root / "distro/profiles").mkdir(parents=True)
            (root / "distro/sources/app").mkdir(parents=True)
            (root / "distro/patches").mkdir(parents=True)
            patch = root / "distro/patches/app.patch"
            patch.write_text("first patch\n", encoding="utf-8")

            (root / "distro/recipes/local.toml").write_text(
                """
[[recipe]]
name = "app"
version = "1"
release = 1
summary = "patched app"
license = "MIT"
architectures = ["all"]
[recipe.source]
type = "local"
path = "distro/sources/app"
[recipe.dependencies]
build = []
runtime = []
[recipe.build]
system = "copy"
patches = ["distro/patches/app.patch"]
""",
                encoding="utf-8",
            )
            (root / "distro/profiles/test.toml").write_text(
                """
[profile]
name = "test"
packages = ["app"]
""",
                encoding="utf-8",
            )

            first = self.run_ki2(root, "build", "--dry-run", "--profile", "distro/profiles/test.toml").stdout
            self.assertIn("patch -d", first)
            self.assertIn("distro/patches/app.patch", first.replace("\\", "/"))
            first_key = re.search(r"key=([0-9a-f]+)", first)
            self.assertIsNotNone(first_key)

            patch.write_text("second patch\n", encoding="utf-8")
            second = self.run_ki2(root, "build", "--dry-run", "--profile", "distro/profiles/test.toml").stdout
            second_key = re.search(r"key=([0-9a-f]+)", second)
            self.assertIsNotNone(second_key)
            self.assertNotEqual(first_key.group(1), second_key.group(1))

    def test_yaml_recipes_profiles_and_dependency_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "distro/recipes").mkdir(parents=True)
            (root / "distro/profiles").mkdir(parents=True)
            (root / "distro/sources/base/etc").mkdir(parents=True)
            (root / "distro/sources/app/usr/bin").mkdir(parents=True)
            (root / "distro/sources/extra").mkdir(parents=True)

            (root / "distro/sources/base/etc/os-release").write_text("ID=kiki-yaml\n", encoding="utf-8")
            (root / "distro/sources/app/usr/bin/yaml-app").write_text("#!/bin/sh\necho yaml\n", encoding="utf-8")

            (root / "distro/recipes/local.yaml").write_text(
                """
recipes:
  - name: base
    version: "1"
    release: 1
    summary: base files
    license: MIT
    arch: all
    source:
      type: local
      path: distro/sources/base
    depends:
      build: []
      runtime: []
    build:
      system: copy
  - name: app
    version: "1"
    release: 1
    summary: app files
    license: MIT
    architectures:
      - all
    source:
      type: local
      path: distro/sources/app
    depends:
      runtime:
        - base
      build: []
    build:
      system: copy
  - name: extra
    version: "1"
    release: 1
    summary: package outside the selected profile
    license: MIT
    arch: all
    source:
      type: local
      path: distro/sources/extra
    depends:
      runtime: []
      build: []
    build:
      system: copy
""",
                encoding="utf-8",
            )
            (root / "distro/profiles/test.yaml").write_text(
                """
profile:
  name: yaml-test
  description: YAML profile smoke
  packages:
    - app
""",
                encoding="utf-8",
            )

            self.run_ki2(root, "validate", "--profile", "distro/profiles/test.yaml", "--max-packages", "2")
            plan = self.run_ki2(root, "plan", "--profile", "distro/profiles/test.yaml").stdout
            self.assertIn("01. base", plan)
            self.assertIn("02. app", plan)

            self.run_ki2(root, "build", "--profile", "distro/profiles/test.yaml")
            package = root / "dist/ki2/packages/x86_64/app-1-1.x86_64.ki2"
            self.assertTrue(package.exists())
            with tarfile.open(package, "r:gz") as tar:
                manifest_file = tar.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                manifest = json.loads(manifest_file.read().decode("utf-8"))
                self.assertEqual(manifest["dependencies"]["runtime"], ["base"])

    def test_rootfs_extract_replaces_existing_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            (rootfs / "bin").mkdir(parents=True)
            (rootfs / "bin/busybox").write_text("busybox\n", encoding="utf-8")
            try:
                os.symlink("busybox", rootfs / "bin/login")
            except (AttributeError, NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks are not available in this test environment: {exc}")

            package = root / "shadow.ki2"
            with tarfile.open(package, "w:gz") as tar:
                payload = b"real-login\n"
                info = tarfile.TarInfo("rootfs/bin/login")
                info.mode = 0o755
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))

            ki2build.extract_package_rootfs(package, rootfs)
            login = rootfs / "bin/login"
            self.assertFalse(login.is_symlink())
            self.assertEqual(login.read_text(encoding="utf-8"), "real-login\n")
            self.assertEqual((rootfs / "bin/busybox").read_text(encoding="utf-8"), "busybox\n")

    def test_package_artifact_by_name_prefers_numeric_latest_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "dist/ki2/packages/x86_64"
            packages.mkdir(parents=True)

            def write_package(filename, release):
                package = packages / filename
                manifest = {
                    "schema": "ki2-package-v1",
                    "name": "base-files",
                    "version": "0.1.0",
                    "release": str(release),
                    "arch": "x86_64",
                }
                payload = json.dumps(manifest).encode("utf-8")
                with tarfile.open(package, "w:gz") as tar:
                    info = tarfile.TarInfo("manifest.json")
                    info.mode = 0o644
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))

            write_package("base-files-0.1.0-9.x86_64.ki2", 9)
            write_package("base-files-0.1.0-10.x86_64.ki2", 10)
            ctx = ki2build.BuildContext(
                repo_root=root,
                recipe_dir=root / "distro/recipes",
                build_dir=root / "build/ki2",
                packages_dir=root / "dist/ki2/packages",
                repo_dir=root / "dist/ki2/repo",
                source_cache=root / "dist/sources",
                rootfs_dir=None,
                arch="x86_64",
                jobs=1,
                toolchain_id="test",
                dry_run=False,
                allow_unpinned=False,
                verbose=False,
            )

            latest = ki2build.package_artifact_by_name(ctx, "base-files")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.name, "base-files-0.1.0-10.x86_64.ki2")


if __name__ == "__main__":
    unittest.main()
