import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


class DesktopToolsUITests(unittest.TestCase):
    def test_settings_and_files(self):
        if sys.platform != 'linux' or not all(shutil.which(t) for t in ('cc', 'pkg-config', 'xvfb-run')):
            self.skipTest('Native GTK and Xvfb required')
        flags=subprocess.run(['pkg-config','--cflags','--libs','gtk4'],capture_output=True,text=True)
        if flags.returncode: self.skipTest('GTK4 headers required')
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='kiki-tools-ui-') as tmp:
            binary=Path(tmp)/'ui-test'
            subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror',str(repo/'cmd/kiki-desktop-tools/ui_test.c'),'-o',str(binary),*shlex.split(flags.stdout)],check=True)
            artifacts=Path(os.environ.get('KIKI_GTK_TEST_ARTIFACTS',tmp))
            artifacts.mkdir(parents=True,exist_ok=True)
            env=dict(os.environ,GSETTINGS_BACKEND='memory',GDK_BACKEND='x11',GSK_RENDERER='cairo',GTK_A11Y='none')
            result=subprocess.run(['xvfb-run','-a',str(binary),str(artifacts)],env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS:',result.stdout)


if __name__=='__main__': unittest.main()
