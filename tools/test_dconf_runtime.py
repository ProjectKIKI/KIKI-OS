"""KIKI package runtime test on a private bus/config directory, not a desktop/ISO test."""
import os
import selectors
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_DCONF_RUNTIME") == "1",
                     "set KIKI_TEST_DCONF_RUNTIME=1 on Linux")
class DconfRuntimeTest(unittest.TestCase):
    def test_private_session_settings_persist_across_clients(self):
        self.check_private_session(autostart=False)

    def test_private_bus_activates_relocated_packaged_service(self):
        self.check_private_session(autostart=True)

    def test_gnome_desktop_settings_persist_with_compiled_schemas(self):
        self.check_private_session(autostart=True, desktop=True)

    def check_private_session(self, autostart, desktop=False):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        packages = ["dconf", "gsettings-desktop-schemas"] if desktop else ["dconf"]
        ordered = ki2build.dependency_closure(recipes, packages, "x86_64", include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix="kiki-dconf-test-") as tmp:
            work = Path(tmp)
            root = work / "root"
            for name in ordered:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1, str(loaders))
            library_path = ":".join(str(root / p) for p in ("usr/lib", "lib", "usr/lib64", "lib64"))

            def command(binary, *args):
                return [str(loaders[0]), "--inhibit-cache", "--library-path", library_path,
                        str(root / binary), *args]

            for dirname in ("home", "config", "runtime", "schemas"):
                (work / dirname).mkdir(mode=0o700)
            profile = work / "dconf-profile"
            profile.write_text("user-db:user\n")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(work / "home"),
                   "XDG_CONFIG_HOME": str(work / "config"), "XDG_RUNTIME_DIR": str(work / "runtime"),
                   "GSETTINGS_SCHEMA_DIR": str(work / "schemas"), "GSETTINGS_BACKEND": "dconf",
                   "GIO_MODULE_DIR": str(root / "usr/lib/gio/modules"), "LC_ALL": "C.UTF-8"}
            env["DCONF_PROFILE"] = str(profile)
            service_dir = work / "services"
            service_dir.mkdir()
            packaged_service = (root / "usr/share/dbus-1/services/ca.desrt.dconf.service").read_text()
            self.assertIn("Name=ca.desrt.dconf", packaged_service)
            self.assertIn("Exec=/usr/libexec/dconf-service", packaged_service)
            self.assertIn("SystemdService=dconf.service", packaged_service)
            self.assertIn("ExecStart=/usr/libexec/dconf-service",
                          (root / "usr/lib/systemd/user/dconf.service").read_text())
            if autostart:
                # Relocate only Exec for a non-chroot test; never install into the host service directory.
                relocated = packaged_service.replace("Exec=/usr/libexec/dconf-service",
                    "Exec=" + shlex.join(command("usr/libexec/dconf-service")))
                (service_dir / "ca.desrt.dconf.service").write_text(relocated)
            config = work / "bus.conf"
            config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' +
                              str(work / "runtime") + '</listen><auth>EXTERNAL</auth>'
                              '<servicedir>' + str(service_dir) + '</servicedir>'
                              '<policy context="default"><allow own="*"/><allow send_destination="*"/>'
                              '<allow receive_sender="*"/></policy></busconfig>')
            schema = work / "schemas/org.kiki.Test.gschema.xml"
            schema.write_text('<schemalist><schema id="org.kiki.Test" path="/org/kiki/test/">'
                              '<key name="counter" type="i"><default>0</default></key>'
                              '</schema></schemalist>')
            if desktop:
                packaged = root / "usr/share/glib-2.0/schemas"
                shutil.copyfile(schema, packaged / schema.name)
                env["GSETTINGS_SCHEMA_DIR"] = str(packaged)
                self.assertTrue((packaged / "org.gnome.desktop.interface.gschema.xml").is_file())
                self.assertTrue((root / "usr/lib/girepository-1.0/GDesktopEnums-3.0.typelib").is_file())
                ki2build.refresh_rootfs_gsettings_cache(root, "x86_64")
                self.assertTrue((packaged / "gschemas.compiled").is_file())
            else:
                subprocess.run(command("usr/bin/glib-compile-schemas", "--strict", str(schema.parent)),
                               env=env, check=True, timeout=15)
            with (work / "session.log").open("w+") as log:
                bus = subprocess.Popen(command("usr/bin/dbus-daemon", "--nofork", "--print-address=1",
                                               "--config-file=" + str(config)),
                                       env=env, stdout=subprocess.PIPE, stderr=log, text=True)
                service = None
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(bus.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(10), "private bus startup timed out")
                    address = bus.stdout.readline().strip()
                    self.assertTrue(address.startswith("unix:"), "private bus failed to start")
                    env["DBUS_SESSION_BUS_ADDRESS"] = address
                    if not autostart:
                        service = subprocess.Popen(command("usr/libexec/dconf-service"), env=env,
                                                   stdout=log, stderr=log)

                    def run(binary, *args):
                        result = subprocess.run(command(binary, *args), env=env, capture_output=True,
                                                text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        return result.stdout.strip()

                    if not autostart:
                        run("usr/bin/gdbus", "wait", "--session", "--timeout=10", "ca.desrt.dconf")
                    run("usr/bin/gsettings", "set", "org.kiki.Test", "counter", "42")
                    self.assertEqual(run("usr/bin/dconf", "read", "/org/kiki/test/counter"), "42")
                    self.assertEqual(run("usr/bin/gsettings", "get", "org.kiki.Test", "counter"), "42")
                    self.assertTrue((work / "config/dconf/user").is_file())
                    if desktop:
                        self.assertIn("org.gnome.desktop.interface", run("usr/bin/gsettings", "list-schemas").splitlines())
                        run("usr/bin/gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "prefer-dark")
                        self.assertEqual(run("usr/bin/gsettings", "get", "org.gnome.desktop.interface", "color-scheme"), "'prefer-dark'")
                        self.assertEqual(run("usr/bin/dconf", "read", "/org/gnome/desktop/interface/color-scheme"), "'prefer-dark'")
                        run("usr/bin/gsettings", "reset", "org.gnome.desktop.interface", "color-scheme")
                        self.assertEqual(run("usr/bin/dconf", "read", "/org/gnome/desktop/interface/color-scheme"), "")
                finally:
                    for process in (service, bus):
                        if process is not None:
                            if process.poll() is None:
                                process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                    if bus.stdout:
                        bus.stdout.close()


if __name__ == "__main__":
    unittest.main()
