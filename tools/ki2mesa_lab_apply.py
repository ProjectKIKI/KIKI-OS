#!/usr/bin/python3
"""Replace only bootstrap-owned files inside the explicitly identified disposable VM."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

media=Path(__file__).resolve().parent
plan=json.loads((media/'overlay.json').read_text())
if os.geteuid()!=0 or os.uname().nodename!='kiki-lab':raise SystemExit('Disposable lab root only')
if Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower()!=plan['guest_uuid']:raise SystemExit('Wrong lab VM identity')
if Path('/sys/class/block/sda/size').read_text().strip()!='67108864':raise SystemExit('Wrong lab disk')
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def target_of(name):
    if not name.startswith('rootfs/'):raise ValueError('Unexpected archive path')
    rel=Path(name[len('rootfs/'):])
    if not rel.parts:return None
    if rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='usr':raise ValueError('Only /usr graphics payload allowed')
    p=Path('/')/rel
    # Existing usr-merge roots are allowed, nested package directories may not redirect writes.
    for parent in list(p.parents)[:-1]:
        if parent==Path('/usr'):break
        if parent.is_symlink():raise ValueError('Unexpected symlink parent: '+str(parent))
    return p
old=json.loads((media/'old-bootstrap-manifest.json').read_text())
for f in old['files']:
    if f['type']=='dir':continue
    p=Path(f['path'])
    if not (str(p).startswith('/usr/') or (p.parent==Path('/lib64') and p.name.endswith(('.so','.so.1','.so.0','.so.2','.so.5','.so.21.1','.so.1.0.0')))):raise ValueError('Unexpected bootstrap path')
    if f['type']=='symlink':
        if not p.is_symlink() or os.readlink(p)!=f['target']:raise ValueError('Changed bootstrap symlink: '+str(p))
    elif not p.is_file() or p.is_symlink() or digest(p)!=f['sha256']:raise ValueError('Changed bootstrap file: '+str(p))
for r in plan['packages']:
    archive=media/r['file']
    if digest(archive)!=r['sha256']:raise ValueError('Archive SHA mismatch')
    with tarfile.open(archive,'r:gz') as t:
        m=json.load(t.extractfile('manifest.json'));expected={f['path']:f for f in m['files']};seen=set()
        for member in t.getmembers():
            if member.name in ['manifest.json','rootfs']:continue
            p=target_of(member.name)
            if p is None:continue
            if str(p) in seen:raise ValueError('Duplicate member')
            seen.add(str(p))
            if member.islnk():target_of(member.linkname)
            if member.isfile() or member.islnk():
                if hashlib.sha256(t.extractfile(member).read()).hexdigest()!=expected[str(p)]['sha256']:raise ValueError('Payload SHA mismatch')
            elif member.issym():
                if member.linkname!=expected[str(p)]['target']:raise ValueError('Symlink mismatch')
            elif not member.isdir():raise ValueError('Unsupported archive type')
        if seen!=set(expected):raise ValueError('Manifest/payload path mismatch')
if digest(media/'mesa-probe')!=plan['probe_sha256']:raise ValueError('Probe SHA mismatch')
subprocess.run(['systemctl','stop','gdm.service'],check=True)
if subprocess.run(['pgrep','-x','gnome-shell'],capture_output=True).returncode==0:raise SystemExit('GNOME Shell must exit before removing bootstrap')
identity={str(p):digest(p) for p in map(Path,['/etc/passwd','/etc/shadow','/etc/group','/etc/gshadow','/etc/machine-id'])}
removed=[]
for f in old['files']:
    if f['type']=='dir':continue
    Path(f['path']).unlink();removed.append(f['path'])
for r in plan['packages']:
    with tarfile.open(media/r['file'],'r:gz') as t:
        for m in t.getmembers():
            if not m.name.startswith('rootfs/'):continue
            p=target_of(m.name)
            if p is None:continue
            if m.isdir():p.mkdir(parents=True,exist_ok=True);continue
            p.parent.mkdir(parents=True,exist_ok=True)
            tmp=p.with_name('.mesa-lab-'+str(os.getpid())+'-'+p.name)
            if tmp.exists() or tmp.is_symlink():raise ValueError('Unexpected temporary file')
            if m.issym():tmp.symlink_to(m.linkname)
            else:
                with t.extractfile(m) as src,tmp.open('xb') as dst:shutil.copyfileobj(src,dst)
                os.chown(tmp,m.uid,m.gid);tmp.chmod(m.mode)
            tmp.replace(p)
    print('MESA_LAB_PACKAGE_OK',r['name'],flush=True)
subprocess.run(['/sbin/ldconfig'],check=True)
if any(digest(Path(p))!=h for p,h in identity.items()):raise ValueError('Identity configuration changed')
out=Path('/var/lib/kiki-mesa-lab');out.mkdir(exist_ok=True)
(out/'overlay-result.json').write_text(json.dumps(dict(passed=True,scope=plan['scope'],packages=plan['packages'],removed_bootstrap_paths=removed,identity_files_unchanged=True),indent=2)+'\n')
shutil.copy2(media/'mesa-probe',out/'mesa-probe')
evidence=out/'media';evidence.mkdir(exist_ok=True)
for name in ['mesa-report.py','session-report.py','overlay.json','old-bootstrap-manifest.json','native-files.json']:
    shutil.copy2(media/name,evidence/name)
subprocess.run(['systemctl','daemon-reload'],check=True)
print('MESA_NATIVE_OVERLAY_OK: reboot required before runtime validation',flush=True)
