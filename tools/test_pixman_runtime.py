"""Opt-in packaged Pixman compositing test using only target libraries."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <pixman.h>
#include <stdint.h>
int main(void) {
  uint32_t src[16], dst[24];
  for (int i=0;i<16;i++) src[i]=0x80800000;
  for (int i=0;i<24;i++) dst[i]=(i%6<4)?0xff0000ff:0x12345678;
  pixman_image_t *s=pixman_image_create_bits(PIXMAN_a8r8g8b8,4,4,src,16);
  pixman_image_t *d=pixman_image_create_bits(PIXMAN_a8r8g8b8,4,4,dst,24);
  if (!s || !d) return 1;
  pixman_region32_t clip; pixman_region32_init_rect(&clip,1,1,2,2);
  if (!pixman_image_set_clip_region32(d,&clip)) return 2;
  pixman_image_composite32(PIXMAN_OP_OVER,s,0,d,0,0,0,0,0,0,4,4);
  for (int y=0;y<4;y++) for (int x=0;x<6;x++) {
    uint32_t expected=x>=4?0x12345678:
      ((x>=1&&x<=2&&y>=1&&y<=2)?0xff80007f:0xff0000ff);
    if (dst[y*6+x]!=expected) return 3;
  }
  pixman_image_set_clip_region32(d,0);
  for (int i=0;i<16;i++) src[i]=0xff002060;
  pixman_image_composite32(PIXMAN_OP_SRC,s,0,d,0,0,0,0,0,0,4,4);
  for (int i=0;i<24;i++) if (dst[i]!=(i%6<4?0xff002060:0x12345678)) return 4;
  pixman_region32_fini(&clip); pixman_image_unref(s); pixman_image_unref(d);
  return pixman_version()!=4604;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PIXMAN") == "1",
                     "set KIKI_TEST_PIXMAN=1 on Linux as root")
class PixmanRuntimeTests(unittest.TestCase):
    def test_alpha_clip_and_stride(self):
        self.assertEqual(os.geteuid(), 0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-pixman-runtime-") as tmp:
            work=Path(tmp); root=work / "root"
            for name in ki2build.dependency_closure(recipes,["pixman","linux-headers"],"x86_64",include_build_deps=False):
                package=repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name],"x86_64")
                self.assertTrue(package.is_file(),str(package))
                ki2build.extract_package_rootfs(package,root)
            def run(command):
                result=subprocess.run(command,env={"PATH":"/usr/sbin:/usr/bin:/bin","LC_ALL":"C"},capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            flags=["cc","--sysroot="+str(root),"-I"+str(root / "usr/include/pixman-1")]
            for sub in ("usr/lib","usr/lib64","lib","lib64"):
                path=str(root/sub)
                flags += ["-B"+path+"/","-L"+path,"-Wl,-rpath-link,"+path]
            (work/"probe.c").write_text(PROBE)
            run(flags+[str(work/"probe.c"),"-lpixman-1","-o",str(root/"probe")])
            loaders=[p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            command=["chroot",str(root),"/"+str(loaders[0].relative_to(root)),"--inhibit-cache","--library-path","/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn("libpixman-1.so.0 => /",run(command+["--list","/probe"]))
            self.assertNotRegex(run(["readelf","-d",str(root/"usr/lib/libpixman-1.so.0")]),r"\((?:RPATH|RUNPATH)\)")
            self.assertTrue((root/"usr/share/licenses/pixman/COPYING").is_file())
            run(command+["/probe"])

if __name__ == "__main__":
    unittest.main()
