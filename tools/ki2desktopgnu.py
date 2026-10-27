#!/usr/bin/env python3
"""Build locked small GNU-style desktop dependencies with target-only flags."""
import contextlib
import difflib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import ki2sessioncandidate as c

PRESETS={
 'libarchive':dict(options=['--disable-static','--without-bz2lib','--without-lz4','--without-nettle','--with-openssl','--without-expat','--without-xml2'],
                    dependencies=['glibc','zlib','xz','zstd','openssl'],license='BSD-2-Clause'),
 'hicolor-icon-theme':dict(options=[],dependencies=[],license='GPL-2.0-or-later'),
 'libfyaml':dict(options=['--disable-static','--disable-testsuite'],dependencies=['glibc'],license='MIT'),
 'libyaml':dict(options=['--disable-static'],dependencies=['glibc'],license='MIT'),
 'alsa-lib':dict(options=['--disable-static','--disable-python'],dependencies=['glibc'],license='LGPL-2.1-or-later'),
 'libogg':dict(options=['--disable-static'],dependencies=['glibc'],license='BSD-3-Clause'),
 'libvorbis':dict(options=['--disable-static','--disable-docs'],dependencies=['glibc','libogg'],license='BSD-3-Clause'),
 'libtool':dict(options=['--disable-static'],dependencies=['glibc'],license='GPL-2.0-or-later WITH Libtool-exception'),
 'libcanberra':dict(options=['--disable-static','--disable-gtk','--disable-gtk3','--disable-gtk-doc','--disable-oss','--disable-gstreamer','--enable-alsa','--enable-pulse','--disable-udev'],
                    dependencies=['glibc','libtool','libvorbis','pulseaudio','alsa-lib'],license='LGPL-2.1-or-later'),
 'ibus':dict(options=['--disable-static','--disable-gtk2','--disable-gtk3','--enable-gtk4','--disable-xim','--enable-wayland','--disable-setup','--disable-ui','--disable-tests',
                     '--disable-appindicator','--enable-memconf','--enable-engine','--disable-glibtest','--disable-python2',
                     '--disable-emoji-dict','--disable-unicode-dict','--disable-gtk-doc','--disable-libnotify','--disable-gconf','--enable-dconf','--enable-introspection','--disable-vala','--disable-schema-compile'],
             dependencies=['glib','gtk','dconf','libxkbcommon','wayland','python'],license='LGPL-2.1-or-later'),
 'sqlite':dict(options=['--disable-static','--disable-readline'],dependencies=['glibc','zlib'],license='blessing'),
 'iso-codes':dict(options=[],dependencies=[],license='LGPL-2.1-or-later'),
 'nghttp2':dict(options=['--enable-lib-only','--disable-static','--disable-examples','--disable-app','--disable-hpack-tools'],dependencies=['glibc'],license='MIT'),
 'libpsl':dict(options=['--disable-static','--disable-gtk-doc','--disable-man'],dependencies=['glibc','libidn2','libunistring'],license='MIT'),
}

