"""Compile the GTK progress validator and exercise malformed backend records."""
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


class GtkProgressTests(unittest.TestCase):
    def test_actual_validator_rejects_false_completion(self):
        if not shutil.which('cc') or not shutil.which('pkg-config'):
            self.skipTest('C compiler and GLib development files required')
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'glib-2.0'],
                               capture_output=True, text=True)
        if flags.returncode:
            self.skipTest('GLib development files required')
        source = (Path(__file__).resolve().parents[1] / 'cmd/kiki-installer-gtk/main.c').read_text()
        function = source.split('static gboolean valid_install_progress(', 1)[1]
        function = 'static gboolean valid_install_progress(' + function.split('\nstatic void append_progress_log', 1)[0]
        harness = '#include <glib.h>\n#include <string.h>\n' + function + r'''
#define BASE "version=1\nstate=completed\npercent=100\npackages_installed=2\npackages_total=2\n"
int main(void) {
    const char *valid[] = {
        BASE, BASE "message=설치 완료\npackage=\n",
        "version=1\nstate=running\npercent=45\npackages_installed=0\npackages_total=2\n",
        "version=1\nstate=failed\npercent=1\npackages_installed=0\npackages_total=0\n"
    };
    const char *invalid[] = {
        "", "state=completed\n", BASE "state=failed\n", BASE "version=1\n",
        BASE "broken", BASE "=value\n", BASE "message=x\nmessage=y\n",
        "version=2\nstate=completed\npercent=100\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=completed\npercent=99\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=completed\npercent=100\npackages_installed=1\npackages_total=2\n",
        "version=1\nstate=rebooting\npercent=100\npackages_installed=1\npackages_total=2\n",
        "version=1\nstate=running\npercent=101\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=running\npercent=+1\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=running\npercent= 1\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=running\npercent=1x\npackages_installed=2\npackages_total=2\n",
        "version=1\nstate=running\npercent=1\npackages_installed=-1\npackages_total=2\n",
        "version=1\nstate=running\npercent=1\npackages_installed=3\npackages_total=2\n",
        "version=1\nstate=running\npercent=1\npackages_installed=0\npackages_total=99999999999999999999999\n",
        "version=1\nstate=unknown\npercent=1\npackages_installed=0\npackages_total=2\n",
        BASE "message=\xff\n"
    };
    for (gsize i=0; i<G_N_ELEMENTS(valid); i++)
        if (!valid_install_progress(valid[i], strlen(valid[i]))) return 1;
    for (gsize i=0; i<G_N_ELEMENTS(invalid); i++)
        if (valid_install_progress(invalid[i], strlen(invalid[i]))) return 2;
    const char embedded[] = BASE "\0ignored";
    if (valid_install_progress(embedded, sizeof(embedded)-1)) return 3;
    char oversized[16386]; memset(oversized, 'x', sizeof(oversized));
    oversized[sizeof(oversized)-1]=0;
    if (valid_install_progress(oversized, sizeof(oversized)-1)) return 4;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kiki-gtk-progress-') as tmp:
            path, binary = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
            path.write_text(harness)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)] +
                           shlex.split(flags.stdout), check=True)
            subprocess.run([str(binary)], check=True, timeout=10)
        poll = source.split('static gboolean poll_install_progress(', 1)[1].split('static void request_reboot', 1)[0]
        self.assertLess(poll.index('!valid_install_progress(contents, length)'),
                        poll.index('ui->install_complete = TRUE'))


if __name__ == '__main__':
    unittest.main()
