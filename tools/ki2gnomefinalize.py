#!/usr/bin/env python3
"""Finalize dependency metadata in new candidate releases, preserving predecessors."""
import contextlib
import io
import json
from pathlib import Path
import sys
import zipfile
import tomli
import ki2sessioncandidate as c

EXTRA = {
 'libepoxy':['libglvnd'],
 'gdk-pixbuf':['shared-mime-info'],
 'libadwaita':['appstream'],
 'gnome-shell':['gnome-autoar','libgweather','geoclue','gnome-bluetooth','ibus','librsvg','libsoup','upower','pulseaudio','gnome-settings-daemon-schemas','adwaita-icon-theme','kiki-desktop-fonts'],
 'mutter':['python3-argcomplete'],
 'gtk':['adwaita-icon-theme','hicolor-icon-theme','kiki-desktop-fonts'],
 'python':['bzip2'],
}

def argcomplete():
    if (c.TARGET/'validation/python3-argcomplete-build.json').exists():return
    lock=json.loads((c.TARGET/'validation/host-extra-python-lock.json').read_text())
    r=next(x for x in lock['packages'] if x['name']=='argcomplete')
    if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Wheel changed')
    dest=c.WORK/'target-argcomplete'
    dest.mkdir(exist_ok=False)
    with zipfile.ZipFile(r['file']) as z:
        for n in z.namelist():
            if n.endswith('/') or '.data/' in n:continue
            if n.startswith('/') or '..' in Path(n).parts:raise ValueError('Unsafe wheel')
            p=dest/'usr/lib/python3.12/site-packages'/n
            p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(z.read(n))
    raw=dict(name='python3-argcomplete',version=r['version'],release='1',summary='Python argument completion for Mutter gdctl',license='Apache-2.0',tier='desktop',architectures=['x86_64'],source=dict(type='url',url=r['url'],sha256=r['sha256']),dependencies=dict(build=[],runtime=['python']),build=dict(system='copy'))
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(wheel=r,pure_python=True,target_python='3.12'))
    print('Packaged target argcomplete',flush=True)

def finalize():
    root_scope='--root' in sys.argv
    audit=json.loads((c.TARGET/'validation'/('desktop-root-elf-suppliers.json' if root_scope else 'desktop-elf-suppliers.json')).read_text())
    if audit['errors']:raise ValueError('ELF errors remain')
    for entry in audit['packages']:
        name=entry['name'];report=c.TARGET/'validation'/(name+'-build.json')
        r=json.loads(report.read_text()) if report.exists() else dict(name=name,file=entry['file'],sha256=entry['sha256'],provenance={})
        if r['sha256']!=entry['sha256'] or c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Stale ELF audit: '+name)
        recipe=c.TARGET/'recipes'/(name+'.toml')
        raw=tomli.loads(recipe.read_text())['recipe'][0] if recipe.exists() else next(x for x in json.loads((c.BASE/'recipes/catalog.json').read_text())['recipes'] if x['name']==name)
        previous=set(raw['dependencies']['runtime'])
        after=(previous|set(entry['additional_direct_dependencies'])|set(EXTRA.get(name,[])))-{name}
        license_change=name=='libepoxy' and raw['license']!='MIT'
        if previous==after and not license_change:continue
        raw['release']=str(int(raw['release'])+1)
        raw['dependencies']['runtime']=sorted(after)
        if name=='libepoxy':raw['license']='MIT'
        dest=c.WORK/'metadata-finalized'/(name+'-'+raw['release'])
        if dest.exists():raise FileExistsError(dest)
        c.build.extract_package_rootfs(Path(r['file']),dest)
        olddir=c.TARGET/'validation/repacked-predecessors';olddir.mkdir(exist_ok=True)
        c.save(olddir/(Path(r['file']).name+'.json'),r)
        provenance=dict(r['provenance'],dependency_metadata_finalized=True,parent_package_sha256=r['sha256'],added_runtime_dependencies=sorted(after-previous),payload_unchanged=True)
        with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,provenance)
        print('Finalized',name,sorted(after-previous),flush=True)

if __name__=='__main__':
    if sys.argv[1:] == ['argcomplete']:argcomplete()
    else:finalize()
