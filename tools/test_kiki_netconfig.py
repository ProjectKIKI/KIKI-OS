from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/kiki-netconfig/usr/bin/kiki-netconfig"


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
