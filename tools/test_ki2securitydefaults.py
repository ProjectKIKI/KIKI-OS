from pathlib import Path
import tempfile
import unittest
from unittest import mock
import ki2desktopdefaults as desktop
import ki2readlinepayload as readline
import ki2sshpolicy as ssh

ROOT=Path(__file__).resolve().parents[1]


class SecurityDefaultsTests(unittest.TestCase):
    def test_ssh_policy_is_first_global_setting_and_keeps_custom_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);conf=root/'etc/ssh/sshd_config';conf.parent.mkdir(parents=True)
            original='Port 2200\nPermitRootLogin yes\nMatch User example\n    X11Forwarding no\n';conf.write_text(original)
            source=ROOT/'distro/sources/openssh-policy'
            ssh.prepare(root,source);ssh.prepare(root,source)
            self.assertEqual(conf.read_text(),ssh.INCLUDE+original)
            self.assertIn('PermitRootLogin no',(root/'etc/ssh/sshd_config.d/00-kiki-defaults.conf').read_text())

    def test_ssh_policy_does_not_follow_external_symlinks(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            root=Path(a);(root/'etc/ssh').mkdir(parents=True)
            other=Path(b)/'config';other.write_text('keep\n');(root/'etc/ssh/sshd_config').symlink_to(other)
            with self.assertRaises(ValueError):ssh.prepare(root,ROOT/'distro/sources/openssh-policy')
            self.assertEqual(other.read_text(),'keep\n')

    def test_readline_backup_cannot_be_selected_after_ldconfig(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lib=root/'usr/lib';lib.mkdir(parents=True)
            for name in ('libreadline','libhistory'):
                (lib/(name+'.so.8.3')).write_bytes(b'ELF fixture')
                (lib/(name+'.so.8.3.old')).write_bytes(b'old broken ELF')
                (lib/(name+'.so.8')).symlink_to(name+'.so.8.3.old')
            with mock.patch.object(readline.subprocess,'check_output',return_value='(NEEDED) Shared library: [libncursesw.so.6]'):
                self.assertEqual(len(readline.prepare(root)),2)
            self.assertFalse(list(lib.glob('*.old')))
            self.assertEqual((lib/'libreadline.so.8').readlink(),Path('libreadline.so.8.3'))

    def test_readline_rejects_missing_native_terminal_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lib=root/'usr/lib';lib.mkdir(parents=True);(lib/'libreadline.so.8.3').write_bytes(b'fixture')
            with mock.patch.object(readline.subprocess,'check_output',return_value='(NEEDED) Shared library: [libc.so.6]'):
                with self.assertRaisesRegex(ValueError,'native wide-character'):readline.prepare(root)

    def test_desktop_payload_enables_services_without_global_ruleset_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'payload';desktop.stage(ROOT/'distro/sources/kiki-desktop-defaults',root)
            desktop.stage(ROOT/'distro/sources/kiki-desktop-defaults',root)
            for name,target in desktop.LINKS.items():self.assertEqual((root/name).readlink(),Path(target))
            policy=(root/'etc/kiki/desktop-firewall.nft').read_text()
            self.assertNotIn('flush ruleset',policy)
            self.assertIn('policy drop',policy)
            self.assertIn('tcp dport 22',policy)
            self.assertIn('udp dport 68',policy)
            self.assertIn('udp dport 546',policy)
            self.assertIn('ct state established,related accept',policy)
            self.assertIn('meta l4proto { 1, 58 } accept',policy)
            override=(root/'etc/systemd/system/sshd.service.d/20-kiki-desktop-firewall.conf').read_text()
            self.assertIn('Requires=kiki-desktop-firewall.service',override)


if __name__=='__main__':unittest.main()
