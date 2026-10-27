import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

import ki2build
import ki2repo


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required")
class PrebuiltProfileTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', "POSIX symlinks required")
    def test_graphical_profile_replaces_baseline_default_and_disables_tty1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rootfs"
            units = root / "usr/lib/systemd/system"
            units.mkdir(parents=True)
            (units / "graphical.target").write_text("[Unit]\nDescription=Graphical\n")
            (units / "gdm.service").write_text("[Unit]\nDescription=GDM\n[Install]\nAlias=display-manager.service\n")
            config = root / "etc/systemd/system"
            (config / "getty.target.wants").mkdir(parents=True)
            (config / "default.target").write_text("baseline copied multi-user target")
            tty = config / "getty.target.wants/getty@tty1.service"
            tty.symlink_to("/usr/lib/systemd/system/getty@.service")
            context = SimpleNamespace(rootfs_dir=root, dry_run=False, clean_rootfs=False, arch="x86_64")
            profile = dict(boot={"default_target": "graphical.target"},
                           services={"disable": ["getty@tty1.service"], "enable": ["gdm.service"]})
            ki2build.assemble_rootfs(context, {}, [], profile)
            self.assertEqual((config / "default.target").resolve(), units / "graphical.target")
            self.assertEqual((config / "display-manager.service").resolve(), units / "gdm.service")
            self.assertFalse(tty.is_symlink())

    def test_verified_snapshot_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = root / "snapshot"
            packages = repository / "packages/x86_64"
            packages.mkdir(parents=True)
            (repository / "repo").mkdir()
            payload = root / "payload"
            (payload / "usr/share/test").mkdir(parents=True)
            (payload / "usr/share/test/data").write_text("package fixture")
            recipe = ki2build.normalize_recipe(dict(name="app", version="1", release="1", summary="fixture",
                license="MIT", architectures=["x86_64"], dependencies={"build": [], "runtime": []},
                source={"type": "local", "path": str(payload)}, build={"system": "copy"}), root / "recipe.toml")
            package = packages / ki2build.package_filename(recipe, "x86_64")
            ki2build.create_package(SimpleNamespace(arch="x86_64"), recipe, payload, package, "fixture", {})
            entry = ki2repo.package_entry(package, ki2build.read_package_manifest(package))
            index = repository / "repo/index.x86_64.json"
            index.write_text(json.dumps({"arch": "x86_64", "packages": [entry]}))
            private, public = root / "private.pem", repository / "public.pem"
            ki2repo.run_openssl(["genpkey", "-algorithm", "ED25519", "-out", str(private)])
            ki2repo.run_openssl(["pkey", "-in", str(private), "-pubout", "-out", str(public)])
            metadata = ki2repo.sign_metadata_ed25519({"arch": "x86_64", "index": {
                "sha256": ki2build.file_sha256(index), "size": index.stat().st_size}}, private)
            metadata_path = index.with_name("metadata.x86_64.json")
            metadata_path.write_text(json.dumps(metadata))
            profile = dict(packages=["app"], prebuilt=dict(repository="snapshot", public_key="public.pem",
                public_key_sha256=ki2build.file_sha256(public), index_sha256=ki2build.file_sha256(index)))
            source, recipes, order = ki2build.load_prebuilt_profile(profile, root, "x86_64")
            self.assertEqual(source, repository)
            self.assertEqual(order, ["app"])
            self.assertEqual(recipes["app"].build["system"], "prebuilt")
            original = package.read_bytes()
            package.write_bytes(b"X" * len(original))
            with self.assertRaisesRegex(ki2build.Ki2Error, "integrity"):
                ki2build.load_prebuilt_profile(profile, root, "x86_64")
            package.write_bytes(original)
            changed = dict(metadata, arch="different")
            metadata_path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ki2build.Ki2Error, "signature"):
                ki2build.load_prebuilt_profile(profile, root, "x86_64")
            metadata_path.write_text(json.dumps(metadata))
            index.write_bytes(index.read_bytes() + b" ")
            with self.assertRaisesRegex(ki2build.Ki2Error, "pinned"):
                ki2build.load_prebuilt_profile(profile, root, "x86_64")


if __name__ == "__main__":
    unittest.main()
