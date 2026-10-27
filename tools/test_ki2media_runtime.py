"""Opt-in real-package chroot test. No device mounts or disk writes."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import ki2bootiso
import ki2repo


@unittest.skipUnless(os.environ.get("KIKI_TEST_MEDIA_RUNTIME") == "1",
                     "requires explicit KIKI_TEST_MEDIA_RUNTIME=1 and Linux root")
class MediaRuntimeTests(unittest.TestCase):
    def test_real_runtime_accepts_signed_media_and_rejects_damage(self):
        self.assertEqual(os.geteuid(), 0, "chroot requires Linux root")
        repo_root = Path(__file__).resolve().parents[1]
        packages = Path(os.environ.get("KIKI_TEST_PACKAGES", str(repo_root / "dist/ki2/packages/x86_64")))
        with tempfile.TemporaryDirectory(prefix="kiki-media-runtime-") as tmp:
            base = Path(tmp)
            root = base / "root"
            root.mkdir()
            (root / "tmp").mkdir(mode=0o1777)
            private, public = base / "private.pem", base / "public.pem"
            ki2repo.run_openssl(["genpkey", "-algorithm", "ED25519", "-out", str(private)])
            ki2repo.run_openssl(["pkey", "-in", str(private), "-pubout", "-out", str(public)])
            ki2bootiso.add_installer_runtime(root, packages)
            ki2bootiso.add_media_verifier(root, packages, public)
            # Exercise the assembled GUI+verifier runtime: GTK can shadow the
            # partitioner's ABI even when every archive member is present.
            for tool, option in (("/sbin/sfdisk", "--version"), ("/usr/sbin/mkfs.ext4", "-V")):
                probe = subprocess.run(["chroot", str(root), tool, option], capture_output=True,
                                       text=True, timeout=30)
                self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            media = root / "media"
            index_dir = media / "kiki/repo"
            package_dir = media / "kiki/packages/x86_64"
            index_dir.mkdir(parents=True)
            package_dir.mkdir(parents=True)
            payload = b"test-only package payload"
            package = package_dir / "test-1.ki2"
            package.write_bytes(payload)
            index = json.dumps({"arch": "x86_64", "packages": [{
                "file": package.name, "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}]}).encode()
            index_path = index_dir / "index.x86_64.json"
            index_path.write_bytes(index)
            metadata = ki2repo.sign_metadata_ed25519({"arch": "x86_64", "index": {
                "size": len(index), "sha256": hashlib.sha256(index).hexdigest()}}, private)
            metadata_path = index_dir / "metadata.x86_64.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            command = ["chroot", str(root), "/usr/bin/python3", "-B",
                       "/usr/lib/kiki-installer/ki2media.py", "--media-root", "/media",
                       "--public-key", "/etc/ki2/trust/installer-repo.ed25519.pub"]
            def run():
                return subprocess.run(command, capture_output=True, text=True, timeout=60,
                                      env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"})
            valid = run()
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn("1 packages", valid.stdout)
            package.write_bytes(b"X" * len(payload))
            corrupt = run()
            self.assertEqual(corrupt.returncode, 1, corrupt.stderr)
            self.assertIn("integrity mismatch", corrupt.stderr)
            package.unlink()
            missing = run()
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertIn("missing", missing.stderr)
            package.write_bytes(payload)
            index_path.write_bytes(index + b" ")
            changed = run()
            self.assertEqual(changed.returncode, 1, changed.stderr)
            self.assertIn("repository index", changed.stderr)
            index_path.write_bytes(index)
            metadata["channel"] = "tampered"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            unsigned = run()
            self.assertEqual(unsigned.returncode, 1, unsigned.stderr)
            self.assertIn("Ed25519", unsigned.stderr)


if __name__ == "__main__":
    unittest.main()
