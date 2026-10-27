"""Target-only keymap compilation; not physical keyboard or Hangul IME testing."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-keysyms.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    struct xkb_context *c=xkb_context_new(XKB_CONTEXT_NO_ENVIRONMENT_NAMES);
    if(!c) return 1;
    for(unsigned i=0;i<xkb_context_num_include_paths(c);i++)
        if(strstr(xkb_context_include_path_get(c,i),"/tmp/")) return 2;
    struct xkb_rule_names names={.rules="evdev",.model="pc105",.layout="kr"};
    struct xkb_keymap *k=xkb_keymap_new_from_names(c,&names,XKB_KEYMAP_COMPILE_NO_FLAGS);
    if(!k) return 3;
    struct xkb_state *s=xkb_state_new(k);
    if(!s) return 4;
    xkb_keycode_t hangul=xkb_keymap_key_by_name(k,"HNGL");
    xkb_keycode_t hanja=xkb_keymap_key_by_name(k,"HJCV");
    if(xkb_state_key_get_one_sym(s,hangul)!=XKB_KEY_Hangul ||
       xkb_state_key_get_one_sym(s,hanja)!=XKB_KEY_Hangul_Hanja) return 5;
    xkb_keycode_t a=xkb_keymap_key_by_name(k,"AC01");
    xkb_keycode_t shift=xkb_keymap_key_by_name(k,"LFSH");
    if(xkb_state_key_get_one_sym(s,a)!=XKB_KEY_a) return 6;
    xkb_state_update_key(s,shift,XKB_KEY_DOWN);
    if(xkb_state_key_get_one_sym(s,a)!=XKB_KEY_A) return 7;
    xkb_state_update_key(s,shift,XKB_KEY_UP);
    char *text=xkb_keymap_get_as_string(k,XKB_KEYMAP_FORMAT_TEXT_V1);
    if(!text) return 8;
    struct xkb_keymap *copy=xkb_keymap_new_from_string(c,text,XKB_KEYMAP_FORMAT_TEXT_V1,0);
    free(text); if(!copy) return 9;
    xkb_keymap_unref(copy); xkb_state_unref(s); xkb_keymap_unref(k);
    names.layout="kiki-nonexistent-layout";
    k=xkb_keymap_new_from_names(c,&names,0);
    if(k) return 10;
    xkb_context_unref(c); return 0;
}
'''

@unittest.skipUnless(sys.platform=='linux' and os.environ.get('KIKI_TEST_XKB')=='1',
                     'set KIKI_TEST_XKB=1 on Linux as root')
class XkbRuntimeTests(unittest.TestCase):
    def test_korean_keys_shift_serialization_and_invalid_layout(self):
        self.assertEqual(os.geteuid(),0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo/'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-xkb-runtime-') as tmp:
            work=Path(tmp); root=work/'root'
            for name in ki2build.dependency_closure(recipes,['libxkbcommon','linux-headers'],'x86_64',include_build_deps=False):
                ki2build.extract_package_rootfs(repo/'dist/ki2/packages/x86_64'/ki2build.package_filename(recipes[name],'x86_64'),root)
            def run(cmd):
                p=subprocess.run(cmd,env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},capture_output=True,text=True,timeout=60)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                return p.stdout
            flags=['cc','--sysroot='+str(root)]
            for sub in ('usr/lib','usr/lib64','lib','lib64'):
                path=str(root/sub); flags+=['-B'+path+'/', '-L'+path, '-Wl,-rpath-link,'+path]
            (work/'probe.c').write_text(PROBE)
            run(flags+[str(work/'probe.c'),'-lxkbcommon','-o',str(root/'probe')])
            loaders=[p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            base=['chroot',str(root),'/'+str(loaders[0].relative_to(root)), '--inhibit-cache',
                  '--library-path','/usr/lib:/usr/lib64:/lib:/lib64']
            for lib in (root/'usr/lib').glob('libxkb*.so'):
                self.assertNotRegex(run(['readelf','-d',str(lib)]),r'\((?:RPATH|RUNPATH)\)')
                run(base+['--list','/'+str(lib.relative_to(root))])
                # Runtime defaults must never contain a cross-build sysroot.
                strings=run(['strings',str(lib)]).splitlines()
                leaked=[line for line in strings if '/tmp/' in line and
                        ('/sysroot/' in line or '/X11/' in line or '/xkeyboard-config' in line)]
                self.assertEqual(leaked,[])
            self.assertIn('1.13.2',run(base+['/usr/bin/xkbcli','--version']))
            run(base+['/probe'])

if __name__=='__main__':
    unittest.main()
