#!/usr/bin/env python3
"""Build ICU host generators separately, then the KIKI target library."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import ki2sessioncandidate as c

s=next(x for x in json.loads((c.TARGET/'gnome50-source-lock.json').read_text())['sources'] if x.get('name')=='icu')
if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('ICU source changed')
root=c.WORK/'desktop-build/icu';src=root/'source'
if not src.exists():
 src.mkdir(parents=True)
 with tarfile.open(s['file']) as t:t.extractall(src)
tree=next(x for x in src.iterdir() if x.is_dir());src=tree/'source'
host=root/'host';host.mkdir(exist_ok=True)
log=c.TARGET/'validation/icu-build.log'
hostenv=dict(CC='gcc',CXX='g++',CPPFLAGS='',CFLAGS='-O2',CXXFLAGS='-O2',LDFLAGS='',LIBRARY_PATH='',LD_LIBRARY_PATH='',PKG_CONFIG_LIBDIR='/usr/lib64/pkgconfig:/usr/share/pkgconfig',PKG_CONFIG_SYSROOT_DIR='')
common=['--disable-tests','--disable-samples','--disable-icuio','--with-data-packaging=archive']
if not (host/'Makefile').exists():c.run([str(src/'configure'),'--prefix='+str(root/'host-prefix')]+common,host,log,hostenv)
if not (host/'.build-complete').exists():
 (host/'data/out/tmp').mkdir(exist_ok=True,parents=True)
 c.run(['make','-j2'],host,log,hostenv)
 (host/'.build-complete').write_text('complete\n')
out=root/'build';out.mkdir(exist_ok=True);dest=root/'dest';dest.mkdir(exist_ok=True)
options=['--prefix=/usr','--libdir=/usr/lib','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--with-cross-build='+str(host)]+common
if not (out/'Makefile').exists():c.run([str(src/'configure')]+options,out,log)
(out/'data/out/tmp').mkdir(exist_ok=True,parents=True)
c.run(['make','-j2'],out,log)
c.run(['make','DESTDIR='+str(dest),'install'],out,log)
notice=dest/'usr/share/licenses/icu';notice.mkdir(exist_ok=True,parents=True);shutil.copy2(tree/'LICENSE',notice/'LICENSE')
raw=dict(name='icu',version=s['version'],release='1',summary='Native Unicode support for GNOME',license='Unicode-3.0',tier='library',architectures=['x86_64'],
         source=dict(type='url',url=s['url'],sha256=s['sha256']),dependencies=dict(build=['linux-headers'],runtime=['glibc','libstdcxx']),build=dict(system='gnu',configure_options=options))
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(source_lock=s,options=options,host_generators=str(host),host_generators_in_target=False))
subprocess.run(['cp','-a',str(dest)+'/.',str(c.SDK)],check=True)
print('Built and staged ICU',s['version'])
