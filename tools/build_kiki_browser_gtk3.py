"""Build private dual-backend GTK3/Cairo for Firefox; never install into the shared GTK stack."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

from build_kiki_browser_x11 import unpack, build as build_x11


def write_program(path, text):
    path.write_text('#!/bin/sh\nset -eu\n'+text+'\n');path.chmod(0o755)


def merge_private(source, target):
    for item in sorted(source.rglob('*'),key=lambda p:len(p.parts)):
        dest=target/item.relative_to(source)
        assert dest.parent.resolve().is_relative_to(target.resolve())
        if item.is_dir() and not item.is_symlink():dest.mkdir(exist_ok=True)
        else:
            if dest.is_symlink():dest.unlink()
            if item.is_symlink():
                if dest.exists():dest.unlink()
                dest.symlink_to(os.readlink(item))
            else:shutil.copy2(item,dest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['sdk','work','inputs','lock','stage']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--x11-sdk',type=Path)
    p.add_argument('--meson',default='meson')
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();root=Path(__file__).resolve().parents[1];work=a.work.resolve();inputs=a.inputs.resolve();stage=a.stage.resolve()
    assert a.resume or (not work.exists() and not stage.exists());work.mkdir(parents=True,exist_ok=a.resume);inputs.mkdir(parents=True,exist_ok=True)
    assert not work.is_relative_to(a.sdk.resolve()) and not stage.is_relative_to(a.sdk.resolve())
    assert subprocess.check_output([a.meson,'--version'],text=True).strip()=='1.9.2','Use the isolated Meson 1.9.2 profile'
    x11=a.x11_sdk.resolve() if a.x11_sdk else work/'x11-work/sdk'
    if not a.x11_sdk:
        build_x11(a.sdk,work/'x11-work',inputs,root/'distro/manifests/kiki-browser-x11-20261107.json',work/'x11-payload')
    private=work/'sdk';assert x11.is_dir() and private!=a.sdk.resolve()
    receipt=work/'progress.json'
    if a.resume:
        progress=json.loads(receipt.read_text());assert progress['stage']==str(stage) and progress['base_sdk']==str(a.sdk.resolve()) and private.is_dir()
    else:
        subprocess.run(['cp','-a','--reflink=auto',str(x11),str(private)],check=True);progress=dict(stage=str(stage),base_sdk=str(a.sdk.resolve()),completed=[]);receipt.write_text(json.dumps(progress))
    for path in private.rglob('*.la'):path.unlink()
    lock=json.loads(a.lock.read_text());assert lock['schema']=='kiki-browser-private-gtk3-v1'
    for item in lock['sources']:
        target=inputs/item['file'];assert target.name==item['file']
        if not target.exists():
            with urllib.request.urlopen(item['url'],timeout=120) as r:data=r.read()
            assert hashlib.sha256(data).hexdigest()==item['sha256'];target.write_bytes(data)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']
    host_pc=work/'host-pkg-config';target_pc=work/'target-pkg-config';wrapper=work/'target-run'
    write_program(host_pc,"exec env PKG_CONFIG_PATH= PKG_CONFIG_SYSROOT_DIR= PKG_CONFIG_LIBDIR=/usr/lib64/pkgconfig:/usr/share/pkgconfig /usr/bin/pkg-config \"$@\"")
    dirs=[private/p for p in ['usr/lib','usr/lib64','lib64']]
    libdirs=':'.join(str(private/p) for p in ['usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig','lib64/pkgconfig'])
    write_program(target_pc,'exec env PKG_CONFIG_PATH= PKG_CONFIG_SYSROOT_DIR='+str(private)+' PKG_CONFIG_LIBDIR='+libdirs+' /usr/bin/pkg-config "$@"')
    write_program(wrapper,'exec '+str(private/'lib64/ld-linux-x86-64.so.2')+' --library-path '+':'.join(map(str,dirs))+' "$@"')
    cargs=['-O2','-pipe','-fstack-protector-strong'];linkargs=['--sysroot='+str(private)]+[flag for d in dirs for flag in ['-L'+str(d),'-Wl,-rpath-link,'+str(d)]]+['-Wl,-z,relro,-z,now']
    cross=work/'cross.ini';native=work/'native.ini'
    cross.write_text("[binaries]\nc="+repr(['gcc','--sysroot='+str(private)])+"\ncpp="+repr(['g++','--sysroot='+str(private)])+"\nar='ar'\nstrip='strip'\npkg-config="+repr(str(target_pc))+"\nexe_wrapper="+repr(str(wrapper))+"\n[host_machine]\nsystem='linux'\ncpu_family='x86_64'\ncpu='x86_64'\nendian='little'\n[properties]\nneeds_exe_wrapper=true\n[built-in options]\nc_args="+repr(cargs)+"\ncpp_args="+repr(cargs)+"\nc_link_args="+repr(linkargs)+"\ncpp_link_args="+repr(linkargs)+"\n")
    native.write_text("[binaries]\nc='gcc'\ncpp='g++'\npkg-config="+repr(str(host_pc))+"\n")
    env=dict(os.environ,PYTHONNOUSERSITE='1',LC_ALL='C',PKG_CONFIG_PATH='',PKG_CONFIG_SYSROOT_DIR='',PKG_CONFIG_LIBDIR='/usr/lib64/pkgconfig:/usr/share/pkgconfig')
    for key in ['CFLAGS','CXXFLAGS','LDFLAGS','LD_LIBRARY_PATH']:env.pop(key,None)
    stage.mkdir(parents=True,exist_ok=a.resume);compat=stage/'usr/libexec/kiki-incident-browser/153.6.0esr/compat';compat.mkdir(parents=True,exist_ok=a.resume)
    options={
        'epoxy':['-Dglx=yes','-Degl=yes','-Dx11=true','-Dtests=false'],
        'cairo':['-Dfontconfig=enabled','-Dfreetype=enabled','-Dpng=enabled','-Dzlib=enabled','-Dglib=enabled','-Dxlib=enabled','-Dxcb=enabled','-Dlzo=disabled','-Dspectre=disabled','-Dsymbol-lookup=disabled','-Dtests=disabled','-Dgtk_doc=false'],
        'gtk3':['-Dx11_backend=true','-Dwayland_backend=true','-Dbroadway_backend=false','-Dintrospection=false','-Ddemos=false','-Dexamples=false','-Dtests=false','-Dinstalled_tests=false','-Dgtk_doc=false','-Dman=false','-Dprint_backends=file'],
    }
    for item in lock['sources']:
        name=item['name']
        if name in progress['completed']:continue
        source_dir=work/(name+'-source');src=next(source_dir.iterdir()) if a.resume and source_dir.exists() else unpack(inputs/item['file'],source_dir)
        build=work/(name+'-build');dest=work/(name+'-stage')
        with (work/(name+'.log')).open('w') as log:
            setup=[a.meson,'setup',str(build),str(src),'--cross-file',str(cross),'--native-file',str(native),'--prefix=/usr','--libdir=lib','--buildtype=release','--wrap-mode=nofallback','-Ddefault_library=shared',*options[name]]
            if (build/'build.ninja').exists():setup.insert(2,'--reconfigure')
            for command,extra in [(setup,{}),([a.meson,'compile','-C',str(build),'-j','2'],{}),([a.meson,'install','-C',str(build),'--no-rebuild'],{'DESTDIR':str(dest)})]:
                subprocess.run(command,env=dict(env,**extra),stdout=log,stderr=subprocess.STDOUT,check=True)
        merge_private(dest,private)
        prefixes=['libepoxy.so'] if name=='epoxy' else ['libcairo.so','libcairo-gobject.so'] if name=='cairo' else ['libgtk-3.so','libgdk-3.so']
        for prefix in prefixes:
            files=list((dest/'usr/lib').glob(prefix+'*'));assert files,prefix
            for source in files:
                target=compat/source.name;assert not target.exists() and not target.is_symlink()
                if source.is_symlink():target.symlink_to(os.readlink(source))
                else:shutil.copy2(source,target)
        for license_name in ['COPYING','COPYING-LGPL-2.1','COPYING-MPL-1.1']:
            source=src/license_name
            if source.is_file():
                target=stage/'usr/share/licenses/kiki-browser-gtk3'/(name+'-'+license_name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        print('Private browser source build completed:',name,item['version'],flush=True)
        progress['completed'].append(name);receipt.write_text(json.dumps(progress,indent=2))
    versions={}
    for tool in ['gcc','pkg-config','glib-compile-resources','wayland-scanner']:
        result=subprocess.run([tool,'--version'],capture_output=True,text=True,check=True);versions[tool]=(result.stdout or result.stderr).splitlines()[0]
    (work/'build-inputs.json').write_text(json.dumps(dict(base_sdk=str(a.sdk.resolve()),x11_sdk=str(x11),private_sdk=str(private),meson=a.meson,source_lock=lock,host_tools=versions,target_and_native_pkg_config_separate=True,builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),resumed=a.resume),indent=2))


if __name__=='__main__':main()
