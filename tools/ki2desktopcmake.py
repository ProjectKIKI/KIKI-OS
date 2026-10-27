#!/usr/bin/env python3
"""Build locked small CMake dependencies in the dedicated desktop SDK."""
import argparse
import contextlib
import difflib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

import ki2sessioncandidate as c

PRESETS = {
    'libsndfile': dict(options=['-DBUILD_SHARED_LIBS=ON','-DBUILD_TESTING=OFF','-DBUILD_PROGRAMS=OFF','-DBUILD_EXAMPLES=OFF','-DENABLE_EXTERNAL_LIBS=OFF','-DENABLE_MPEG=OFF','-DINSTALL_MANPAGES=OFF','-DENABLE_CPACK=OFF'],
                       dependencies=['glibc'],license='LGPL-2.1-or-later',notice='COPYING'),
    'libical': dict(options=['-DSHARED_ONLY=ON','-DWITH_CXX_BINDINGS=OFF','-DICAL_GLIB=ON','-DGOBJECT_INTROSPECTION=ON','-DICAL_BUILD_DOCS=OFF','-DICAL_GLIB_VAPI=OFF','-DLIBICAL_BUILD_TESTING=OFF','-DUSE_BUILTIN_TZDATA=OFF'],
                    dependencies=['glib','libxml2','icu','tzdata'],license='LGPL-2.1-only OR MPL-2.0',notice='LICENSE'),
    'evolution-data-server': dict(options=['-DLIB_INSTALL_DIR=/usr/lib','-DCMAKE_SKIP_RPATH=OFF','-DCMAKE_INSTALL_RPATH=/usr/lib/evolution-data-server','-DSYSCONF_INSTALL_DIR=/etc','-DENABLE_GTK=OFF','-DENABLE_GTK4=OFF','-DENABLE_GOA=OFF','-DENABLE_UOA=OFF',
                                          '-DENABLE_OAUTH2_WEBKITGTK=OFF','-DENABLE_OAUTH2_WEBKITGTK4=OFF','-DENABLE_GOOGLE=OFF','-DENABLE_GOOGLE_AUTH=OFF','-DENABLE_WEATHER=OFF',
                                          '-DENABLE_CANBERRA=OFF','-DWITH_LIBDB=OFF','-DWITH_OPENLDAP=OFF','-DWITH_KRB5=OFF','-DENABLE_VALA_BINDINGS=OFF','-DENABLE_GTK_DOC=OFF',
                                          '-DENABLE_INTROSPECTION=ON','-DENABLE_TESTS=OFF','-DENABLE_INSTALLED_TESTS=OFF','-DENABLE_EXAMPLES=OFF','-DENABLE_PHONENUMBER=OFF','-DENABLE_SMIME=ON'],
                                  dependencies=['glib','json-glib','util-linux','icu','libsecret','libxml2','libsoup','nss','nspr','sqlite','libical'],license='LGPL-2.1-or-later',notice='COPYING'),
    'json-c': dict(options=['-DBUILD_SHARED_LIBS=ON','-DBUILD_STATIC_LIBS=OFF','-DBUILD_TESTING=OFF','-DDISABLE_WERROR=ON'],
                   dependencies=['glibc'], license='MIT', notice='COPYING'),
}


