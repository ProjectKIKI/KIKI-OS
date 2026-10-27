"""Opt-in native Cairo image/document/font integration smoke test."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r"""
#include <cairo.h>
#include <cairo-ft.h>
#include <cairo-pdf.h>
#include <cairo-svg.h>
#include <stdint.h>
#include <string.h>
static int document(int pdf) {
  cairo_surface_t *s=pdf?cairo_pdf_surface_create("/test.pdf",80,40):cairo_svg_surface_create("/test.svg",80,40);
  cairo_t *cr=cairo_create(s);
  cairo_set_source_rgb(cr,0,32.0/255,96.0/255); cairo_paint(cr);
  cairo_destroy(cr); cairo_surface_finish(s);
  int err=cairo_surface_status(s); cairo_surface_destroy(s); return err;
}
int main(void) {
  cairo_surface_t *s=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,96,40);
  cairo_t *cr=cairo_create(s);
  cairo_set_source_rgb(cr,0,32.0/255,96.0/255); cairo_paint(cr);
  cairo_surface_flush(s);
  if (*(uint32_t*)cairo_image_surface_get_data(s)!=0xff002060) return 1;
  if (cairo_surface_write_to_png(s,"/test.png")) return 2;
  cairo_surface_t *read=cairo_image_surface_create_from_png("/test.png");
  if (cairo_surface_status(read) || cairo_image_surface_get_width(read)!=96) return 3;
  if (memcmp(cairo_image_surface_get_data(s),cairo_image_surface_get_data(read),96*40*4)) return 4;
  cairo_surface_destroy(read);
  FT_Library lib; FT_Face ft;
  if (FT_Init_FreeType(&lib) || FT_New_Face(lib,"/font.ttc",0,&ft)) return 5;
  cairo_font_face_t *face=cairo_ft_font_face_create_for_ft_face(ft,0);
  cairo_set_font_face(cr,face); cairo_set_font_size(cr,24);
  cairo_set_source_rgb(cr,1,1,1); cairo_move_to(cr,2,28); cairo_show_text(cr,"한국어");
  if (cairo_status(cr)) return 6;
  cairo_surface_flush(s);
  uint32_t *pixels=(uint32_t*)cairo_image_surface_get_data(s); int changed=0;
  for(int i=0;i<96*40;i++) if(pixels[i]!=0xff002060) changed++;
  if(changed<20) return 7;
  cairo_destroy(cr); cairo_surface_destroy(s); cairo_font_face_destroy(face);
  cairo_debug_reset_static_data(); FT_Done_Face(ft); FT_Done_FreeType(lib);
  if(document(1)||document(0)) return 8;
  return cairo_version()!=11804;
}
"""

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_CAIRO") == "1",
                     "set KIKI_TEST_CAIRO=1 on Linux as root")
class CairoRuntimeTests(unittest.TestCase):
    def test_target_png_fonts_and_documents(self):
        self.assertEqual(os.geteuid(),0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo/"distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-cairo-runtime-") as tmp:
            work=Path(tmp); root=work/"root"
            for name in ki2build.dependency_closure(recipes,["cairo","linux-headers"],"x86_64",include_build_deps=False):
                package=repo/"dist/ki2/packages/x86_64"/ki2build.package_filename(recipes[name],"x86_64")
                self.assertTrue(package.is_file(),str(package))
                ki2build.extract_package_rootfs(package,root)
            def run(command):
                result=subprocess.run(command,env={"PATH":"/usr/sbin:/usr/bin:/bin","LC_ALL":"C"},capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            flags=["cc","--sysroot="+str(root)]
            for sub in ("usr/lib","usr/lib64","lib","lib64"):
                path=str(root/sub); flags += ["-B"+path+"/","-L"+path,"-Wl,-rpath-link,"+path]
            for sub in ("usr/include/cairo","usr/include/freetype2"):
                flags += ["-I"+str(root/sub)]
            (work/"probe.c").write_text(PROBE)
            run(flags+[str(work/"probe.c"),"-lcairo","-lfreetype","-o",str(root/"probe")])
            shutil.copyfile(repo/"build/ki2/host-graphics/rootfs/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",root/"font.ttc")
            loaders=[p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            base=["chroot",str(root),"/"+str(loaders[0].relative_to(root)),"--inhibit-cache","--library-path","/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn("libcairo.so.2 => /",run(base+["--list","/probe"]))
            self.assertNotRegex(run(["readelf","-d",str(root/"usr/lib/libcairo.so.2")]),r"\((?:RPATH|RUNPATH)\)")
            run(base+["/probe"])
            self.assertTrue((root/"test.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertTrue((root/"test.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertIn(b"<svg",(root/"test.svg").read_bytes())

if __name__ == "__main__":
    unittest.main()
