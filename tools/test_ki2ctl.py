import functools
import hmac
import hashlib
import http.server
import json
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/ki2ctl/usr/bin/ki2ctl"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


class Ki2CtlTests(unittest.TestCase):
    def run_ki2ctl(self, root, *args):
        command = [sys.executable, str(SCRIPT), "--root", str(root), *args]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise AssertionError(
                f"command failed: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def run_ki2ctl_failure(self, root, *args):
        command = [sys.executable, str(SCRIPT), "--root", str(root), *args]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            raise AssertionError(f"command unexpectedly succeeded: {' '.join(command)}\nstdout:\n{result.stdout}")
        return result

    def test_http_update_install_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            repo_packages = repo / "packages"
            repo_index = repo / "repo"
            repo_packages.mkdir(parents=True)
            repo_index.mkdir(parents=True)

            dep_pkg = repo_packages / "libhello-1-1.x86_64.ki2"
            app_pkg = repo_packages / "hello-1-1.x86_64.ki2"
            write_ki2_package(dep_pkg, name="libhello", dependencies=[], files={"rootfs/usr/lib/libhello.txt": b"library\n"})
            write_ki2_package(app_pkg, name="hello", dependencies=["libhello"], files={"rootfs/usr/bin/hello": b"#!/bin/sh\necho hello\n"})
            write_index(repo_index / "index.x86_64.json", [dep_pkg, app_pkg])

            self.run_ki2ctl(target, "repo", "set", repo_url)
            update = self.run_ki2ctl(target, "update").stdout
            self.assertIn("2 packages", update)

            search = self.run_ki2ctl(target, "search", "hello").stdout
            self.assertIn("hello", search)
            self.assertIn("libhello", search)

            dry_run = self.run_ki2ctl(target, "install", "hello", "--dry-run").stdout
            self.assertRegex(dry_run, r"libhello 1-1\s+hello 1-1")

            install = self.run_ki2ctl(target, "install", "hello").stdout
            self.assertIn("installed libhello", install)
            self.assertIn("installed hello", install)
            self.assertEqual((target / "usr/bin/hello").read_text(encoding="utf-8"), "#!/bin/sh\necho hello\n")
            self.assertEqual((target / "usr/lib/libhello.txt").read_text(encoding="utf-8"), "library\n")

            installed = self.run_ki2ctl(target, "list").stdout
            self.assertIn("hello\t1-1", installed)
            self.assertIn("libhello\t1-1", installed)
            transactions = list((target / "var/lib/ki2/transactions").glob("*.json"))
            self.assertTrue(transactions)
            last_tx = json.loads(sorted(transactions)[-1].read_text(encoding="utf-8"))
            self.assertEqual(last_tx["schema"], "ki2-transaction-v1")
            self.assertEqual(last_tx["status"], "succeeded")

            remove = self.run_ki2ctl(target, "remove", "hello").stdout
            self.assertIn("remove /usr/bin/hello", remove)
            self.assertFalse((target / "usr/bin/hello").exists())
            self.assertTrue((target / "usr/lib/libhello.txt").exists())

    def test_upgrade_installed_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            repo_packages = repo / "packages"
            repo_index = repo / "repo"
            repo_packages.mkdir(parents=True)
            repo_index.mkdir(parents=True)

            hello_v1 = repo_packages / "hello-1-1.x86_64.ki2"
            hello_v2 = repo_packages / "hello-2-1.x86_64.ki2"
            write_ki2_package(hello_v1, name="hello", version="1", dependencies=[], files={"rootfs/usr/bin/hello": b"v1\n"})
            write_index(repo_index / "index.x86_64.json", [hello_v1])

            self.run_ki2ctl(target, "repo", "set", repo_url)
            self.run_ki2ctl(target, "update")
            self.run_ki2ctl(target, "install", "hello")
            self.assertEqual((target / "usr/bin/hello").read_text(encoding="utf-8"), "v1\n")

            write_ki2_package(hello_v2, name="hello", version="2", dependencies=[], files={"rootfs/usr/bin/hello": b"v2\n"})
            write_index(repo_index / "index.x86_64.json", [hello_v1, hello_v2])
            self.run_ki2ctl(target, "update")

            dry_run = self.run_ki2ctl(target, "upgrade", "--dry-run").stdout
            self.assertIn("hello 1-1 -> 2-1", dry_run)

            upgrade = self.run_ki2ctl(target, "upgrade").stdout
            self.assertIn("installed hello", upgrade)
            self.assertEqual((target / "usr/bin/hello").read_text(encoding="utf-8"), "v2\n")
            installed = self.run_ki2ctl(target, "list").stdout
            self.assertIn("hello\t2-1", installed)

    def test_install_rejects_file_owned_by_another_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            repo_packages = repo / "packages"
            repo_index = repo / "repo"
            repo_packages.mkdir(parents=True)
            repo_index.mkdir(parents=True)

            owner_pkg = repo_packages / "owner-1-1.x86_64.ki2"
            rival_pkg = repo_packages / "rival-1-1.x86_64.ki2"
            write_ki2_package(owner_pkg, name="owner", dependencies=[], files={"rootfs/usr/bin/tool": b"owner\n"})
            write_ki2_package(rival_pkg, name="rival", dependencies=[], files={"rootfs/usr/bin/tool": b"rival\n"})
            write_index(repo_index / "index.x86_64.json", [owner_pkg, rival_pkg])

            self.run_ki2ctl(target, "repo", "set", repo_url)
            self.run_ki2ctl(target, "update")
            self.run_ki2ctl(target, "install", "owner")
            failure = self.run_ki2ctl_failure(target, "install", "rival")
            self.assertIn("file conflicts", failure.stderr)
            self.assertIn("owned by installed package owner", failure.stderr)
            self.assertEqual((target / "usr/bin/tool").read_text(encoding="utf-8"), "owner\n")
            installed = self.run_ki2ctl(target, "list").stdout
            self.assertIn("owner\t1-1", installed)
            self.assertNotIn("rival\t1-1", installed)

    def test_failed_install_rolls_back_files_and_installed_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            repo_packages = repo / "packages"
            repo_index = repo / "repo"
            repo_packages.mkdir(parents=True)
            repo_index.mkdir(parents=True)

            broken_pkg = repo_packages / "broken-1-1.x86_64.ki2"
            write_broken_ki2_package(broken_pkg)
            write_index(repo_index / "index.x86_64.json", [broken_pkg])

            self.run_ki2ctl(target, "repo", "set", repo_url)
            self.run_ki2ctl(target, "update")
            failure = self.run_ki2ctl_failure(target, "install", "broken")
            self.assertIn("missing", failure.stderr)
            self.assertFalse((target / "usr/bin/good").exists())
            installed = json.loads((target / "var/lib/ki2/installed.json").read_text(encoding="utf-8"))
            self.assertEqual(installed["packages"], {})
            transactions = list((target / "var/lib/ki2/transactions").glob("*.json"))
            self.assertTrue(transactions)
            last_tx = json.loads(sorted(transactions)[-1].read_text(encoding="utf-8"))
            self.assertEqual(last_tx["status"], "rolled-back")
            self.assertTrue(any(event["event"] == "rollback-complete" for event in last_tx["events"]))

    def test_temporary_repo_url_without_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            (repo / "packages/x86_64").mkdir(parents=True)
            (repo / "repo").mkdir(parents=True)
            package = repo / "packages/x86_64/tool-1-1.x86_64.ki2"
            write_ki2_package(package, name="tool", dependencies=[], files={"rootfs/usr/bin/tool": b"tool\n"})
            write_index(repo / "repo/index.x86_64.json", [package])

            info = self.run_ki2ctl(target, "--repo", repo_url, "info", "tool").stdout
            self.assertIn("Name    : tool", info)

    def test_local_file_repository_path_supports_disconnected_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            (repo / "packages/x86_64").mkdir(parents=True)
            (repo / "repo").mkdir(parents=True)
            package = repo / "packages/x86_64/tool-1-1.x86_64.ki2"
            write_ki2_package(package, name="tool", dependencies=[], files={"rootfs/usr/bin/tool": b"tool\n"})
            write_index(repo / "repo/index.x86_64.json", [package])

            self.run_ki2ctl(target, "repo", "set", str(repo))
            repos = self.run_ki2ctl(target, "repo", "list").stdout
            self.assertIn(repo.resolve().as_uri(), repos)

            update = self.run_ki2ctl(target, "update").stdout
            self.assertIn("1 packages", update)
            install = self.run_ki2ctl(target, "install", "tool").stdout
            self.assertIn("installed tool", install)
            self.assertEqual((target / "usr/bin/tool").read_text(encoding="utf-8"), "tool\n")

            removed = self.run_ki2ctl(target, "repo", "remove").stdout
            self.assertIn("removed repo default", removed)
            self.assertFalse((target / "etc/ki2/repos.d/default.repo").exists())
            self.assertFalse((target / "var/lib/ki2/repos/default").exists())

    def test_temporary_local_file_repo_without_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            (repo / "packages").mkdir(parents=True)
            (repo / "repo").mkdir(parents=True)
            package = repo / "packages/tool-1-1.x86_64.ki2"
            write_ki2_package(package, name="tool", dependencies=[], files={"rootfs/usr/bin/tool": b"tool\n"})
            write_index(repo / "repo/index.x86_64.json", [package])

            info = self.run_ki2ctl(target, "--repo", str(repo), "info", "tool").stdout
            self.assertIn("Repo    : cli", info)
            self.assertIn("Name    : tool", info)

    def test_update_can_verify_signed_repository_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            key = base / "repo-signing.key"
            repo_url = serve_directory(repo)
            (repo / "packages/x86_64").mkdir(parents=True)
            (repo / "repo").mkdir(parents=True)
            package = repo / "packages/x86_64/tool-1-1.x86_64.ki2"
            write_ki2_package(package, name="tool", dependencies=[], files={"rootfs/usr/bin/tool": b"tool\n"})
            index_path = repo / "repo/index.x86_64.json"
            write_index(index_path, [package])
            key.write_text("11" * 32 + "\n", encoding="utf-8")
            write_signed_metadata(repo / "repo/metadata.x86_64.json", index_path, key)

            self.run_ki2ctl(target, "repo", "set", repo_url)
            update = self.run_ki2ctl(target, "update", "--verify-key", str(key)).stdout
            self.assertIn("metadata verified", update)
            self.assertTrue((target / "var/lib/ki2/repos/default/metadata.x86_64.json").exists())

            metadata = json.loads((repo / "repo/metadata.x86_64.json").read_text(encoding="utf-8"))
            metadata["name"] = "tampered"
            (repo / "repo/metadata.x86_64.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            failure = self.run_ki2ctl_failure(target, "update", "--verify-key", str(key))
            self.assertIn("signature verification failed", failure.stderr)

    def test_install_records_pending_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            target = base / "target"
            repo_url = serve_directory(repo)
            repo_packages = repo / "packages"
            repo_index = repo / "repo"
            repo_packages.mkdir(parents=True)
            repo_index.mkdir(parents=True)
            package = repo_packages / "servicepkg-1-1.x86_64.ki2"
            write_ki2_package(
                package,
                name="servicepkg",
                dependencies=[],
                files={
                    "rootfs/usr/lib/libdemo.so.1": b"lib\n",
                    "rootfs/usr/lib/systemd/system/demo.service": b"[Service]\nExecStart=/bin/true\n",
                    "rootfs/usr/lib/tmpfiles.d/demo.conf": b"d /run/demo 0755 root root -\n",
                },
            )
            write_index(repo_index / "index.x86_64.json", [package])

            self.run_ki2ctl(target, "repo", "set", repo_url)
            self.run_ki2ctl(target, "update")
            self.run_ki2ctl(target, "install", "servicepkg")
            hooks = json.loads((target / "var/lib/ki2/pending-hooks.json").read_text(encoding="utf-8"))
            actions = {item["action"] for item in hooks["hooks"]}
            self.assertEqual(actions, {"ldconfig", "systemd-daemon-reload", "systemd-tmpfiles-create"})
            listing = self.run_ki2ctl(target, "hooks", "list").stdout
            self.assertIn("ldconfig", listing)
            dry_run = self.run_ki2ctl(target, "hooks", "apply", "--dry-run").stdout
            self.assertIn("would run", dry_run)


def serve_directory(directory: Path) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}"


def write_ki2_package(
    path: Path,
    *,
    name: str,
    dependencies: list[str],
    files: dict[str, bytes],
    version: str = "1",
    release: str = "1",
) -> None:
    manifest = {
        "schema": "ki2-package-v1",
        "name": name,
        "version": version,
        "release": release,
        "arch": "x86_64",
        "summary": f"{name} package",
        "dependencies": {"build": [], "runtime": dependencies},
        "payload": {"rootfs_prefix": "rootfs/", "contains_os_tree": True, "file_count": len(files)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        body = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.mode = 0o644
        info.size = len(body)
        tar.addfile(info, fileobj=BytesReader(body))
        for name, payload in files.items():
            item = tarfile.TarInfo(name)
            item.mode = 0o755 if name.startswith("rootfs/usr/bin/") else 0o644
            item.size = len(payload)
            tar.addfile(item, fileobj=BytesReader(payload))


def write_broken_ki2_package(path: Path) -> None:
    manifest = {
        "schema": "ki2-package-v1",
        "name": "broken",
        "version": "1",
        "release": "1",
        "arch": "x86_64",
        "summary": "broken package",
        "dependencies": {"build": [], "runtime": []},
        "payload": {"rootfs_prefix": "rootfs/", "contains_os_tree": True, "file_count": 2},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        body = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.mode = 0o644
        info.size = len(body)
        tar.addfile(info, fileobj=BytesReader(body))
        payload = b"good\n"
        good = tarfile.TarInfo("rootfs/usr/bin/good")
        good.mode = 0o755
        good.size = len(payload)
        tar.addfile(good, fileobj=BytesReader(payload))
        bad = tarfile.TarInfo("rootfs/usr/bin/bad")
        bad.type = tarfile.LNKTYPE
        bad.linkname = "rootfs/usr/bin/missing"
        bad.mode = 0o755
        bad.size = 0
        tar.addfile(bad)


def write_index(path: Path, packages: list[Path]) -> None:
    items = []
    for package in packages:
        with tarfile.open(package, "r:gz") as tar:
            manifest_file = tar.extractfile("manifest.json")
            assert manifest_file is not None
            manifest = json.loads(manifest_file.read().decode("utf-8"))
        items.append(
            {
                "name": manifest["name"],
                "version": manifest["version"],
                "release": manifest["release"],
                "arch": manifest["arch"],
                "file": package.name,
                "size": package.stat().st_size,
                "sha256": sha256(package),
                "summary": manifest["summary"],
                "dependencies": manifest["dependencies"],
                "runtime_dependencies": manifest["dependencies"]["runtime"],
                "file_count": manifest["payload"]["file_count"],
            }
        )
    index = {
        "schema": "ki2-repository-v1",
        "arch": "x86_64",
        "created_at": "2026-05-25T00:00:00+00:00",
        "packages": items,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_json_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_signed_metadata(path: Path, index_path: Path, key_path: Path) -> None:
    key = bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
    metadata = {
        "schema": "ki2-repository-metadata-v1",
        "name": "test",
        "arch": "x86_64",
        "channel": "stage2-v2",
        "created_at": "2026-05-25T00:00:00+00:00",
        "index": {
            "path": "repo/index.x86_64.json",
            "size": index_path.stat().st_size,
            "sha256": sha256(index_path),
            "package_count": 1,
        },
        "security": {
            "signed": True,
            "algorithm": "hmac-sha256",
            "key_id": hashlib.sha256(key).hexdigest()[:16],
            "signed_at": "2026-05-25T00:00:00+00:00",
            "signature": None,
        },
    }
    signature = hmac.new(key, canonical_json_bytes(metadata), hashlib.sha256).hexdigest()
    metadata["security"]["signature"] = signature
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


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
