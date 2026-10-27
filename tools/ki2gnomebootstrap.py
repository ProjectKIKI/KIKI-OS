#!/usr/bin/env python3
"""Split verified legacy graphics/fonts for the candidate, without copying its GTK stack."""
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tarfile

import ki2sessioncandidate as c
from ki2integrity import sha256_file


def main():
    snapshot=json.loads((c.BASE/'snapshot.json').read_text())
    record=next(x for x in snapshot['packages'] if x['name']=='kiki-installer-gtk')
    archive=c.BASE/'packages/x86_64'/record['file']
    if sha256_file(archive)!=record['sha256']:
        raise ValueError('Legacy installer archive changed')
    with tarfile.open(archive) as t:
        manifest=json.load(t.extractfile('manifest.json'))
    entries={x['path'].lstrip('/'):x for x in manifest['files']}
    legacy=Path('/home/tang/kiki-build/png-logo-20261017/fixed-payload')
    providers=json.loads((c.TARGET/'validation/base-library-providers.json').read_text())
    providers={n:r for n,r in providers.items() if not r['package'].startswith('kiki-')}
    for report in sorted((c.TARGET/'validation').glob('*-build.json')):
        r=json.loads(report.read_text())
        if r.get('name','').startswith('kiki-'):continue
        if not r.get('file') or not Path(r['file']).exists(): continue
        if sha256_file(r['file'])!=r['sha256']:raise ValueError('Candidate archive changed')
        with tarfile.open(r['file']) as t:
            m=json.load(t.extractfile('manifest.json'))
        for x in m['files']:
            if x['type'] in ['file','symlink'] and '.so' in Path(x['path']).name:
                providers[Path(x['path']).name]=dict(package=r['name'],path=x['path'],package_sha256=r['sha256'])
    files={Path(k).name:k for k,v in entries.items() if v['type'] in ['file','symlink'] and '.so' in Path(k).name}
    dest=c.WORK/'bootstrap-graphics-r2'
    dest.mkdir(exist_ok=False)
    copied={}; dependencies=set(); unresolved=[]
    def copy(relative):
        if relative in copied:return
        entry=entries[relative];p=legacy/relative;out=dest/relative
        if entry['type']=='file':
            if sha256_file(p)!=entry['sha256']:raise ValueError('Changed legacy file '+relative)
        elif entry['type']=='symlink':
            if os.readlink(p)!=entry['target']:raise ValueError('Changed legacy link '+relative)
        else:return
        out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,out,follow_symlinks=False)
        copied[relative]=entry
        if entry['type']=='symlink':
            target=posixpath.normpath(posixpath.join(posixpath.dirname('/'+relative),os.readlink(p))).lstrip('/')
            if target not in entries:raise ValueError('Missing legacy target '+target)
            copy(target)
        elif p.read_bytes()[:4]==b'\x7fELF':
            dynamic=subprocess.run(['readelf','-d',str(p)],check=True,capture_output=True,text=True).stdout
            for needed in re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic):
                if needed in providers:
                    dependencies.add(providers[needed]['package'])
                elif needed in files:copy(files[needed])
                else:unresolved.append(dict(file=relative,needed=needed))
    roots=[k for k in entries if entries[k]['type']!='dir' and (
        Path(k).name.startswith(('libEGL_mesa.so','libgbm.so','libgallium-')) or
        k.startswith('usr/lib64/dri/') or k.startswith('usr/share/glvnd/egl_vendor.d/') or
        k.startswith('usr/share/drirc.d/'))]
    for relative in roots:copy(relative)
    if unresolved:raise ValueError(str(unresolved))
    # Development files must match the exact preserved binary's installed RPM.
    rpm=subprocess.run(['rpm','-q','mesa-libgbm','mesa-libgbm-devel','mesa-libEGL','mesa-libEGL-devel'],capture_output=True,text=True,check=True).stdout
    verified=subprocess.run(['rpm','-V','mesa-libgbm','mesa-libgbm-devel','mesa-libEGL','mesa-libEGL-devel'],capture_output=True,text=True)
    if verified.returncode or verified.stdout:raise ValueError('Host GBM RPM verification failed')
    if sha256_file('/usr/lib64/libgbm.so.1.0.0')!=sha256_file(legacy/'usr/lib64/libgbm.so.1.0.0'):
        raise ValueError('GBM development files do not match preserved binary')
    if sha256_file('/usr/lib64/libEGL_mesa.so.0')!=sha256_file(legacy/'usr/lib64/libEGL_mesa.so.0'):
        raise ValueError('Mesa EGL development files do not match preserved binary')
    dev=[]
    for path in ['/usr/include/gbm.h','/usr/lib64/pkgconfig/gbm.pc','/usr/include/EGL/eglmesaext.h']:
        p=Path(path);out=dest/path.lstrip('/');out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
        dev.append(dict(path=path,sha256=sha256_file(p)))
    # Preserve all bundled license texts under a separate namespace.
    licenses=dest/'usr/share/licenses/kiki-mesa-bootstrap'
    shutil.copytree(legacy/'usr/share/licenses',licenses,symlinks=True)
    raw=dict(name='kiki-mesa-bootstrap',version='25.2.7',release='2',summary='Verified bootstrap Mesa drivers and their non-native library closure',
             license='LicenseRef-KIKI-Verified-Bootstrap-Graphics',tier='desktop',architectures=['x86_64'],
             source=dict(type='local',path=str(dest)),dependencies=dict(build=[],runtime=sorted(dependencies)),build=dict(system='copy'))
    c.package(raw,dest,dict(bootstrap=True,native_source_build=False,parent_package=record,
              copied_files=list(copied.values()),gbm_matching_rpm=rpm,gbm_development_files=dev))
    if (c.TARGET/'validation/kiki-desktop-fonts-build.json').exists():return
    fonts=c.WORK/'bootstrap-fonts';fonts.mkdir(exist_ok=False)
    for relative,entry in entries.items():
        if relative.startswith('usr/share/fonts/') and entry['type']=='file':
            p=legacy/relative
            if sha256_file(p)!=entry['sha256']:raise ValueError('Changed font')
            out=fonts/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
    shutil.copytree(legacy/'usr/share/licenses',fonts/'usr/share/licenses/kiki-desktop-fonts',symlinks=True)
    raw.update(name='kiki-desktop-fonts',version='0.1.0',summary='Preserved desktop fonts including Korean coverage',
               license='LicenseRef-KIKI-Preserved-Fonts',source=dict(type='local',path=str(fonts)),
               dependencies=dict(build=[],runtime=['fontconfig']))
    c.package(raw,fonts,dict(parent_package=record,unchanged_font_bytes=True))


if __name__=='__main__':main()
