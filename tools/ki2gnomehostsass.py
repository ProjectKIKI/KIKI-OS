#!/usr/bin/env python3
"""Build a static SassC host tool outside the target SDK and legacy toolchains."""
import json
from pathlib import Path
import subprocess
import tarfile
import ki2sessioncandidate as c

lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
prefix=c.WORK/'host-tools'
env=dict(CC='gcc',CXX='g++',CPPFLAGS='',CFLAGS='-O2',CXXFLAGS='-O2',LDFLAGS='',LD_LIBRARY_PATH='',LIBRARY_PATH='',
         PKG_CONFIG_SYSROOT_DIR='',PKG_CONFIG_PATH=str(prefix/'lib/pkgconfig'),PKG_CONFIG_LIBDIR='/usr/lib64/pkgconfig:/usr/share/pkgconfig')
records=[]
for name in ['libsass-host','sassc-host']:
 s=next(s for s in lock['sources'] if s.get('name')==name)
 if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('Host tool source changed')
 root=c.WORK/'host-build'/name;source=root/'source'
 if not source.exists():
  source.mkdir(parents=True)
  with tarfile.open(s['file']) as t:t.extractall(source)
 src=next(p for p in source.iterdir() if p.is_dir())
 log=c.TARGET/'validation'/(name+'-build.log')
 if not (src/'configure').exists():c.run(['autoreconf','-fi'],src,log,env)
 out=root/'build';out.mkdir(exist_ok=True)
 options=['--prefix='+str(prefix),'--libdir='+str(prefix/'lib'),'--disable-shared','--enable-static']
 if name=='sassc-host':
  options.append('--with-libsass='+str(prefix))
  env.update(CPPFLAGS='-I'+str(prefix/'include'),LDFLAGS='-L'+str(prefix/'lib'),LIBS='-lstdc++ -lm')
 if not (out/'Makefile').exists():c.run([str(src/'configure')]+options,out,log,env)
 c.run(['make','-j2'],out,log,env)
 c.run(['make','install'],out,log,env)
 records.append(dict(source=s,host_only=True,configure_options=options))
 print('Built isolated host tool',name,flush=True)
version=subprocess.check_output([str(prefix/'bin/sassc'),'--version'],text=True)
c.save(c.TARGET/'validation/host-sass-lock.json',dict(sources=records,binary_sha256=c.sha256_file(prefix/'bin/sassc'),version=version,target_payload=False))
