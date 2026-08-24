from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/ki2ctl/usr/bin/ki2ctl"
SPEC = importlib.util.spec_from_file_location("ki2ctl_ed25519", SCRIPT)
if SPEC is None:
    from importlib.machinery import SourceFileLoader

    SPEC = importlib.util.spec_from_loader("ki2ctl_ed25519", SourceFileLoader("ki2ctl_ed25519", str(SCRIPT)))
ki2ctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ki2ctl
SPEC.loader.exec_module(ki2ctl)


class Ki2CtlEd25519Tests(unittest.TestCase):
    def test_rfc8032_empty_message_vector(self):
        public_key = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a"
            "0ee172f3daa62325af021a68f707511a"
        )
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a"
            "84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46b"
            "d25bf5f0595bbe24655141438e7a100b"
        )
        self.assertTrue(ki2ctl.verify_ed25519(public_key, b"", signature))
        self.assertFalse(ki2ctl.verify_ed25519(public_key, b"tampered", signature))

    def test_rejects_noncanonical_scalar(self):
        public_key = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a"
            "0ee172f3daa62325af021a68f707511a"
        )
        signature = bytearray(64)
        signature[32:] = ki2ctl.ED25519_L.to_bytes(32, "little")
        self.assertFalse(ki2ctl.verify_ed25519(public_key, b"", bytes(signature)))


if __name__ == "__main__":
    unittest.main()
