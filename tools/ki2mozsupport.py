#!/usr/bin/env python3
"""Build NSPR/NSS from the already SHA-locked Firefox source, in separate trees."""
import contextlib
import difflib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import ki2sessioncandidate as c

FIREFOX=c.WORK/'desktop-build/mozjs/firefox-140.1.0'


def package(name,version,dest,dependencies,options):
    source=next(x for x in json.loads((c.TARGET/'gnome50-source-lock.json').read_text())['sources'] if 'firefox-140.1.0' in x['file'])
    if c.sha256_file(source['file'])!=source['sha256']:raise ValueError('Firefox source changed')
    raw=dict(name=name,version=version,release='1',summary='Native Mozilla support library for GNOME',license='MPL-2.0',tier='library',architectures=['x86_64'],
             source=dict(type='url',url=source['url'],sha256=source['sha256']),dependencies=dict(build=['linux-headers'],runtime=dependencies),build=dict(system='gnu',configure_options=options))
    notice=dest/'usr/share/licenses'/name;notice.mkdir(exist_ok=True,parents=True)
    shutil.copy2(FIREFOX/'LICENSE',notice/'LICENSE')
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(parent_source=source,source_subdirectory='nsprpub' if name=='nspr' else 'security/nss',options=options))
    subprocess.run(['cp','-a',str(dest)+'/.',str(c.SDK)],check=True)


def nspr():
    root=c.WORK/'desktop-build/nspr';src=root/'source'
    if not src.exists():shutil.copytree(FIREFOX/'nsprpub',src,symlinks=True)
    version=re.search(r'#define PR_VERSION\s+"(.*?)"',(src/'pr/include/prinit.h').read_text())[1]
    out=root/'build';out.mkdir(exist_ok=True);dest=root/'dest';dest.mkdir(exist_ok=True)
    log=c.TARGET/'validation/nspr-build.log'
    options=['--prefix=/usr','--libdir=/usr/lib','--includedir=/usr/include/nspr','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--enable-64bit','--disable-debug','--enable-optimize']
    if not (out/'Makefile').exists():c.run([str(src/'configure')]+options,out,log,{'HOST_CC':'gcc','HOST_CFLAGS':'-O2'})
    c.run(['make','-j2'],out,log)
    c.run(['make','DESTDIR='+str(dest),'install'],out,log)
    package('nspr',version,dest,['glibc'],options)


def nss():
    root=c.WORK/'desktop-build/nss';src=root/'source/nss'
    if not src.exists():shutil.copytree(FIREFOX/'security/nss',src,symlinks=True)
    version=re.search(r'#define NSS_VERSION\s+"(.*?)"',(src/'lib/nss/nss.h').read_text())[1]
    sign=src/'cmd/shlibsign/sign.sh'
    before=sign.read_text()
    needle='    "${2}"/shlibsign -v -i "${5}"'
    replacement='    KI2_SYSROOT_LIBRARY_PATH="${1}/lib:${4}:$KI2_SYSROOT_LIBRARY_PATH" LD_LIBRARY_PATH= /bin/sh "'+str(c.TARGET/'inputs/distro/scripts/ki2-target-run')+'" "${2}"/shlibsign -v -i "${5}"'
    # Replace only the Unix branch. Host shell utilities retain the host ABI.
    position=before.rfind(needle)
    patch=c.TARGET/'inputs/patches/nss-shlibsign-target-loader.patch'
    if position>=0:
        after=before[:position]+before[position:].replace(needle,replacement,1)
        patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/cmd/shlibsign/sign.sh',tofile='b/cmd/shlibsign/sign.sh')))
        sign.write_text(after)
    env=c.environment()
    cc='gcc '+env['CFLAGS']+' '+env['LDFLAGS']
    options=['BUILD_OPT=1','USE_64=1','NSS_ENABLE_WERROR=0','NSS_DISABLE_GTESTS=1','NSS_USE_SYSTEM_SQLITE=1','USE_SYSTEM_ZLIB=1','ZLIB_LIBS=-lz',
             'NSPR_INCLUDE_DIR='+str(c.SDK/'usr/include/nspr'),'NSPR_LIB_DIR='+str(c.SDK/'usr/lib'),
             'SQLITE_INCLUDE_DIR='+str(c.SDK/'usr/include'),'SQLITE_LIB_DIR='+str(c.SDK/'usr/lib'),
             'NSINSTALL='+str(c.WORK/'desktop-build/nspr/build/config/nsinstall'),
             'CC='+cc,'CXX=g++ '+env['CXXFLAGS']+' '+env['LDFLAGS'],'HOST_CC=gcc','HOST_CXX=g++']
    # NSS captures recursive make output as object names; suppress progress
    # directory messages so they cannot be parsed as prerequisite patterns.
    c.run(['make','--no-print-directory','-C',str(src),'-j2']+options,root,c.TARGET/'validation/nss-build.log',{'KI2_USE_TARGET_LOADER':'1'})
    dist=root/'source/dist';dest=root/'dest';lib=dest/'usr/lib';inc=dest/'usr/include/nss'
    lib.mkdir(exist_ok=True,parents=True);inc.mkdir(exist_ok=True,parents=True)
    for f in list(dist.glob('Linux*/lib/*.so'))+list(dist.glob('Linux*/lib/*.chk')):shutil.copy2(f,lib/f.name)
    for f in (dist/'public/nss').iterdir():
        if f.is_file():shutil.copy2(f,inc/f.name)
    if not (lib/'libnss3.so').exists():raise ValueError('No native NSS shared library')
    pc=lib/'pkgconfig/nss.pc';pc.parent.mkdir(exist_ok=True)
    pc.write_text('prefix=/usr\nlibdir=${prefix}/lib\nincludedir=${prefix}/include/nss\n\nName: NSS\nDescription: Mozilla Network Security Services\nVersion: '+version+'\nRequires: nspr >= 4.36\nLibs: -L${libdir} -lnss3 -lnssutil3 -lsmime3 -lssl3\nCflags: -I${includedir}\n')
    package('nss',version,dest,['glibc','nspr','sqlite','zlib'],options)


if __name__=='__main__':
    for name in sys.argv[1:]:
        if (c.TARGET/'validation'/(name+'-build.json')).exists():print('Already built',name,flush=True);continue
        globals()[name]()
        print('Built and staged',name,flush=True)
