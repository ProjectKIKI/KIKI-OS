"""Opt-in GLib/libffi regression test against actual target packages."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <glib-object.h>
#include <gio/gio.h>
#include <string.h>
static int calls;
static int callback(GObject *object, int number, const char *text, void *data) {
  (void)object; (void)data;
  if (number == 42 && !strcmp(text, "한국어")) calls++;
  return number + 1;
}
static gboolean idle(gpointer data) { g_main_loop_quit(data); return G_SOURCE_REMOVE; }
int main(void) {
  GObject *object = g_object_new(G_TYPE_OBJECT, NULL);
  guint signal = g_signal_new("kiki-probe", G_TYPE_OBJECT, G_SIGNAL_RUN_LAST,
      0, NULL, NULL, g_cclosure_marshal_generic, G_TYPE_INT, 2, G_TYPE_INT, G_TYPE_STRING);
  if (!signal) return 1;
  g_signal_connect(object, "kiki-probe", G_CALLBACK(callback), NULL);
  int result = 0;
  g_signal_emit(object, signal, 0, 42, "한국어", &result);
  if (calls != 1 || result != 43) return 2;
  g_object_unref(object);
  char *nfd = g_utf8_normalize("한국어", -1, G_NORMALIZE_NFD);
  char *nfc = g_utf8_normalize(nfd, -1, G_NORMALIZE_NFC);
  if (strcmp(nfc, "한국어")) return 3;
  g_free(nfd); g_free(nfc);
  GMainLoop *loop = g_main_loop_new(NULL, FALSE);
  g_idle_add(idle, loop); g_main_loop_run(loop); g_main_loop_unref(loop);
  GFile *file = g_file_new_for_path("/tmp/kiki-not-created");
  char *path = g_file_get_path(file);
  if (strcmp(path, "/tmp/kiki-not-created")) return 4;
  g_free(path); g_object_unref(file); return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_GLIB") == "1",
                     "set KIKI_TEST_GLIB=1 on Linux as root")
class GlibRuntimeTests(unittest.TestCase):
    def test_ffi_signal_and_mainloop(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-glib-runtime-") as tmp:
            work = Path(tmp); root = work / "root"
            for name in ki2build.dependency_closure(recipes, ["glib", "linux-headers"],
                                                    "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            flags = ["cc", "--sysroot=" + str(root)]
            for sub in ("usr/lib", "usr/lib64", "lib", "lib64"):
                path = str(root / sub)
                flags += ["-B" + path + "/", "-L" + path, "-Wl,-rpath-link," + path]
            for sub in ("usr/include/glib-2.0", "usr/lib/glib-2.0/include"):
                flags += ["-I" + str(root / sub)]
            (work / "probe.c").write_text(PROBE)
            run(flags + [str(work / "probe.c"), "-lgio-2.0", "-lgobject-2.0", "-lglib-2.0", "-o", str(root / "probe")])
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            command = ["chroot", str(root), "/" + str(loaders[0].relative_to(root)),
                       "--inhibit-cache", "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn("libffi.so.8 => /", run(command + ["--list", "/probe"]))
            for library in ("libglib-2.0.so.0", "libgobject-2.0.so.0", "libgio-2.0.so.0"):
                self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib" / library)]), r"\((?:RPATH|RUNPATH)\)")
            run(command + ["/probe"])

if __name__ == "__main__":
    unittest.main()
