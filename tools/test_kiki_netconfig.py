from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import runpy
import io
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/kiki-netconfig/usr/bin/kiki-netconfig"
MODULE = runpy.run_path(str(SCRIPT))


class TuiTests(unittest.TestCase):
    def run_tui(self, root, answers, preview=False):
        args = MODULE['build_parser']().parse_args(['--root', str(root), 'tui'] + (['--dry-run'] if preview else []))
        devices = [{'ifname': 'eth0', 'operstate': 'UP', 'addr_info': []}]
        with patch.dict(MODULE['command_tui'].__globals__, interfaces=lambda: devices), patch('builtins.input', side_effect=answers), redirect_stdout(io.StringIO()):
            return MODULE['command_tui'](args)

    def test_cancel_and_preview_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_tui(root, ['']), 0)
            self.assertEqual(self.run_tui(root, ['1', '1', '']), 0)
            self.assertEqual(self.run_tui(root, ['1', '2', '10.0.2.15/24', '10.0.2.2', '10.0.2.3', ''], True), 0)
            self.assertEqual(list(root.iterdir()), [])

    def test_save_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_tui(root, ['1', '1', 's'])
            target = root / 'etc/systemd/network/10-kiki-eth0.network'
            old = target.read_bytes()
            self.run_tui(root, ['1', '2', '10.0.2.15/24', '10.0.2.2', '10.0.2.3', 's'])
            self.assertIn('Address=10.0.2.15/24', target.read_text())
            self.assertEqual(next(target.parent.glob('*.bak-*')).read_bytes(), old)

    def test_refuses_unmanaged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'etc/systemd/network/10-kiki-eth0.network'
            target.parent.mkdir(parents=True)
            target.write_text('# user configuration\n')
            with self.assertRaises(ValueError):
                MODULE['save_tui_profile'](Path(tmp), 'eth0', 'replacement')
            self.assertEqual(target.read_text(), '# user configuration\n')

    def test_static_validation(self):
        for address, gateway, dns in [('10.0.2.15', '', []), ('10.0.2.15/24', '192.168.1.1', []), ('10.0.2.15/24', '', ['bad']), ('127.0.0.1/8', '', [])]:
            with self.subTest(address=address, gateway=gateway, dns=dns), self.assertRaises(ValueError):
                MODULE['validate_static_settings'](address, gateway, dns)

    def test_apply_requires_exact_confirmation(self):
        with patch.dict(MODULE['command_tui'].__globals__, save_tui_profile=lambda *a: self.fail('must not save')):
            self.assertEqual(self.run_tui(Path('/'), ['1', '1', 'a', 'no']), 0)


class KikiNetconfigTests(unittest.TestCase):
    def run_tool(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *args],
            text=True,
            capture_output=True,
            check=True,
        )

    def network_file(self, root: Path) -> Path:
        return root / "etc/systemd/network/20-kiki.network"

    def test_writes_dhcp_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = self.run_tool(root, "dhcp")
            text = self.network_file(root).read_text(encoding="utf-8")

            self.assertIn("wrote DHCP network profile", result.stdout)
            self.assertIn("Name=en* eth*", text)
            self.assertIn("DHCP=ipv4", text)
            self.assertIn("IPv6AcceptRA=yes", text)

    def test_writes_static_profile_with_dns_dropin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.run_tool(
                root,
                "static",
                "--match",
                "eth0",
                "--address",
                "192.168.122.50/24",
                "--gateway",
                "192.168.122.1",
                "--dns",
                "1.1.1.1,8.8.8.8",
                "--ntp",
                "time.cloudflare.com",
                "--write-resolved-dropin",
            )
            text = self.network_file(root).read_text(encoding="utf-8")
            resolved = (root / "etc/systemd/resolved.conf.d/10-kiki-dns.conf").read_text(encoding="utf-8")

            self.assertIn("Name=eth0", text)
            self.assertIn("Address=192.168.122.50/24", text)
            self.assertIn("Gateway=192.168.122.1", text)
            self.assertIn("DNS=1.1.1.1", text)
            self.assertIn("DNS=8.8.8.8", text)
            self.assertIn("NTP=time.cloudflare.com", text)
            self.assertIn("IPv6AcceptRA=no", text)
            self.assertIn("DNS=1.1.1.1 8.8.8.8", resolved)

    def test_off_profile_disables_autoconfiguration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.run_tool(root, "off", "--match", "enp0s3")
            text = self.network_file(root).read_text(encoding="utf-8")

            self.assertIn("Name=enp0s3", text)
            self.assertIn("DHCP=no", text)
            self.assertIn("LinkLocalAddressing=no", text)
            self.assertIn("IPv6AcceptRA=no", text)

    def test_dry_run_does_not_write_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = self.run_tool(root, "dhcp", "--dry-run")

            self.assertIn("DHCP=ipv4", result.stdout)
            self.assertFalse(self.network_file(root).exists())

    def test_rejects_invalid_static_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "static", "--address", "bad-address"],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("kiki-netconfig:", result.stderr)


if __name__ == "__main__":
    unittest.main()
