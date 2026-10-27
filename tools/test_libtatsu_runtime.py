"""Opt-in packaged libtatsu smoke test; never sends a TSS request."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

import ki2build


PROBE = r'''
#include <stdlib.h>
#include <string.h>
#include <curl/curl.h>
#include <libtatsu/tss.h>
int main(void) {
    if (curl_global_init(CURL_GLOBAL_DEFAULT)) return 4;
    CURL *handle = curl_easy_init();
    char *ca = NULL;
    if (!handle || curl_easy_getinfo(handle, CURLINFO_CAINFO, &ca) || !ca ||
        strcmp(ca, "/etc/ssl/certs/ca-certificates.crt")) return 5;
    curl_easy_cleanup(handle);
    curl_global_cleanup();
    if (strcmp(libtatsu_version(), "1.0.5")) return 1;
    plist_t overrides = plist_new_dict();
    plist_dict_set_item(overrides, "@HostPlatformInfo", plist_new_string("KIKI-test"));
    plist_t request = tss_request_new(overrides);
    plist_free(overrides);
    if (!request || plist_get_node_type(request) != PLIST_DICT) return 2;
    char *platform = NULL, *version = NULL, *uuid = NULL;
    plist_get_string_val(plist_dict_get_item(request, "@HostPlatformInfo"), &platform);
    plist_get_string_val(plist_dict_get_item(request, "@VersionInfo"), &version);
    plist_get_string_val(plist_dict_get_item(request, "@UUID"), &uuid);
    int failed = !platform || strcmp(platform, "KIKI-test") ||
                 !version || !*version || !uuid || strlen(uuid) != 36;
    free(platform); free(version); free(uuid); plist_free(request);
    return failed ? 3 : 0;
}
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_LIBTATSU') == '1',
                     'set KIKI_TEST_LIBTATSU=1 on Linux')
class LibtatsuRuntimeTests(unittest.TestCase):
    def test_version_request_creation_and_target_linkage(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        names = ki2build.dependency_closure(recipes, ['libtatsu', 'linux-headers'],
                                            'x86_64', include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix='kiki-tatsu-runtime-') as tmp:
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
            self.assertFalse((root / 'usr/lib/libtatsu.la').exists())
            self.assertFalse((root / 'usr/lib/libcurl.la').exists())
            self.assertTrue((root / 'usr/lib/libcurl.a').is_file())
            self.assertTrue((root / 'usr/lib/pkgconfig/libcurl.pc').is_file())
            self.assertTrue((root / 'usr/lib/pkgconfig/libtatsu-1.0.pc').is_file())
            self.assertNotRegex(run(['readelf', '-d', str(root / 'usr/lib/libtatsu.so.0')]),
                                r'\((?:RPATH|RUNPATH)\)')
            directories = [root / p for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64')]
            flags = ['cc', '--sysroot=' + str(root)]
            for path in directories:
                flags += ['-B' + str(path) + '/', '-L' + str(path), '-Wl,-rpath-link,' + str(path)]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-ltatsu', '-lplist-2.0', '-lcurl', '-o', str(work / 'probe')])
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            command = [str(loaders[0]), '--inhibit-cache', '--library-path', ':'.join(map(str, directories))]
            listing = run(command + ['--list', str(work / 'probe')])
            resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(', listing, re.MULTILINE))
            for name in ('libtatsu.so.0', 'libplist-2.0.so.4', 'libcurl.so.4', 'libzstd.so.1', 'libc.so.6'):
                self.assertIn(name, resolved)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            run(command + [str(work / 'probe')])
            curl = str(root / 'usr/bin/curl')
            config = str(root / 'usr/bin/curl-config')
            self.assertEqual(shlex.split(run(['/bin/sh', config, '--ca'])),
                             ['/etc/ssl/certs/ca-certificates.crt'])
            self.assertTrue((root / 'etc/ssl/certs/ca-certificates.crt').is_file())
            static_flags = run(['/bin/sh', config, '--static-libs'])
            self.assertNotIn('/tmp/', static_flags)
            self.assertNotIn('--sysroot', static_flags)
            self.assertIn('-lzstd', static_flags)
            for binary in (curl, str(root / 'usr/lib/libcurl.so.4')):
                self.assertNotRegex(run(['readelf', '-d', binary]), r'\((?:RPATH|RUNPATH)\)')
            curl_listing = run(command + ['--list', curl])
            curl_resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(', curl_listing, re.MULTILINE))
            self.assertIn('libzstd.so.1', curl_resolved)
            for path in curl_resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), curl_listing)
            version = run(command + [curl, '--disable', '--version'])
            self.assertIn('curl 8.8.0', version)
            self.assertRegex(version, r'(?m)^Features:.*\bzstd\b')
            # Local file transfer exercises curl without a network connection.
            fixture = work / 'fixture.txt'
            fixture.write_text('KIKI local curl transfer\n')
            self.assertEqual(run(command + [curl, '--disable', '--silent', '--show-error',
                                            '--proto', '=file', fixture.as_uri()]),
                             'KIKI local curl transfer\n')
            print('KIKI libtatsu: version, in-memory request and target linkage passed; no request sent')


if __name__ == '__main__':
    unittest.main()