def build(name):
 report=c.TARGET/'validation'/(name+'-build.json')
 if report.exists():
  r=json.loads(report.read_text())
  if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Package changed')
 else:
  p=PRESETS[name];s=next(x for x in json.loads((c.TARGET/'gnome50-source-lock.json').read_text())['sources'] if x.get('name')==name)
  if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('Source changed')
  root=c.WORK/'desktop-build'/name;source=root/'source'
  if not source.exists():
   source.mkdir(parents=True)
   with tarfile.open(s['file']) as t:t.extractall(source)
  src=next(x for x in source.iterdir() if x.is_dir())
  out=root/'build';out.mkdir(exist_ok=True);dest=root/'dest';dest.mkdir(exist_ok=True)
  shutil.copy2(c.WORK/'g-ir-compiler.real',out/'g-ir-compiler.real')
  env=dict(KI2_REPO_ROOT=str(c.TARGET/'inputs'),KI2_BUILD_DIR=str(out),KI2_USE_TARGET_LOADER='1',
           GI_CROSS_LAUNCHER='/bin/sh '+str(c.TARGET/'inputs/distro/scripts/ki2-target-run'))
  if name == 'ibus':
   gi_runner=out/'gi-target-run'
   gi_runner.write_text('#!/bin/sh\nset -eu\nprogram=$1\nshift\ncase "$program" in */*) directory=${program%/*}; base=${program##*/} ;; *) directory=.; base=$program ;; esac\nif [ -f "$directory/.libs/$base" ]; then program="$directory/.libs/$base"; fi\nexec /bin/sh "'+str(c.TARGET/'inputs/distro/scripts/ki2-target-run')+'" "$program" "$@"\n')
   gi_runner.chmod(0o755)
   env['GI_CROSS_LAUNCHER']=str(gi_runner)
   env['KI2_SYSROOT_LIBRARY_PATH']=str(out/'src/.libs')+':'+c.environment()['KI2_SYSROOT_LIBRARY_PATH']
   host_pkg=out/'host-pkg-config'
   host_pkg.write_text('#!/bin/sh\nexec env PKG_CONFIG_SYSROOT_DIR= PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR=/usr/lib64/pkgconfig:/usr/share/pkgconfig /usr/bin/pkg-config "$@"\n')
   host_pkg.chmod(0o755)
   env.update(PKG_CONFIG_FOR_BUILD=str(host_pkg),CC_FOR_BUILD='gcc',CFLAGS_FOR_BUILD='-O2',CPPFLAGS_FOR_BUILD='',LDFLAGS_FOR_BUILD='')
   target_python=out/'target-python3'
   target_python.write_text('#!/bin/sh\nexec /bin/sh "'+str(c.TARGET/'inputs/distro/scripts/ki2-target-python3')+'" "$@"\n')
   target_python.chmod(0o755)
   env['PYTHON']=str(target_python)
   env.update(WAYLAND_SCANNER=str(c.SDK/'usr/bin/wayland-scanner'),GDBUS_CODEGEN=str(c.SDK/'usr/bin/gdbus-codegen'),
              GLIB_GENMARSHAL=str(c.SDK/'usr/bin/glib-genmarshal'),GLIB_MKENUMS=str(c.SDK/'usr/bin/glib-mkenums'),
              GLIB_COMPILE_RESOURCES=str(c.SDK/'usr/bin/glib-compile-resources'))
   changes=[]
   for relative in ['src/Makefile.am','src/Makefile.in']:
    f=src/relative;before=f.read_text()
    after=before.replace('$(builddir)/gen-internal-compose-table &&', '/bin/sh '+str(c.TARGET/'inputs/distro/scripts/ki2-target-run')+' $(builddir)/gen-internal-compose-table &&')
    if before!=after:
     changes+=list(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative));f.write_text(after)
   patch=c.TARGET/'inputs/patches/ibus-compose-target-run.patch'
   if changes:patch.write_text(''.join(changes))
  log=c.TARGET/'validation'/(name+'-build.log')
  options=['--prefix=/usr','--libdir=/usr/lib','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu']+p['options']
  if name in ['ibus','libcanberra','libarchive']:options.append('--with-sysroot='+str(c.SDK))
  if not (out/'Makefile').exists() or name in ['ibus','libcanberra']:c.run([str(src/'configure')]+options,out,log,env)
  make_options=[]
  if name=='ibus':
   # The generator uses newer GLib APIs than the builder provides. Build it
   # against the target SDK and execute it only through the target loader.
   marker=out/'.target-compose-generator'
   if not marker.exists():
    backup=out/'generator-host-objects';backup.mkdir(exist_ok=True)
    for f in (out/'src').glob('gen_internal_compose_table*.o'):f.rename(backup/f.name)
    marker.write_text('target generator; loader wrapper required\n')
   libs=['glib-2.0','gobject-2.0','gio-2.0','gio-unix-2.0','gthread-2.0']
   flags=lambda kind:subprocess.check_output(['pkg-config',kind]+libs,env=c.environment(),text=True).strip()
   make_options=['CC_FOR_BUILD=gcc','CFLAGS_FOR_BUILD='+c.environment()['CFLAGS'],'CPPFLAGS_FOR_BUILD='+c.environment()['CPPFLAGS'],
                 'LDFLAGS_FOR_BUILD='+c.environment()['LDFLAGS'],'GLIB_CFLAGS_FOR_BUILD='+flags('--cflags'),'GLIB_LIBS_FOR_BUILD='+flags('--libs')]
   make_options+=['INTROSPECTION_MAKEFILE='+str(c.SDK/'usr/share/gobject-introspection-1.0/Makefile.introspection'),
                  'INTROSPECTION_SCANNER='+str(c.SDK/'usr/bin/g-ir-scanner'),'INTROSPECTION_COMPILER='+str(c.SDK/'usr/bin/g-ir-compiler')]
  c.run(['make','-j2']+make_options,out,log,env)
  c.run(['make','DESTDIR='+str(dest),'install']+make_options,out,log,env)
  notices=dest/'usr/share/licenses'/name;notices.mkdir(exist_ok=True,parents=True)
  for f in src.iterdir():
   if f.is_file() and f.name.startswith(('COPYING','LICENSE','NOTICE')):shutil.copy2(f,notices/f.name)
  raw=dict(name=name,version=s['version'],release='1',summary='Native GNOME desktop dependency',license=p['license'],tier='library',architectures=['x86_64'],
           source=dict(type='url',url=s['url'],sha256=s['sha256']),dependencies=dict(build=['linux-headers'],runtime=p['dependencies']),build=dict(system='gnu',configure_options=options))
  provenance=dict(source_lock=s,configure_options=options,make_options=make_options)
  if name=='ibus':provenance['patches']=[dict(path=str(patch),sha256=c.sha256_file(patch))]
  with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,provenance)
 subprocess.run(['cp','-a',str(c.WORK/'desktop-build'/name/'dest')+'/.',str(c.SDK)],check=True)
 print('Built and staged',name,flush=True)

if __name__=='__main__':
 for name in sys.argv[1:]:build(name)
