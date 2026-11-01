import configparser
from pathlib import Path
import stat
import tempfile
import unittest
import ki2network


class NetworkManagerTargetTests(unittest.TestCase):
    def parse(self,**options):
        data=configparser.ConfigParser(interpolation=None)
        data.read_string(ki2network.render(interface='eth0',**options))
        return data

    def test_dhcp_tracks_mac_after_interface_rename(self):
        data=self.parse(mac='00:15:5D:01:03:55')
        self.assertEqual(data['ipv4']['method'],'auto')
        self.assertNotIn('interface-name',data['connection'])
        self.assertEqual(data['ethernet']['mac-address'],'00:15:5d:01:03:55')

    def test_static_preserves_address_gateway_and_both_dns_families(self):
        data=self.parse(mode='static',address='192.0.2.10/24',gateway='192.0.2.1',dns='1.1.1.1 2001:4860:4860::8888,8.8.8.8')
        self.assertEqual(data['ipv4']['address1'],'192.0.2.10/24,192.0.2.1')
        self.assertEqual(data['ipv4']['dns'],'1.1.1.1;8.8.8.8;')
        self.assertEqual(data['ipv6']['dns'],'2001:4860:4860::8888;')
        self.assertEqual(data['ipv4']['ignore-auto-dns'],'true')

    def test_disabled_does_not_autoconnect(self):
        data=self.parse(mode='disabled')
        self.assertEqual(data['connection']['autoconnect'],'false')
        self.assertEqual(data['ipv4']['method'],'disabled')
        self.assertEqual(data['ipv6']['method'],'disabled')

    def test_tui_default_interface_globs_use_nm_match(self):
        data=configparser.ConfigParser(interpolation=None)
        data.read_string(ki2network.render(interface='en* eth*'))
        self.assertEqual(data['match']['interface-name'],'en*;eth*;')
        self.assertNotIn('interface-name',data['connection'])
        self.assertEqual(data['ipv4']['method'],'auto')

    def test_explicit_mac_takes_precedence_over_patterns(self):
        data=configparser.ConfigParser(interpolation=None)
        data.read_string(ki2network.render(interface='en* eth*',mac='00:15:5d:01:03:55'))
        self.assertNotIn('match',data)
        self.assertEqual(data['ethernet']['mac-address'],'00:15:5d:01:03:55')

    def test_ipv6_ra_can_be_disabled(self):
        self.assertEqual(self.parse(ipv6=False)['ipv6']['method'],'disabled')

    def test_target_profile_permissions_and_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ki2network.write_target(root,interface='eth0',ntp='time.example.test')
            path=root/'etc/NetworkManager/system-connections/kiki-wired.nmconnection'
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertIn('dns=systemd-resolved',(root/'etc/NetworkManager/conf.d/20-kiki.conf').read_text())
            self.assertIn('no-auto-default=*',(root/'etc/NetworkManager/conf.d/20-kiki.conf').read_text())
            self.assertIn('NTP=time.example.test',(root/'etc/systemd/timesyncd.conf.d/20-kiki-network.conf').read_text())

    def test_rejects_invalid_values_before_writing(self):
        for options in [dict(interface='eth0\n[ipv4]'),dict(interface='en*\neth*'),dict(interface='eth0;*'),dict(interface=''),dict(interface='eth0',dns='not-an-ip'),
                        dict(interface='eth0',mac='bad'),dict(interface='eth0',mode='static',address='::1/64')]:
            with self.subTest(options=options),self.assertRaises(ValueError):ki2network.render(**options)

    def test_running_host_and_target_symlink_escape_rejected(self):
        with self.assertRaises(ValueError):ki2network.write_target('/',interface='eth0')
        with tempfile.TemporaryDirectory() as directory,tempfile.TemporaryDirectory() as outside:
            root=Path(directory);(root/'etc').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):ki2network.write_target(root,interface='eth0')


if __name__=='__main__':unittest.main()
