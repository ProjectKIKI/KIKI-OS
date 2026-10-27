"""Wayland protocol roundtrips without a compositor, GPU, or external socket."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ki2build

PROBE = r'''
#include <wayland-client.h>
#include <wayland-server.h>
#include <sys/socket.h>
#include <unistd.h>
#include <stdint.h>
static void done(void *data, struct wl_callback *callback, uint32_t serial) {
  (void)serial;
  (*(int *)data)++;
  wl_callback_destroy(callback);
}
static const struct wl_callback_listener listener = {done};
int main(void) {
  int sockets[2];
  if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sockets)) return 1;
  struct wl_display *server = wl_display_create();
  if (!server) return 2;
  struct wl_client *peer = wl_client_create(server, sockets[0]);
  if (!peer) return 3;
  struct wl_display *client = wl_display_connect_to_fd(sockets[1]);
  if (!client) return 4;
  int count = 0;
  for (int i=0; i<64; i++) {
    struct wl_callback *callback = wl_display_sync(client);
    if (!callback || wl_callback_add_listener(callback, &listener, &count)) return 5;
    if (wl_display_flush(client) < 0) return 6;
    if (wl_event_loop_dispatch(wl_display_get_event_loop(server), 100) < 0) return 7;
    wl_display_flush_clients(server);
    if (wl_display_dispatch(client) < 0 || count != i+1) return 8;
  }
  wl_display_disconnect(client);
  wl_display_destroy_clients(server);
  wl_display_destroy(server);
  return 0;
}
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_WAYLAND') == '1',
                     'set KIKI_TEST_WAYLAND=1 on Linux as root')
class WaylandRuntimeTests(unittest.TestCase):
    def test_scanner_and_protocol_roundtrips(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-wayland-runtime-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in ki2build.dependency_closure(recipes, ['wayland', 'linux-headers'], 'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command, success=True):
                result = subprocess.run(command, env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                        capture_output=True, text=True, timeout=30)
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertGreater(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr
            flags = ['cc', '--sysroot=' + str(root)]
            for sub in ('usr/lib', 'usr/lib64', 'lib', 'lib64'):
                path = str(root / sub)
                flags += ['-B'+path+'/', '-L'+path, '-Wl,-rpath-link,'+path]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-lwayland-client', '-lwayland-server', '-o', str(root / 'probe')])
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ['chroot', str(root), '/'+str(loaders[0].relative_to(root)),
                    '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
            linked = run(base + ['--list', '/probe'])
            self.assertIn('libwayland-client.so.0 => /', linked)
            self.assertIn('libwayland-server.so.0 => /', linked)
            run(base + ['/probe'])
            self.assertIn('1.26.0', run(base + ['/usr/bin/wayland-scanner', '--version']))
            for mode, output in [('client-header','client.h'), ('server-header','server.h'), ('private-code','code.c')]:
                run(base + ['/usr/bin/wayland-scanner', '-s', mode, '/usr/share/wayland/wayland.xml', '/'+output])
                self.assertGreater((root / output).stat().st_size, 100)
            run(flags + ['-c', str(root / 'code.c'), '-o', str(work / 'protocol.o')])
            (root / 'invalid.xml').write_text('<protocol name="broken"><invalid/></protocol>')
            run(base + ['/usr/bin/wayland-scanner', '-s', 'client-header', '/invalid.xml', '/invalid.h'], success=False)


if __name__ == '__main__':
    unittest.main()
