#!/usr/bin/env python3
"""Build a locked native host utility under the dedicated host-tools prefix."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import ki2sessioncandidate as c

name=sys.argv[1]
if name!='patchelf-host':raise ValueError(name)
s=next(s for s in json.loads((c.TARGET/'gnome50-source-lock.json').read_text())['sources'] if s.get('name')==name)
if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('Host source changed')
root=c.WORK/'host-build'/name;src=root/'source'
if not src.exists():
 src.mkdir(parents=True)
 with tarfile.open(s['file']) as t:t.extractall(src)
src=next(p for p in src.iterdir() if p.is_dir())
out=root/'build';out.mkdir(exist_ok=True);prefix=c.WORK/'host-tools'
env=dict(CC='gcc',CXX='g++',CPPFLAGS='',CFLAGS='-O2',CXXFLAGS='-O2',LDFLAGS='',LD_LIBRARY_PATH='',LIBRARY_PATH='',
         PKG_CONFIG_SYSROOT_DIR='',PKG_CONFIG_PATH='',PKG_CONFIG_LIBDIR='/usr/lib64/pkgconfig:/usr/share/pkgconfig')
log=c.TARGET/'validation'/(name+'-build.log')
if not (out/'Makefile').exists():c.run([str(src/'configure'),'--prefix='+str(prefix)],out,log,env)
c.run(['make','-j2'],out,log,env)
c.run(['make','install'],out,log,env)
binary=prefix/'bin/patchelf'
c.save(c.TARGET/'validation/patchelf-host-lock.json',dict(source=s,host_only=True,target_payload=False,binary=str(binary),sha256=c.sha256_file(binary),version=subprocess.check_output([str(binary),'--version'],text=True)))
print('Built isolated host patchelf')
