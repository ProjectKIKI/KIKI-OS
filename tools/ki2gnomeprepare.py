#!/usr/bin/env python3
"""Stage only verified native package payloads into the disposable desktop SDK."""
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import ki2sessioncandidate as c


def stage(payload):
    subprocess.run(['cp','-a',str(payload)+'/.',str(c.SDK)],check=True)


def original_provider(name):
    snapshot=json.loads((c.BASE/'snapshot.json').read_text())
    r=next(x for x in snapshot['packages'] if x['name']==name)
    f=c.BASE/'packages/x86_64'/r['file']
    if c.sha256_file(f)!=r['sha256']:raise ValueError('SHA '+name)
    d=c.WORK/'sdk-providers'/name
    if not d.exists():c.build.extract_package_rootfs(f,d)
    for p in d.rglob('*'):
        target=c.SDK/p.relative_to(d)
        if p.is_symlink() and target.is_dir() and not target.is_symlink():
            backup=c.WORK/'sdk-compat-backups'/name/p.relative_to(d)
            backup.parent.mkdir(parents=True,exist_ok=True)
            target.rename(backup)
    stage(d)
    print('Staged native provider',name,flush=True)


def inspect_source(name):
    lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
    s=next(x for x in lock['sources'] if x.get('name')==name or Path(x['file']).name.startswith(name+'-'))
    if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('Source SHA '+name)
    dest=c.WORK/'desktop-build'/name/'source'
    if not dest.exists():
        dest.mkdir(parents=True)
        with tarfile.open(s['file']) as t:t.extractall(dest)
    root=next(x for x in dest.iterdir() if x.is_dir())
    out=c.TARGET/'inputs/meson-inspect'/name;out.mkdir(exist_ok=True,parents=True)
    for f in ['meson.build','meson_options.txt','meson.options','CMakeLists.txt','configure.ac']:
        if (root/f).exists():shutil.copy2(root/f,out/f)
    print('Inspected source',name,flush=True)


def main():
    for name in ['glib','gtk']:
        if not (c.TARGET/'validation'/(name+'-build.json')).exists():raise ValueError('Not finished '+name)
        stage(c.WORK/'desktop-build'/name/'dest')
    print('Staged GLib and GTK',flush=True)
    snapshot=json.loads((c.BASE/'snapshot.json').read_text())
    for name in ['gnutls','p11-kit','libgcrypt','libgpg-error','nettle','gmp','libtasn1','libidn2','libunistring',
                 'libgudev','json-glib','dconf','gsettings-desktop-schemas','polkit','upower']:
        r=next(x for x in snapshot['packages'] if x['name']==name)
        f=c.BASE/'packages/x86_64'/r['file']
        if c.sha256_file(f)!=r['sha256']:raise ValueError('SHA '+name)
        d=c.WORK/'sdk-providers'/name
        if not d.exists():c.build.extract_package_rootfs(f,d)
        stage(d)
    print('Staged verified native providers',flush=True)
    lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
    for name in ['librsvg','colord','libei','libdisplay-info','gcr','libsecret','glib-networking','libsoup','libadwaita']:
        s=next(x for x in lock['sources'] if x.get('name')==name or Path(x['file']).name.startswith(name+'-'))
        src=c.WORK/'desktop-build'/name/'source'
        if not src.exists():
            src.mkdir(parents=True)
            with tarfile.open(s['file']) as t:t.extractall(src)
        root=next(x for x in src.iterdir() if x.is_dir())
        for n in ['meson.options','meson_options.txt','meson.build']:
            if (root/n).exists():
                d=c.TARGET/'inputs/meson-inspect'/name;d.mkdir(exist_ok=True,parents=True);shutil.copy2(root/n,d/n)
    print('Source inspection ready',flush=True)


if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='--inspect':
        for name in sys.argv[2:]:inspect_source(name)
    elif len(sys.argv)>1:
        for name in sys.argv[1:]:original_provider(name)
    else:main()
