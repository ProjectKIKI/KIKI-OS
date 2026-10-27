from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "ki2stage3.py"
SPEC = importlib.util.spec_from_file_location("ki2stage3", SCRIPT)
ki2stage3 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ki2stage3
SPEC.loader.exec_module(ki2stage3)


class Ki2Stage3Tests(unittest.TestCase):
    def test_signature_smoke_uses_nonempty_verified_repository(self):
        result = ki2stage3.smoke_repository_signature(SCRIPT.parents[1])
        self.assertEqual(result["algorithm"], "ed25519")
        self.assertTrue(result["policy_enforced"])

    def test_client_crypto_process_dependency_is_rejected(self):
        repo = SCRIPT.parents[1]
        recipes = ki2stage3.load_ki2build(repo).load_recipes(repo / "distro/recipes")
        dependencies = dict(recipes["ki2ctl"].dependencies)
        dependencies["runtime"] = ["python", "install-info", "openssl"]
        recipes["ki2ctl"] = replace(recipes["ki2ctl"], dependencies=dependencies)
        module = SimpleNamespace(load_recipes=lambda path: recipes)
        with mock.patch.object(ki2stage3, "load_ki2build", return_value=module):
            with self.assertRaisesRegex(ki2stage3.Stage3Error, "crypto process dependency"):
                ki2stage3.verify_contract(repo)

    def test_host_libc_fallback_for_target_nftables_is_rejected(self):
        repo = SCRIPT.parents[1]
        recipes = ki2stage3.load_ki2build(repo).load_recipes(repo / "distro/recipes")
        build = dict(recipes["nftables"].build)
        build["sysroot_exclude"] = ["glibc"]
        recipes["nftables"] = replace(recipes["nftables"], build=build)
        module = SimpleNamespace(load_recipes=lambda path: recipes)
        with mock.patch.object(ki2stage3, "load_ki2build", return_value=module):
            with self.assertRaisesRegex(ki2stage3.Stage3Error, "target glibc"):
                ki2stage3.verify_contract(repo)

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
