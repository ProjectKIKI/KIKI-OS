#!/usr/bin/env python3
"""Supply the native bzip2 ABI needed by the preserved target Python runtime."""
import contextlib
import io
import json
import shutil
import tarfile
import urllib.request
import ki2sessioncandidate as c

url='https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz'
expected='ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269'
archive=c.WORK/'sources/bzip2-1.0.8.tar.gz'
if not archive.exists():archive.write_bytes(urllib.request.urlopen(url,timeout=60).read())
if c.sha256_file(archive)!=expected:raise ValueError('bzip2 source SHA mismatch')
source=dict(name='bzip2',version='1.0.8',url=url,sha256=expected,file=str(archive),verification='Official Sourceware HTTPS archive; pinned SHA-256; no signature claim')
lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
if not any(s.get('name')=='bzip2' for s in lock['sources']):lock['sources'].append(source);c.save(c.TARGET/'gnome50-source-lock.json',lock)
out=c.WORK/'desktop-build/bzip2';out.mkdir(exist_ok=True)
src=out/'bzip2-1.0.8'
if not src.exists():
    with tarfile.open(archive) as t:t.extractall(out)
dest=out/'dest';lib=dest/'usr/lib';lib.mkdir(exist_ok=True,parents=True)
log=c.TARGET/'validation/bzip2-build.log'
objects=[]
for name in ['blocksort','huffman','crctable','randtable','compress','decompress','bzlib']:
    obj=out/(name+'.o');objects.append(str(obj))
    c.run(['gcc']+c.environment()['CFLAGS'].split()+['-fPIC','-c',str(src/(name+'.c')),'-o',str(obj)],out,log)
c.run(['gcc','-shared']+c.environment()['LDFLAGS'].split()+['-Wl,-soname,libbz2.so.1','-o',str(lib/'libbz2.so.1.0.8')]+objects,out,log)
for name in ['libbz2.so.1','libbz2.so.1.0','libbz2.so']:
    p=lib/name
    if not p.is_symlink():p.symlink_to('libbz2.so.1.0.8')
(dest/'usr/include').mkdir(exist_ok=True);shutil.copy2(src/'bzlib.h',dest/'usr/include/bzlib.h')
notice=dest/'usr/share/licenses/bzip2';notice.mkdir(exist_ok=True,parents=True);shutil.copy2(src/'LICENSE',notice/'LICENSE')
raw=dict(name='bzip2',version='1.0.8',release='1',summary='Native bzip2 library for Python bz2',license='bzip2-1.0.6',tier='base',architectures=['x86_64'],source=dict(type='url',url=url,sha256=expected),dependencies=dict(build=['linux-headers'],runtime=['glibc']),build=dict(system='custom'))
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(source=source,native_source_build=True,soname='libbz2.so.1'))
print('Built native bzip2 ABI supplier',flush=True)
