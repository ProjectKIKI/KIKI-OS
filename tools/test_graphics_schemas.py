"""The graphics bootstrap must retain sources for target cache regeneration."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import ki2graphics

class GraphicsSchemaTests(unittest.TestCase):
    def test_missing_sources_and_cache_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "schemas", Path(tmp) / "out"
            source.mkdir()
            with self.assertRaises(ki2graphics.GraphicsError):
                ki2graphics.install_gsettings_assets(source, output)
            (source / "test.gschema.xml").write_text("<schemalist/>")
            with self.assertRaises(ki2graphics.GraphicsError):
                ki2graphics.install_gsettings_assets(source, output)
            self.assertFalse(output.exists())

    def test_copied_sources_recompile_with_overrides(self):
        compiler = shutil.which("glib-compile-schemas")
        settings = shutil.which("gsettings")
        if not compiler or not settings:
            self.skipTest("GLib tools required")
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "schemas", Path(tmp) / "out"
            source.mkdir()
            (source / "test.gschema.xml").write_text(
                '<schemalist><schema id="org.kiki.test" path="/org/kiki/test/">'
                '<key name="enabled" type="b"><default>false</default></key>'
                '</schema></schemalist>')
            (source / "test.gschema.override").write_text('[org.kiki.test]\nenabled=true\n')
            subprocess.run([compiler, "--strict", str(source)], check=True)
            ki2graphics.install_gsettings_assets(source, output)
            target = output / "usr/share/glib-2.0/schemas"
            for file in source.iterdir():
                self.assertEqual(file.read_bytes(), (target / file.name).read_bytes())
            subprocess.run([compiler, "--strict", str(target)], check=True)
            result = subprocess.run([settings, "--schemadir", str(target), "get", "org.kiki.test", "enabled"],
                                    env={"GSETTINGS_BACKEND":"memory", "PATH":"/usr/bin:/bin"},
                                    check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), "true")

if __name__ == "__main__":
    unittest.main()
