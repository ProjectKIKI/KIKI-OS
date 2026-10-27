import tempfile
from pathlib import Path
import unittest
import ki2x11
import ki2build


class X11RuntimeTests(unittest.TestCase):
    def test_no_conflicting_base_files_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/"a", Path(directory)/"b"
            a.write_bytes(b"same")
            b.write_bytes(b"same")
            self.assertTrue(ki2x11.same_file(a,b))
            b.write_bytes(b"different")
            self.assertFalse(ki2x11.same_file(a,b))

    def test_session_requires_local_tty_and_cookie(self):
        repo = Path(__file__).resolve().parents[1]
        script = (repo/"distro/sources/kiki-x11/usr/bin/kiki-startx").read_text()
        for required in ["-nolisten tcp", 'MIT-MAGIC-COOKIE-1', '-auth "$XAUTHORITY"', '/dev/tty[0-9]*']:
            self.assertIn(required,script)
        self.assertNotIn("xhost +",script)
        self.assertNotIn(" -ac",script)
        recipe = ki2build.load_recipes(repo/"distro/recipes")["kiki-x11-runtime"]
        self.assertIn("kiki-installer-gtk",recipe.dependencies["runtime"])


if __name__ == "__main__":
    unittest.main()
