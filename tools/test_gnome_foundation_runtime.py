"""Opt-in real KIKI rootfs runtime checks; no sessions, mounts or device writes."""
import os
from pathlib import Path
import subprocess
import unittest


PROBE = r'''
import ctypes as c
import os
root = os.environ['KI2_SYSROOT']
libc = c.CDLL('libc.so.6')
libc.gnu_get_libc_version.restype = c.c_char_p
assert libc.gnu_get_libc_version() == b'2.39'
gi = c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_prepend_search_path.argtypes = [c.c_char_p]
gi.g_irepository_prepend_search_path((root+'/usr/lib/girepository-1.0').encode())
gi.g_irepository_get_default.restype = c.c_void_p
repository = gi.g_irepository_get_default()
gi.g_irepository_require.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int, c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype = c.c_void_p
for name, version in [(b'GDesktopEnums', b'3.0'), (b'Json', b'1.0'), (b'GUdev', b'1.0'),
                      (b'Polkit', b'1.0'), (b'PolkitAgent', b'1.0')]:
    error = c.c_void_p()
    assert gi.g_irepository_require(repository, name, version, 0, c.byref(error)), name
    assert not error.value
    print('TYPELIB', name.decode(), version.decode())
gobject = c.CDLL('libgobject-2.0.so.0')
gobject.g_object_unref.argtypes = [c.c_void_p]
json = c.CDLL('libjson-glib-1.0.so.0')
json.json_parser_new.restype = c.c_void_p
json.json_parser_load_from_data.argtypes = [c.c_void_p, c.c_char_p, c.c_ssize_t, c.POINTER(c.c_void_p)]
json.json_parser_load_from_data.restype = c.c_int
parser = json.json_parser_new()
assert parser
try:
    error = c.c_void_p()
    assert json.json_parser_load_from_data(parser, b'{"test":42}', -1, c.byref(error))
    assert not error.value
finally:
    gobject.g_object_unref(parser)
print('JSON parser runtime passed')
gudev = c.CDLL('libgudev-1.0.so.0')
gudev.g_udev_client_new.argtypes = [c.c_void_p]
gudev.g_udev_client_new.restype = c.c_void_p
client = gudev.g_udev_client_new(None)
assert client
gobject.g_object_unref(client)
print('GUdev client lifecycle passed')
c.CDLL('libdconf.so.1')
print('dconf library loaded')
polkit = c.CDLL('libpolkit-gobject-1.so.0')
polkit.polkit_details_new.restype = c.c_void_p
polkit.polkit_details_insert.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
polkit.polkit_details_lookup.argtypes = [c.c_void_p, c.c_char_p]
polkit.polkit_details_lookup.restype = c.c_char_p
details = polkit.polkit_details_new()
assert details
try:
    text = '한국어 인증 시험'.encode('utf-8')
    polkit.polkit_details_insert(details, b'message', text)
    assert polkit.polkit_details_lookup(details, b'message') == text
    assert polkit.polkit_details_lookup(details, b'missing') is None
finally:
    gobject.g_object_unref(details)
c.CDLL('libpolkit-agent-1.so.0')
print('Polkit details UTF-8/missing-key and agent library load passed; no authorization request')
'''


@unittest.skipUnless(os.environ.get('KIKI_GNOME_TEST_ROOTFS'), 'set KIKI_GNOME_TEST_ROOTFS to an assembled foundation rootfs')
class FoundationRuntimeTests(unittest.TestCase):
    def test_combined_target_runtime(self):
        root = Path(os.environ['KIKI_GNOME_TEST_ROOTFS']).resolve(strict=True)
        self.assertTrue((root / 'usr/share/glib-2.0/schemas/gschemas.compiled').is_file())
        repo = Path(__file__).resolve().parents[1]
        env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'KI2_SYSROOT': str(root),
               'PYTHONHOME': str(root / 'usr'),
               'KI2_SYSROOT_LIBRARY_PATH': ':'.join(str(root / p) for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64'))}
        result = subprocess.run(['/bin/sh', str(repo / 'distro/scripts/ki2-target-run'),
                                 str(root / 'usr/bin/python3.12'), '-B', '-c', PROBE],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout, end='')


if __name__ == '__main__':
    unittest.main()