def build(name):
    preset = PRESETS[name]
    source = next(x for x in json.loads((c.TARGET/'gnome50-source-lock.json').read_text())['sources'] if x.get('name') == name)
    archive = Path(source['file'])
    if c.sha256_file(archive) != source['sha256']:
        raise ValueError('Source SHA changed')
    root = c.WORK/'desktop-build'/name
    src = root/'source'
    if not src.exists():
        src.mkdir(parents=True)
        with tarfile.open(archive) as t:
            t.extractall(src)
    src = next(p for p in src.iterdir() if p.is_dir())
    patches=[]
    if name=='evolution-data-server':
        f=src/'cmake/modules/GObjectIntrospection.cmake';before=f.read_text()
        after=before.replace(' LDFLAGS=\n',' "LDFLAGS=$ENV{LDFLAGS}"\n')
        patch=c.TARGET/'inputs/patches/eds-gi-preserve-target-link-flags.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/cmake/modules/GObjectIntrospection.cmake',tofile='b/cmake/modules/GObjectIntrospection.cmake')));f.write_text(after)
        patches.append(dict(path=str(patch),sha256=c.sha256_file(patch)))
        before=f.read_text()
        after=before.replace('${SHARE_INSTALL_PREFIX}/gir-1.0','${CMAKE_SYSROOT}${SHARE_INSTALL_PREFIX}/gir-1.0')
        patch=c.TARGET/'inputs/patches/eds-gi-target-gir-path.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/cmake/modules/GObjectIntrospection.cmake',tofile='b/cmake/modules/GObjectIntrospection.cmake')));f.write_text(after)
        patches.append(dict(path=str(patch),sha256=c.sha256_file(patch)))
        f=src/'src/addressbook/libebook-contacts/CMakeLists.txt';before=f.read_text()
        after=before.replace('COMMAND ${CMAKE_CURRENT_BINARY_DIR}/gen-western-table ', 'COMMAND gen-western-table ')
        patch=c.TARGET/'inputs/patches/eds-western-generator-emulator.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/src/addressbook/libebook-contacts/CMakeLists.txt',tofile='b/src/addressbook/libebook-contacts/CMakeLists.txt')));f.write_text(after)
        patches.append(dict(path=str(patch),sha256=c.sha256_file(patch)))
    if name=='libical':
        f=src/'src/libical-glib/CMakeLists.txt';before=f.read_text()
        after=before.replace('if(CMAKE_CROSSCOMPILING)\n','if(CMAKE_CROSSCOMPILING AND NOT CMAKE_CROSSCOMPILING_EMULATOR)\n')
        patch=c.TARGET/'inputs/patches/libical-cross-generator-emulator.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/src/libical-glib/CMakeLists.txt',tofile='b/src/libical-glib/CMakeLists.txt')));f.write_text(after)
        patches.append(dict(path=str(patch),sha256=c.sha256_file(patch)))
    out = root/'build'; dest = root/'dest'; dest.mkdir(exist_ok=True)
    options = ['-DCMAKE_SYSTEM_NAME=Linux','-DCMAKE_SYSROOT='+str(c.SDK),'-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_SYSTEM_PROCESSOR=x86_64','-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER','-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY',
               '-DCMAKE_CROSSCOMPILING_EMULATOR=/bin/sh;'+str(c.TARGET/'inputs/distro/scripts/ki2-target-run'),
               '-DCMAKE_INSTALL_PREFIX=/usr','-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_SKIP_RPATH=ON'] + preset['options']
    log = c.TARGET/'validation'/(name+'-build.log')
    out.mkdir(exist_ok=True)
    shutil.copy2(c.WORK/'g-ir-compiler.real',out/'g-ir-compiler.real')
    env=dict(KI2_REPO_ROOT=str(c.TARGET/'inputs'),KI2_BUILD_DIR=str(out),KI2_USE_TARGET_LOADER='1',
             XDG_DATA_DIRS=str(c.SDK/'usr/share'),
             GI_CROSS_LAUNCHER='/bin/sh '+str(c.TARGET/'inputs/distro/scripts/ki2-target-run'),
             PATH=str(c.VENV/'bin')+':/usr/bin:/bin')
    env['KI2_SYSROOT_LIBRARY_PATH']=str(out/'lib')+':'+c.environment()['KI2_SYSROOT_LIBRARY_PATH']
    env['LDFLAGS']='-L'+str(out/'lib')+' -Wl,-rpath-link,'+str(out/'lib')+' '+c.environment()['LDFLAGS']
    c.run(['cmake','-S',str(src),'-B',str(out),'-G','Ninja']+options,root,log,env)
    library_dirs=[out/'lib']+sorted({p.parent for p in out.rglob('CMakeFiles')})
    env['KI2_SYSROOT_LIBRARY_PATH']=':'.join(str(p) for p in library_dirs)+':'+c.environment()['KI2_SYSROOT_LIBRARY_PATH']
    env['LDFLAGS']=' '.join('-Wl,-rpath-link,'+str(p) for p in library_dirs)+' '+c.environment()['LDFLAGS']
    if name=='evolution-data-server':
        c.run(['cmake','-S',str(src),'-B',str(out),'-G','Ninja']+options,root,log,env)
    c.run(['cmake','--build',str(out),'--parallel','2'],root,log,env)
    c.run(['cmake','--install',str(out)],root,log,dict(env,DESTDIR=str(dest)))
    licenses = dest/'usr/share/licenses'/name; licenses.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src/preset['notice'],licenses/preset['notice'])
    raw = dict(name=name,version=source['version'],release='2' if name=='evolution-data-server' else '1',summary='Native GNOME desktop dependency',license=preset['license'],
               tier='library',architectures=['x86_64'],source=dict(type='url',url=source['url'],sha256=source['sha256']),
               dependencies=dict(build=['linux-headers'],runtime=preset['dependencies']),build=dict(system='cmake',configure_options=options))
    with contextlib.redirect_stdout(io.StringIO()):
        c.package(raw,dest,dict(source_lock=source,cmake_options=options,patches=patches))
    subprocess.run(['cp','-a',str(dest)+'/.',str(c.SDK)],check=True)
    print('Built and staged',name,source['version'])


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name',choices=list(PRESETS))
    args=parser.parse_args()
    build(args.name)
