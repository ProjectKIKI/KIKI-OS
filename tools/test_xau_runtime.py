"""Exercise the packaged X authority library in a disposable target-only root."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
#include <X11/Xauth.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(void) {
    char address[]="kiki-test", number[]="0", name[]="MIT-MAGIC-COOKIE-1";
    char cookie[]={0,1,2,3,0,5,6,7,8,9,10,11,12,13,14,15};
    Xauth a={FamilyLocal,9,address,1,number,18,name,16,cookie};
    FILE *f=fopen("/tmp/test-authority","wb");
    if (!f || !XauWriteAuth(f,&a) || fclose(f)) return 1;
    f=fopen("/tmp/test-authority","rb");
    if (!f) return 2;
    Xauth *b=XauReadAuth(f);
    if (!b || b->family!=a.family || b->address_length!=9 || b->number_length!=1 ||
        b->name_length!=18 || b->data_length!=16 || memcmp(b->address,address,9) ||
        memcmp(b->number,number,1) || memcmp(b->name,name,18) || memcmp(b->data,cookie,16)) return 3;
    XauDisposeAuth(b);
    if (XauReadAuth(f)!=NULL || fclose(f)) return 4;
    if (setenv("XAUTHORITY","/tmp/test-authority",1) ||
        strcmp(XauFileName(),"/tmp/test-authority")) return 5;
    b=XauGetAuthByAddr(FamilyLocal,9,address,1,number,18,name);
    if (!b || b->data_length!=16 || memcmp(b->data,cookie,16)) return 6;
    XauDisposeAuth(b);
    b=XauGetAuthByAddr(FamilyLocal,9,address,1,"9",18,name);
    if (b) return 7;
    if (XauLockAuth("/tmp/test-authority",1,0,0)!=LOCK_SUCCESS) return 8;
    /* Unlike XauLockAuth, XauUnlockAuth returns boolean success (1). */
    if (XauUnlockAuth("/tmp/test-authority")!=1) return 9;
    if (!access("/tmp/test-authority-c",F_OK) || !access("/tmp/test-authority-l",F_OK)) return 10;
    /* A declared 16-byte cookie with its final byte missing must not parse. */
    f=fopen("/tmp/test-authority","r+b");
    if (!f || fseek(f,0,SEEK_END)) return 11;
    long size=ftell(f);
    if (size<2 || ftruncate(fileno(f),size-1) || fclose(f)) return 12;
    /* Reopen so stdio cannot satisfy the read from pre-truncation buffers. */
    f=fopen("/tmp/test-authority","rb");
    if (!f) return 14;
    b=XauReadAuth(f);
    if (b || fclose(f)) return 13;
    return 0;
}
'''

@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_TEST_XAU') == '1',
                     'set KIKI_TEST_XAU=1 on Linux as root')
class XauRuntimeTests(unittest.TestCase):
    def test_roundtrip_lookup_lock_and_truncated_record(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-xau-runtime-') as tmp:
            work = Path(tmp); root = work / 'root'
            for name in ki2build.dependency_closure(recipes, ['libxau','xorgproto','linux-headers'],
                                                   'x86_64', include_build_deps=False):
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name],'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            (root / 'tmp').mkdir(exist_ok=True)
            def run(command):
                result = subprocess.run(command, env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                        capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            flags = ['cc','--sysroot='+str(root)]
            for sub in ('usr/lib','usr/lib64','lib','lib64'):
                path=str(root/sub)
                flags += ['-B'+path+'/', '-L'+path, '-Wl,-rpath-link,'+path]
            (work/'probe.c').write_text(PROBE)
            run(flags+[str(work/'probe.c'),'-lXau','-o',str(root/'probe')])
            loaders=[p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            command=['chroot',str(root),'/'+str(loaders[0].relative_to(root)),
                     '--inhibit-cache','--library-path','/usr/lib:/usr/lib64:/lib:/lib64']
            self.assertIn('libXau.so.6 => /',run(command+['--list','/probe']))
            self.assertNotRegex(run(['readelf','-d',str(root/'usr/lib/libXau.so.6')]),r'\((?:RPATH|RUNPATH)\)')
            self.assertTrue((root/'usr/share/licenses/libxau/COPYING').is_file())
            run(command+['/probe'])

if __name__ == '__main__':
    unittest.main()
