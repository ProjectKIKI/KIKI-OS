"""Compile the production monotonic stale-record helper, without GTK display."""
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

class GtkStaleProgressTests(unittest.TestCase):
    def test_timeout_and_recovery(self):
        if not shutil.which("cc") or not shutil.which("pkg-config"):
            self.skipTest("C compiler and GLib required")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "glib-2.0"],
                               capture_output=True, text=True)
        if flags.returncode:
            self.skipTest("GLib development files required")
        source = (Path(__file__).resolve().parents[1] / "cmd/kiki-installer-gtk/main.c").read_text()
        helper = "static gboolean progress_is_stale(" + source.split(
            "static gboolean progress_is_stale(", 1)[1].split("static gboolean poll_install_progress", 1)[0]
        harness = '#include <glib.h>\n#include <string.h>\n' + helper + r'''
int main(void) {
    char hash[65] = {0}; gint64 changed = 0;
    gint64 base = 7000000, minute = 60 * G_USEC_PER_SEC;
    if (progress_is_stale(hash, &changed, "a", 1, base)) return 1;
    if (progress_is_stale(hash, &changed, "a", 1, base + 2*minute - 1)) return 2;
    if (!progress_is_stale(hash, &changed, "a", 1, base + 2*minute)) return 3;
    if (!progress_is_stale(hash, &changed, "a", 1, base + 5*minute)) return 4;
    if (progress_is_stale(hash, &changed, "b", 1, base + 5*minute)) return 5;
    if (changed != base + 5*minute) return 6;
    if (progress_is_stale(hash, &changed, "b", 1, base + 6*minute)) return 7;
    if (progress_is_stale(hash, &changed, "b", 1, base)) return 8;
    if (changed != base) return 9;
    if (!progress_is_stale(hash, &changed, "b", 1, base + 2*minute)) return 10;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="kiki-gtk-stale-") as tmp:
            path, binary = Path(tmp) / "probe.c", Path(tmp) / "probe"
            path.write_text(harness)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(binary)] +
                           shlex.split(flags.stdout), check=True)
            subprocess.run([str(binary)], check=True, timeout=10)
        poll = source.split("static gboolean poll_install_progress(", 1)[1].split(
            "static void request_reboot", 1)[0]
        self.assertLess(poll.index('g_str_equal(state, "completed")'), poll.index('if (stale)'))
        self.assertLess(poll.index('g_str_equal(state, "failed")'), poll.index('if (stale)'))
        warning = poll.split('if (stale)', 1)[1]
        self.assertNotIn('install_complete =', warning)
        self.assertNotIn('gtk_widget_set_sensitive', warning)
        self.assertIn('g_get_monotonic_time()', poll)

if __name__ == "__main__":
    unittest.main()
