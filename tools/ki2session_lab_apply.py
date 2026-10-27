#!/usr/bin/python3
"""Atomic runtime overlay for the disposable lab VM, never a package upgrade."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

media = Path(__file__).resolve().parent
if os.geteuid() != 0 or os.uname().nodename != 'kiki-lab':
    raise SystemExit('Only the disposable kiki-lab guest may apply this runtime overlay')
if Path('/sys/class/block/sda/size').read_text().strip() != '67108864':
    raise SystemExit('Unexpected lab disk size')
plan = json.loads((media / 'overlay.json').read_text())
requested=set(sys.argv[1:])
if requested-{r['name'] for r in plan['packages']}:raise SystemExit('Unknown selected lab package')
records = []
for record in plan['packages']:
    if requested and record['name'] not in requested:continue
    if record['name'] in ['base-files','linux']:
        print('LAB_PRESERVE_EXISTING',record['name'],'machine identity/accounts and current kernel retained',flush=True)
        continue
    archive = media / record['file']
    h = hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    if h.hexdigest() != record['sha256']:
        raise SystemExit('Package SHA mismatch: ' + record['file'])
    with tarfile.open(archive, 'r:gz') as tar:
        manifest = json.load(tar.extractfile('manifest.json'))
        expected = {p['path']: p for p in manifest['files']}
        for member in tar.getmembers():
            if not member.name.startswith('rootfs/'):continue
            relative=Path(member.name[len('rootfs/'):])
            if not relative.parts:continue
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('usr','bin','sbin','lib','lib64','etc','var','run','linuxrc'):
                raise SystemExit('Unexpected lab payload path before applying package: '+str(relative))
            if '/'+str(relative) in ['/etc/passwd','/etc/shadow','/etc/group','/etc/gshadow','/etc/hostname','/etc/machine-id','/etc/fstab','/var/lib/dbus/machine-id']:
                raise SystemExit('Identity payload rejected before applying package')
        count = 0
        for member in tar.getmembers():
            if not member.name.startswith('rootfs/'):
                continue
            relative = Path(member.name[len('rootfs/'):])
            if not relative.parts:
                continue
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('usr', 'bin', 'sbin', 'lib', 'lib64', 'etc', 'var', 'run', 'linuxrc'):
                raise SystemExit('Unexpected lab payload path')
            target = Path('/') / relative
            if str(target) in ['/etc/passwd','/etc/shadow','/etc/group','/etc/gshadow','/etc/hostname','/etc/machine-id','/etc/fstab','/var/lib/dbus/machine-id']:
                raise SystemExit('Lab account/identity configuration must be preserved')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name('.kiki-session-lab-' + str(os.getpid()) + '-' + target.name)
            if temporary.exists() or temporary.is_symlink():
                raise SystemExit('Unexpected existing temporary file')
            if member.issym():
                temporary.symlink_to(member.linkname)
            elif member.islnk():
                link = member.linkname.removeprefix('rootfs/')
                if Path(link).is_absolute() or '..' in Path(link).parts:
                    raise SystemExit('Unsafe hardlink target')
                os.link(Path('/') / link, temporary)
            elif member.isfile():
                with tar.extractfile(member) as src, temporary.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                if expected['/' + str(relative)]['sha256'] != digest:
                    raise SystemExit('Payload SHA mismatch')
                os.chown(temporary, member.uid, member.gid)
                temporary.chmod(member.mode)
            else:
                raise SystemExit('Unsupported lab payload entry')
            os.replace(temporary, target)
            count += 1
    records.append(dict(name=record['name'], sha256=record['sha256'], files=count))
    print('LAB_OVERLAY_OK', record['name'], count, flush=True)
subprocess.run(['/sbin/ldconfig'], check=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
out = Path('/var/lib/kiki-session-lab/overlay-result.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(dict(mode='disposable VM runtime overlay; package manager DB unchanged', packages=records), indent=2) + '\n')
print('LAB_OVERLAY_COMPLETE: reboot to validate the new PID 1 and PAM sessions', flush=True)
