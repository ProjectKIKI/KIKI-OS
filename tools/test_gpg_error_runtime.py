"""Opt-in target errno and multithreaded gpgrt lock smoke test."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


PROBE = r'''
#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <gpg-error.h>
static gpgrt_lock_t lock = GPGRT_LOCK_INITIALIZER;
static unsigned counter;
static void *worker(void *unused) {
    (void)unused;
    for (int i=0; i<10000; i++) {
        if (gpgrt_lock_lock(&lock)) return (void*)1;
        counter++;
        if (gpgrt_lock_unlock(&lock)) return (void*)1;
    }
    return NULL;
}
int main(void) {
    if (strcmp(gpg_error_check_version(NULL), "1.61")) return 1;
    struct { int number; gpg_err_code_t code; } errors[] = {
        {EACCES,GPG_ERR_EACCES}, {ENOENT,GPG_ERR_ENOENT}, {ENOSPC,GPG_ERR_ENOSPC},
        {EPIPE,GPG_ERR_EPIPE}, {EIO,GPG_ERR_EIO}, {EINTR,GPG_ERR_EINTR},
        {EAGAIN,GPG_ERR_EAGAIN}, {ENOMEM,GPG_ERR_ENOMEM}, {EINVAL,GPG_ERR_EINVAL},
        {EBUSY,GPG_ERR_EBUSY}
    };
    for (unsigned i=0; i<sizeof(errors)/sizeof(errors[0]); i++) {
        if (gpg_err_code_from_errno(errors[i].number) != errors[i].code ||
            gpg_err_code_to_errno(errors[i].code) != errors[i].number) return 2;
    }
    pthread_t threads[4];
    for (int i=0; i<4; i++) if (pthread_create(&threads[i],NULL,worker,NULL)) return 3;
    for (int i=0; i<4; i++) {
        void *result;
        if (pthread_join(threads[i],&result) || result) return 4;
    }
    if (counter != 40000 || gpgrt_lock_destroy(&lock)) return 5;
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_GPG_ERROR') == '1',
                     'set KIKI_TEST_GPG_ERROR=1 on Linux')
class GpgErrorRuntimeTests(unittest.TestCase):
    def test_target_errno_lock_and_linkage(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        names = ki2build.dependency_closure(recipes, ['libgpg-error', 'linux-headers'],
                                           'x86_64', include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix='kiki-gpg-error-runtime-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in names:
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertFalse((root / 'usr/lib/libgpg-error.la').exists())
            self.assertTrue((root / 'usr/lib/pkgconfig/gpg-error.pc').is_file())
            self.assertNotRegex(run(['readelf','-d',str(root / 'usr/lib/libgpg-error.so.0')]),
                                r'\((?:RPATH|RUNPATH)\)')
            directories = [root / p for p in ('usr/lib','usr/lib64','lib','lib64')]
            flags = ['cc','--sysroot=' + str(root)]
            for path in directories:
                flags += ['-B'+str(path)+'/', '-L'+str(path), '-Wl,-rpath-link,'+str(path)]
            (work / 'probe.c').write_text(PROBE)
            run(flags + [str(work / 'probe.c'), '-lgpg-error', '-pthread', '-o', str(work / 'probe')])
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]),'--inhibit-cache','--library-path',':'.join(map(str,directories))]
            listing = run(loader + ['--list',str(work / 'probe')])
            resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(',listing,re.MULTILINE))
            for name in ('libgpg-error.so.0','libc.so.6'):
                self.assertIn(name,resolved)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root),listing)
            run(loader + [str(work / 'probe')])
            print('KIKI libgpg-error: 10 errno mappings, 4-thread lock/40000 increments and target linkage passed')


if __name__ == '__main__':
    unittest.main()
