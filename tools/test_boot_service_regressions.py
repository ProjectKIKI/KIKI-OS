"""Checks for the swap applet collision and local console boot ordering."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
import ki2build

ROOT = Path(__file__).resolve().parents[1]


class BootServiceTests(unittest.TestCase):
    def test_dnssec_compatibility_default_in_base_and_installer(self):
        base = (ROOT / 'distro/sources/base-files/etc/systemd/resolved.conf').read_text()
        installer = (ROOT / 'tools/ki2bootiso.py').read_text()
        self.assertIn('DNSSEC=no', base)
        self.assertIn('DNSSEC=no\\n', installer)
        self.assertNotIn('DNSSEC=allow-downgrade', base)
        self.assertNotIn('DNSSEC=allow-downgrade', installer)

    def test_busybox_does_not_replace_systemd_swap_tools(self):
        recipe = ki2build.load_recipes(ROOT / 'distro/recipes')['busybox']
        install = '\n'.join(recipe.build['install'])
        self.assertIn('CONFIG_PREFIX=${KI2_DESTDIR} install', install)
        for name in ('swapon', 'swapoff', 'mkswap'):
            self.assertIn('${KI2_DESTDIR}/sbin/' + name, install)

    def test_network_wait_is_bounded_and_ipv4_matches_default(self):
        path = ROOT / 'distro/sources/base-files/etc/systemd/system/systemd-networkd-wait-online.service.d/20-kiki-timeout.conf'
        text = path.read_text()
        self.assertIn('--any --ipv4 --timeout=30', text)
        self.assertIn('TimeoutStartSec=35s', text)

    def test_local_ai_does_not_wait_for_external_network(self):
        text = (ROOT / 'distro/sources/kiki-ai-console/etc/systemd/system/kiki-ai-console@.service').read_text()
        after = next(line for line in text.splitlines() if line.startswith('After='))
        self.assertNotIn('network-online.target', after)
        self.assertIn('kiki-llama-server.service', after)

    def test_ai_console_keeps_native_tty_and_declares_hangul_terminal_provider(self):
        text = (ROOT / 'distro/sources/kiki-ai-console/etc/systemd/system/kiki-ai-console@.service').read_text()
        self.assertIn('ExecStart=/usr/bin/kiki-ai-console', text)
        self.assertIn('StandardOutput=tty', text)
        self.assertNotIn('kiki-kmscon', text)
        recipe = ki2build.load_recipes(ROOT / 'distro/recipes')['kiki-ai-console']
        # Keep the native TTY unit available; the Hangul unit needs its declared provider.
        alternate = (ROOT / 'distro/sources/kiki-ai-console/etc/systemd/system/kiki-ai-console-kmscon@.service').read_text()
        self.assertIn('kiki-kmscon', alternate)
        self.assertIn('kiki-kmscon', recipe.dependencies['runtime'])

    def test_dbus_daemon_controls_its_own_privilege_drop(self):
        text = (ROOT / 'distro/sources/base-files/usr/lib/systemd/system/dbus.service').read_text()
        self.assertNotIn('\nUser=messagebus', text)
        self.assertIn('ExecStart=/usr/bin/dbus-daemon --system', text)
        self.assertIn('Requires=dbus.socket', text)
        self.assertIn('--address=systemd:', text)
        self.assertIn('--systemd-activation', text)
        socket = (ROOT / 'distro/sources/base-files/usr/lib/systemd/system/dbus.socket').read_text()
        self.assertIn('ListenStream=/run/dbus/system_bus_socket', socket)

    def test_systemd_dbus_paths_do_not_inherit_build_sysroot(self):
        recipe = ki2build.load_recipes(ROOT / 'distro/recipes')['systemd']
        options = recipe.build['configure_options']
        self.assertIn('-Ddbuspolicydir=/usr/share/dbus-1/system.d', options)
        self.assertIn('-Ddbussystemservicedir=/usr/share/dbus-1/system-services', options)
        self.assertTrue(any(option.startswith('-Dc_args=') and '--sysroot=${KI2_SYSROOT}' in option for option in options))

    def test_dbus_explicitly_requires_systemd_support_without_a_cycle(self):
        recipes = ki2build.load_recipes(ROOT / 'distro/recipes')
        self.assertIn('--enable-systemd', recipes['dbus'].build['configure_options'])
        self.assertIn('systemd', recipes['dbus'].dependencies['runtime'])
        self.assertNotIn('dbus', recipes['systemd'].dependencies['runtime'])
        ki2build.dependency_closure(recipes, ['dbus', 'systemd'], 'x86_64', include_build_deps=True)

    def test_case_insensitive_archive_collision_fails(self):
        original = Path.exists
        def exists(path):
            return True if path.name == 'casesensitive' else original(path)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'exists', exists):
                with self.assertRaisesRegex(ki2build.Ki2Error, 'case-sensitive Linux'):
                    ki2build.check_archive_case_collisions(
                        ['config/FirewallD.conf', 'config/firewalld.conf'], Path(directory))

    def test_case_insensitive_noncolliding_archive_is_allowed(self):
        original = Path.exists
        def exists(path):
            return True if path.name == 'casesensitive' else original(path)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'exists', exists):
                ki2build.check_archive_case_collisions(
                    ['config/FirewallD.conf', 'other/firewalld.conf'], Path(directory))


if __name__ == '__main__':
    unittest.main()
