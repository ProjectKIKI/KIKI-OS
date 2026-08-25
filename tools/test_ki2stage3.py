from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "ki2stage3.py"
SPEC = importlib.util.spec_from_file_location("ki2stage3", SCRIPT)
ki2stage3 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ki2stage3
SPEC.loader.exec_module(ki2stage3)


class Ki2Stage3Tests(unittest.TestCase):
    def test_repository_contract(self):
        result = ki2stage3.verify_contract(SCRIPT.parents[1])
        self.assertEqual(result["profiles"], 4)
        self.assertEqual(result["defaults"], 3)
        self.assertTrue(result["recipe"].startswith("kiki-agent-"))
        self.assertEqual(
            result["source_promotions"],
            ["bridge-utils", "chrony", "conntrack-tools", "ethtool", "firewalld", "iptables", "nftables", "socat"],
        )
        self.assertEqual(
            result["firewall_runtime_sources"],
            ["dbus", "glib", "gobject-introspection", "python", "python-setuptools", "python3-dbus", "python3-gobject"],
        )
        self.assertEqual(
            result["hardened_foundation_releases"],
            {
                "zlib": 3,
                "expat": 3,
                "openssl": 5,
                "xz": 3,
                "python": 5,
                "python-setuptools": 2,
                "python3-dbus": 3,
                "python3-gobject": 3,
                "firewalld": 10,
            },
        )
        self.assertEqual(result["host_file_recipes"], [])
        self.assertEqual(result["management_console"], "tools/kiki_console.py")
        self.assertEqual(result["on_device_ai_console"], "tty1")
        self.assertEqual(result["bundled_model"], "Qwen2.5-1.5B-Instruct-Q4_K_M")
        self.assertEqual(result["recovery_shell"], "tty2")


if __name__ == "__main__":
    unittest.main()
