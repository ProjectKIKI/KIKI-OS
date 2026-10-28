"""Build desktop additions in an isolated target SDK; preserve all old candidates."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'tools'))
import ki2build
from ki2stage3candidate import read_manifest, recipe_toml

work = Path('/tmp/kiki-gnome-native-apps-20261028')
original = Path('/home/tang/kiki-build/gnome50-session-20261017')
sdk = work / 'sdk'
if not sdk.exists():
    subprocess.run(['cp', '-a', '--reflink=auto', str(Path('/tmp/kiki-desktop-apps-20261027/sdk')), str(sdk)], check=True)
venv = original / 'venv/bin'
tools = original / 'host-tools/bin'
libdirs = [sdk / p for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64', 'usr/lib/pulseaudio')]
env = dict(os.environ, PATH=str(work/'host-tools')+':'+str(venv)+':'+str(tools)+':/usr/bin:/bin:/usr/sbin',
           PKG_CONFIG_SYSROOT_DIR=str(sdk), PKG_CONFIG_LIBDIR=':'.join(str(sdk/p) for p in ('usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig','lib64/pkgconfig')),
           CFLAGS='--sysroot='+str(sdk)+' -O2 -pipe -fPIC', CXXFLAGS='--sysroot='+str(sdk)+' -O2 -pipe -fPIC',
           LDFLAGS='--sysroot='+str(sdk)+' '+ ' '.join('-L'+str(p)+' -Wl,-rpath-link,'+str(p) for p in libdirs),
           KI2_SYSROOT=str(sdk), KI2_SYSROOT_LIBRARY_PATH=':'.join(map(str,libdirs)),
           KI2_USE_TARGET_LOADER='1', KI2_REPO_ROOT=str(repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017/inputs'),
           LC_ALL='C', PYTHONNOUSERSITE='1', GETTEXTDATADIRS=str(sdk/'usr/share/gettext'),
           XDG_DATA_DIRS=str(sdk/'usr/share')+':/usr/local/share:/usr/share')
def write_generated(path, value):
    if path.exists() and path.read_text()==value:return
    import uuid
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    temporary.write_text(value);temporary.replace(path)

cross = work / 'cross.ini'
wrapper=work/'target-run'
write_generated(wrapper,'#!/bin/sh\nexec '+str(sdk/'lib64/ld-linux-x86-64.so.2')+' --library-path '+':'.join(map(str,libdirs))+' "$@"\n')
wrapper.chmod(0o755)
write_generated(cross,"[binaries]\nc='gcc'\ncpp='"+str(tools/'clang++')+"'\nar='ar'\nstrip='strip'\npkg-config='/usr/bin/pkg-config'\nexe_wrapper='"+str(wrapper)+"'\n[host_machine]\nsystem='linux'\ncpu_family='x86_64'\ncpu='x86_64'\nendian='little'\n[properties]\nneeds_exe_wrapper=true\n")
records = {r['name']: r for r in json.loads((repo/'artifacts/gnome-native-apps-20261028/sources.json').read_text())}
packages = work / 'packages'
packages.mkdir(exist_ok=True)


def run(args, extra=None):
    print('$', *map(str,args), flush=True)
    subprocess.run(list(map(str,args)), env=dict(env, **(extra or {})), check=True)


def package(name, version, dest, deps, source=None, license='LGPL-3.0-or-later', release='1'):
    for forbidden in ['tmp','home','mnt']:
        if (dest/forbidden).exists():raise RuntimeError('Staged host path in package: '+str(dest/forbidden))
    (dest/'usr/share/info/dir').unlink(missing_ok=True)
    raw = dict(name=name, version=version, release=release, summary='KIKI native desktop '+name,
               license=license, tier='desktop', architectures=['x86_64'],
               source=dict(type='local',path=str(dest)), dependencies=dict(build=[],runtime=deps), build=dict(system='copy'))
    recipes = work/'recipes'
    recipes.mkdir(exist_ok=True)
    (recipes/(name+'.toml')).write_text(recipe_toml([raw]))
    recipe = ki2build.load_recipes(recipes)[name]
    output = packages/ki2build.package_filename(recipe,'x86_64')
    if not output.exists():
        # Strip temporary SDK paths from the generated ELF runpaths.
        for p in dest.rglob('*'):
            if p.is_symlink() or not p.is_file(): continue
            with p.open('rb') as f: elf = f.read(4)==b'\x7fELF'
            if elf:
                needed = subprocess.run([str(tools/'patchelf'),'--print-needed',str(p)],capture_output=True,text=True)
                for library in needed.stdout.splitlines():
                    if library.startswith('/'):
                        provider=Path(library).resolve(strict=True)
                        if not provider.is_relative_to(sdk.resolve()):raise RuntimeError('Non-SDK absolute dependency: '+library)
                        soname=subprocess.check_output([str(tools/'patchelf'),'--print-soname',str(provider)],text=True).strip()
                        if not soname or '/' in soname:raise RuntimeError('Dependency lacks a portable SONAME: '+library)
                        run([tools/'patchelf','--replace-needed',library,soname,p])
                r = subprocess.run([str(tools/'patchelf'),'--print-rpath',str(p)],capture_output=True,text=True)
                if r.returncode == 0 and any(x in r.stdout for x in ('/tmp/','/home/','/mnt/')):
                    kept = ':'.join(x for x in r.stdout.strip().split(':') if x and not any(y in x for y in ('/tmp/','/home/','/mnt/')))
                    run([tools/'patchelf','--set-rpath',kept,p])
        ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,dest,output,ki2build.stable_hash(dict(recipe=recipe.digest, source=source)),{})
    subprocess.run(['cp','-a',str(dest)+'/.',str(sdk)],check=True)
    record_path=work/'output-records.json'
    import fcntl
    with (work/'output-records.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        records_out=json.loads(record_path.read_text()) if record_path.exists() else {}
        records_out[name]=dict(file=str(output),sha256=ki2build.file_sha256(output),version=version,release=release,source=source)
        record_path.write_text(json.dumps(records_out,indent=2)+'\n')
    return output
