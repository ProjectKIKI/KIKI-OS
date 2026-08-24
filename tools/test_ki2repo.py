import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2repo


class Ki2RepoTests(unittest.TestCase):
    def test_generate_writes_index_metadata_and_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "dist/ki2/packages/x86_64"
            repo = root / "dist/ki2/repo"
            iso = root / "dist/iso"
            packages.mkdir(parents=True)
            iso.mkdir(parents=True)
            write_package(packages / "base-1-1.x86_64.ki2", name="base", tier="base", runtime=[])
            write_package(packages / "app-2-1.x86_64.ki2", name="app", tier="shell", runtime=["base"])
            (iso / "kiki.iso").write_bytes(b"iso")

            args = fake_args(root=root, packages=packages, repo=repo, iso=iso)
            result = ki2repo.generate(args)

            self.assertEqual(result["packages"], 2)
            index = json.loads((repo / "index.x86_64.json").read_text(encoding="utf-8"))
            self.assertEqual(index["schema"], "ki2-repository-v1")
            self.assertEqual([pkg["name"] for pkg in index["packages"]], ["app", "base"])
            app = next(pkg for pkg in index["packages"] if pkg["name"] == "app")
            self.assertEqual(app["runtime_dependencies"], ["base"])
            self.assertEqual(app["tier"], "shell")

            metadata = json.loads((repo / "metadata.x86_64.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["schema"], "ki2-repository-metadata-v1")
            self.assertEqual(metadata["channel"], "stage2-v2")
            self.assertEqual(metadata["index"]["package_count"], 2)
            self.assertEqual(metadata["packages"]["tiers"], {"base": 1, "shell": 1})
            self.assertEqual(metadata["artifacts"]["iso"][0]["file"], "kiki.iso")
            self.assertFalse(metadata["security"]["signed"])

            channels = json.loads((repo / "channels.json").read_text(encoding="utf-8"))
            self.assertEqual(channels["schema"], "ki2-repository-channels-v1")
            self.assertEqual(channels["channels"]["stage2-v2"]["metadata"], "repo/metadata.x86_64.json")
            self.assertTrue(channels["channels"]["stage2-v2"]["metadata_sha256"])

    def test_sign_and_verify_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "dist/ki2/packages/x86_64"
            repo = root / "dist/ki2/repo"
            iso = root / "dist/iso"
            packages.mkdir(parents=True)
            iso.mkdir(parents=True)
            write_package(packages / "base-1-1.x86_64.ki2", name="base", tier="base", runtime=[])
            key = root / "repo-signing.key"
            key.write_text("00" * 32 + "\n", encoding="utf-8")

            args = fake_args(root=root, packages=packages, repo=repo, iso=iso)
            args.sign_key = key
            ki2repo.generate(args)

            metadata = json.loads((repo / "metadata.x86_64.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata["security"]["signed"])
            self.assertEqual(metadata["security"]["algorithm"], "hmac-sha256")
            self.assertTrue(metadata["security"]["signature"])
            self.assertIn("signed-metadata-hmac-sha256", metadata["capabilities"])
            self.assertTrue(ki2repo.verify_metadata_file(repo / "metadata.x86_64.json", key))

            metadata["name"] = "tampered"
            (repo / "metadata.x86_64.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            self.assertFalse(ki2repo.verify_metadata_file(repo / "metadata.x86_64.json", key))

    def test_sign_and_verify_metadata_with_ed25519(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "dist/ki2/packages/x86_64"
            repo = root / "dist/ki2/repo"
            iso = root / "dist/iso"
            private_key = root / "stage3-repo.ed25519"
            public_key = root / "stage3-repo.ed25519.pub"
            packages.mkdir(parents=True)
            iso.mkdir(parents=True)
            write_package(packages / "base-1-1.x86_64.ki2", name="base", tier="base", runtime=[])
            ki2repo.run_openssl(["genpkey", "-algorithm", "ED25519", "-out", str(private_key)])
            ki2repo.run_openssl(["pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)])

            args = fake_args(root=root, packages=packages, repo=repo, iso=iso)
            args.sign_key = private_key
            args.sign_algorithm = "ed25519"
            ki2repo.generate(args)

            metadata_path = repo / "metadata.x86_64.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["security"]["algorithm"], "ed25519")
            self.assertIn("signed-metadata-ed25519", metadata["capabilities"])
            self.assertTrue(ki2repo.verify_metadata_file(metadata_path, public_key))

            metadata["channel"] = "tampered"
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            self.assertFalse(ki2repo.verify_metadata_file(metadata_path, public_key))


def fake_args(*, root: Path, packages: Path, repo: Path, iso: Path):
    class Args:
        repo_root = root
        arch = "x86_64"
        packages_dir = packages
        repo_dir = repo
        iso_dir = iso
        name = "kiki-test"
        title = "KIKI Test Repository"
        description = "test repository"
        channel = "stage2-v2"
        base_url = "http://repo.example.internal:8080"
        sign_key = None

    return Args()


def write_package(path: Path, *, name: str, tier: str, runtime: list[str]) -> None:
    manifest = {
        "schema": "ki2-package-v1",
        "name": name,
        "version": "1" if name == "base" else "2",
        "release": "1",
        "arch": "x86_64",
        "summary": f"{name} package",
        "license": "MIT",
        "tier": tier,
        "dependencies": {"build": [], "runtime": runtime},
        "payload": {"rootfs_prefix": "rootfs/", "contains_os_tree": True, "file_count": 1},
        "files": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        body = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.mode = 0o644
        info.size = len(body)
        tar.addfile(info, fileobj=BytesReader(body))
        payload = f"{name}\n".encode("utf-8")
        item = tarfile.TarInfo(f"rootfs/usr/bin/{name}")
        item.mode = 0o755
        item.size = len(payload)
        tar.addfile(item, fileobj=BytesReader(payload))


class BytesReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.data) - self.pos
        chunk = self.data[self.pos : self.pos + size]
        self.pos += len(chunk)
        return chunk


if __name__ == "__main__":
    unittest.main()
