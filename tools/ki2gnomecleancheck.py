#!/usr/bin/env python3
"""Run target library and configuration checks inside an assembled native root."""
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import ki2sessioncandidate as c

r=json.loads((c.TARGET/'validation/desktop-root-assembled.json').read_text())
root=Path(r['root'])
if not root.resolve().is_relative_to(c.WORK.resolve()):raise ValueError('Unexpected root')
bad=[]
for directory in ['usr/lib/systemd','usr/share/dbus-1','etc','usr/share/wayland-sessions','usr/share/gnome-session']:
    for p in (root/directory).rglob('*'):
        if p.is_file() and not p.is_symlink() and p.stat().st_size<1024*1024:
            data=p.read_bytes()
            if str(c.WORK).encode() in data or str(c.REPO).encode() in data:bad.append(str(p.relative_to(root)))
if bad:raise ValueError('Build paths in runtime configuration: '+str(bad))
for path in ['run','tmp','dev','proc','sys']:(root/path).mkdir(exist_ok=True)
for name,minor in [('null',3),('zero',5),('random',8),('urandom',9)]:
    p=root/'dev'/name
    if not p.exists():os.mknod(p,stat.S_IFCHR|0o666,os.makedev(1,minor));p.chmod(0o666)
log=c.TARGET/'validation/desktop-clean-runtime.log'
commands=[['/usr/bin/gio-querymodules','/usr/lib/gio/modules'],['/usr/bin/glib-compile-schemas','/usr/share/glib-2.0/schemas'],['/usr/bin/gnome-shell','--version'],['/usr/sbin/gdm','--version'],['/usr/bin/gjs','-c',"imports.gi.versions.Gtk='4.0'; imports.gi.versions.Adw='1'; const {Gtk,Adw,Gio}=imports.gi; if(!Gio.TlsBackend.get_default().supports_tls()) throw Error('TLS missing'); print('CLEAN_ROOT_GTK_ADW_TLS_OK',Gtk.get_minor_version(),Adw.get_minor_version());"]]
commands.append(['/usr/bin/gjs','-c',"for (const [name,version] of [['GWeather','4.0'],['Geoclue','2.0'],['GnomeBluetooth','3.0'],['IBus','1.0'],['Rsvg','2.0'],['Soup','3.0'],['UPowerGlib','1.0'],['Gcr','4'],['ECal','2.0'],['EDataServer','1.2'],['GnomeAutoar','0.1'],['GnomeDesktop','4.0'],['Gdm','1.0'],['Polkit','1.0'],['PolkitAgent','1.0']]) { imports.gi.versions[name]=version; void imports.gi[name]; print('SHELL_PUBLIC_GI_OK',name,version); }"])
shutil.copy2(c.WORK/'runtime-smoke/nss-probe',root/'run/nss-probe')
commands.append(['/run/nss-probe'])
commands.append(['/usr/bin/gjs','-c',"imports.gi.versions.GWeather='4.0'; if (!imports.gi.GWeather.Location.get_world()) throw Error('Weather location database missing'); print('GWEATHER_TARGET_DATABASE_OK');"])
commands.append(['/usr/bin/gnome-shell','--list-modes'])
with log.open('w') as stream:
    for command in commands:
        stream.write('$ '+' '.join(command)+'\n');stream.flush()
        subprocess.run(['/usr/sbin/chroot',str(root),'/usr/bin/env','-i','PATH=/usr/bin:/usr/sbin:/bin:/sbin','HOME=/root','LANG=en_US.UTF-8','GSETTINGS_BACKEND=memory']+command,stdout=stream,stderr=subprocess.STDOUT,check=True)
c.save(c.TARGET/'validation/desktop-clean-runtime.json',dict(passed=True,scope='Clean native root chroot; no host/installer libraries',commands=commands,root_report_sha256=c.sha256_file(c.TARGET/'validation/desktop-root-assembled.json'),graphical_login_tested=False))
print('Clean native root library/configuration checks passed',flush=True)
