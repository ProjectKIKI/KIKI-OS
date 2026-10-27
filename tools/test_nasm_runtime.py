"""Target assembler/disassembler verification in an isolated package root."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build


@unittest.skipUnless(sys.platform=='linux' and os.environ.get('KIKI_TEST_NASM')=='1',
                     'set KIKI_TEST_NASM=1 on Linux as root')
class NasmRuntimeTests(unittest.TestCase):
    def test_simd_encoding_disassembly_and_invalid_input(self):
        self.assertEqual(os.geteuid(),0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo/'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-nasm-runtime-') as tmp:
            root=Path(tmp)/'root'
            for name in ki2build.dependency_closure(recipes,['nasm'],'x86_64',include_build_deps=False):
                ki2build.extract_package_rootfs(repo/'dist/ki2/packages/x86_64'/ki2build.package_filename(recipes[name],'x86_64'),root)
            def run(cmd,success=True):
                p=subprocess.run(cmd,env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                 capture_output=True,text=True,timeout=30)
                if success:
                    self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                else:
                    self.assertGreater(p.returncode,0,p.stdout+p.stderr)
                return p.stdout+p.stderr
            loaders=[p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            base=['chroot',str(root),'/'+str(loaders[0].relative_to(root)), '--inhibit-cache',
                  '--library-path','/usr/lib:/usr/lib64:/lib:/lib64']
            for binary in ('nasm','ndisasm'):
                run(base+['--list','/usr/bin/'+binary])
                self.assertNotRegex(run(['readelf','-d',str(root/'usr/bin'/binary)]),r'\((?:RPATH|RUNPATH)\)')
            self.assertIn('3.02',run(base+['/usr/bin/nasm','-v']))
            (root/'probe.asm').write_text('bits 64\npxor xmm0,xmm0\nvpxor ymm0,ymm0,ymm0\nmov eax,42\nret\n')
            run(base+['/usr/bin/nasm','-f','bin','-o','/probe.bin','/probe.asm'])
            self.assertEqual((root/'probe.bin').read_bytes(),bytes.fromhex('660fefc0c5fdefc0b82a000000c3'))
            disassembly=run(base+['/usr/bin/ndisasm','-b','64','/probe.bin'])
            self.assertIn('pxor xmm0,xmm0',disassembly)
            self.assertIn('vpxor ymm0,ymm0,ymm0',disassembly)
            (root/'bad.asm').write_text('bits 64\nnot_an_instruction xyz\n')
            self.assertIn('error',run(base+['/usr/bin/nasm','-f','bin','-o','/bad.bin','/bad.asm'],False).lower())


if __name__=='__main__':
    unittest.main()
