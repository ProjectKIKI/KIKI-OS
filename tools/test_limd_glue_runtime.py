"""Opt-in KIKI device helper smoke test; no sockets, devices or sessions."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


PROBE = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <libimobiledevice-glue/glue.h>
#include <libimobiledevice-glue/sha.h>
#include <libimobiledevice-glue/opack.h>
int main(void) {
    if (strcmp(libimobiledevice_glue_version(), "1.3.2")) return 1;
    const unsigned char expected[32] = {
        0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,
        0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad};
    unsigned char digest[32];
    if (sha256((const unsigned char*)"abc", 3, digest) || memcmp(digest, expected, 32)) return 2;
    plist_t input = plist_new_dict(), decoded = NULL;
    plist_dict_set_item(input, "name", plist_new_string("KIKI"));
    plist_dict_set_item(input, "count", plist_new_uint(42));
    unsigned char *encoded = NULL;
    unsigned int length = 0;
    opack_encode_from_plist(input, &encoded, &length);
    if (!encoded || !length) return 3;
    if (opack_decode_to_plist(encoded, length, &decoded) || !decoded) return 4;
    char *name = NULL;
    uint64_t count = 0;
    plist_get_string_val(plist_dict_get_item(decoded, "name"), &name);
    plist_get_uint_val(plist_dict_get_item(decoded, "count"), &count);
    int result = !name || strcmp(name, "KIKI") || count != 42;
    free(name); free(encoded); plist_free(input); plist_free(decoded);
    return result ? 5 : 0;
}
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_LIMD_GLUE') == '1',
                     'set KIKI_TEST_LIMD_GLUE=1 on Linux')
class LimdGlueRuntimeTests(unittest.TestCase):
    def test_version_sha256_and_opack_roundtrip(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        names = ki2build.dependency_closure(recipes, ['libimobiledevice-glue', 'linux-headers'],
                                            'x86_64', include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix='kiki-limd-runtime-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in names:
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
            def run(command):
                result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            library = root / 'usr/lib/libimobiledevice-glue-1.0.so.0'
            dynamic = run(['readelf', '-d', str(library)])
            self.assertNotRegex(dynamic, r'\((?:RPATH|RUNPATH)\)')
            directories = [root / p for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64')]
            flags = ['cc', '--sysroot=' + str(root)]
            for path in directories:
                flags += ['-B' + str(path) + '/', '-L' + str(path), '-Wl,-rpath-link,' + str(path)]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-limobiledevice-glue-1.0', '-lplist-2.0', '-o', str(work / 'probe')])
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            command = [str(loaders[0]), '--inhibit-cache', '--library-path', ':'.join(map(str, directories))]
            listing = run(command + ['--list', str(work / 'probe')])
            resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(', listing, re.MULTILINE))
            for name in ('libimobiledevice-glue-1.0.so.0', 'libplist-2.0.so.4', 'libc.so.6'):
                self.assertIn(name, resolved)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            run(command + [str(work / 'probe')])
            print('KIKI libimobiledevice-glue: version, SHA256 vector, OPACK roundtrip passed')


if __name__ == '__main__':
    unittest.main()
