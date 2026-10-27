#!/usr/bin/env python3
"""Create SHA-checked data media for the isolated GNOME VM, without publishing an index."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import ki2sessioncandidate as c

version=sys.argv[1]
if not version.isdecimal():raise ValueError('Numeric media revision required')
plan=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
if plan['errors'] or plan['conflicts'] or plan['installer_bundle_in_target']:raise ValueError('Invalid native root plan')
media=c.WORK/('gnome-lab-media-'+version);media.mkdir(exist_ok=False)
packages=media/'packages';packages.mkdir()
records=[]
for r in plan['packages']:
    source=Path(r['file'])
    if c.sha256_file(source)!=r['sha256']:raise ValueError('Changed archive')
    out=packages/source.name;shutil.copy2(source,out)
    if c.sha256_file(out)!=r['sha256']:raise ValueError('Copy SHA mismatch')
    records.append(dict(name=r['name'],file='packages/'+out.name,sha256=r['sha256']))
c.save(media/'overlay.json',dict(packages=records,scope='isolated lab only; no package-manager upgrade claim'))
shutil.copy2(c.REPO/'tools/ki2session_lab_apply.py',media/'apply.py')
shutil.copy2(c.REPO/'tools/ki2gnomevmreport.py',media/'vm-report.py')
post=media/'configure-desktop.sh'
post.write_text('''#!/bin/sh
set -eu
[ "$(hostname)" = kiki-lab ]
systemd-sysusers
systemd-tmpfiles --create
ldconfig
glib-compile-schemas /usr/share/glib-2.0/schemas
gio-querymodules /usr/lib/gio/modules
update-mime-database /usr/share/mime
gdk-pixbuf-query-loaders --update-cache
gtk4-update-icon-cache -f -t /usr/share/icons/hicolor
fc-cache -f
systemctl daemon-reload
systemctl enable gdm.service
cp -a /etc/systemd/system/default.target /var/lib/kiki-session-lab/default.target.before-gnome
if [ ! -L /etc/systemd/system/default.target ]; then
    mv /etc/systemd/system/default.target /var/lib/kiki-session-lab/default.target.regular
fi
systemctl set-default graphical.target
printf 'GNOME_LAB_CONFIGURATION_COMPLETE\\n'
''');post.chmod(0o755)
iso=c.TARGET/'iso'/('gnome50-runtime-lab-'+version+'.iso');iso.parent.mkdir(exist_ok=True)
if iso.exists():raise FileExistsError(iso)
subprocess.run(['xorriso','-as','mkisofs','-quiet','-R','-J','-V','KIKI_GNOME_LAB','-o',str(iso),str(media)],check=True)
c.save(Path(str(iso)+'.sha256.json'),dict(file=str(iso),sha256=c.sha256_file(iso),bytes=iso.stat().st_size,bootable=False,scope='disposable VM runtime overlay'))
print('Created lab data ISO',iso,flush=True)
