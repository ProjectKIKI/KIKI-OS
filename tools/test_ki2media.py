import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import ki2media
import ki2repo


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required")
class MediaTests(unittest.TestCase):
    def test_signed_media_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "media"
            repo = root / "kiki/repo"
            packages = root / "kiki/packages/x86_64"
            repo.mkdir(parents=True)
            packages.mkdir(parents=True)
            private = base / "test-private.pem"
            public = base / "test-public.pem"
            ki2repo.run_openssl(["genpkey", "-algorithm", "ED25519", "-out", str(private)])
            ki2repo.run_openssl(["pkey", "-in", str(private), "-pubout", "-out", str(public)])
            payload = b"test package"
            package = packages / "test-1.ki2"
            package.write_bytes(payload)
            index = json.dumps({"arch": "x86_64", "packages": [{
                "file": package.name, "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}]}).encode()
            index_path = repo / "index.x86_64.json"
            index_path.write_bytes(index)
            metadata = {"arch": "x86_64", "index": {
                "size": len(index), "sha256": hashlib.sha256(index).hexdigest()}}
            signed = ki2repo.sign_metadata_ed25519(metadata, private)
            metadata_path = repo / "metadata.x86_64.json"
            metadata_path.write_text(json.dumps(signed), encoding="utf-8")
            self.assertEqual(ki2media.verify_media(root, public), 1)
            package.write_bytes(b"bad! package")
            with self.assertRaisesRegex(ki2media.MediaError, "integrity mismatch"):
                ki2media.verify_media(root, public)
            package.unlink()
            with self.assertRaisesRegex(ki2media.MediaError, "missing"):
                ki2media.verify_media(root, public)
            package.write_bytes(payload)
            index_path.write_bytes(index + b" ")
            with self.assertRaisesRegex(ki2media.MediaError, "repository index"):
                ki2media.verify_media(root, public)
            index_path.write_bytes(index)
            signed["channel"] = "tampered"
            metadata_path.write_text(json.dumps(signed), encoding="utf-8")
            with self.assertRaisesRegex(ki2media.MediaError, "Ed25519"):
                ki2media.verify_media(root, public)
            media_key = root / "attacker.pub"
            media_key.write_bytes(public.read_bytes())
            with self.assertRaisesRegex(ki2media.MediaError, "trust key"):
                ki2media.verify_media(root, media_key)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ki2media.MediaError):
            ki2media.read_json_bytes(b'{"size":1,"size":2}')


if __name__ == "__main__":
    unittest.main()
