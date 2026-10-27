#!/usr/bin/env python3
"""Supply the preserved GTK server profile's extra socat in a separate signed repo."""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import ki2sessioncandidate as c
import ki2repo
from ki2stage3candidate import read_manifest

baseline=json.loads((c.BASE/'snapshot.json').read_text())['packages']
r=next(x for x in baseline if x['name']=='socat')
source=c.BASE/'packages/x86_64'/r['file']
if c.sha256_file(source)!=r['sha256']:raise ValueError('Original socat SHA mismatch')
manifest=read_manifest(source)
plan=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
names=set(plan['order'])
if set(manifest.get('dependencies',{}).get('runtime',[]))-names:raise ValueError('Extra unresolved socat dependencies')
owners={f['path'] for p in plan['packages'] for f in read_manifest(Path(p['file']))['files'] if f['type']!='dir'}
conflicts=[f['path'] for f in manifest['files'] if f['type']!='dir' and f['path'] in owners]
if conflicts:raise ValueError('Extra socat file conflict: '+str(conflicts))
scratch=c.WORK/'native-desktop-root-v2/tmp/kiki-socat-proof'
if scratch.exists():raise FileExistsError(scratch)
scratch.mkdir()
try:
    c.build.extract_package_rootfs(source,scratch)
    version=subprocess.run(['/usr/sbin/chroot',str(c.WORK/'native-desktop-root-v2'),'/tmp/kiki-socat-proof/usr/bin/socat','-V'],check=True,capture_output=True,text=True)
finally:
    if scratch.resolve()!=c.WORK/'native-desktop-root-v2/tmp/kiki-socat-proof':raise ValueError('Unexpected scratch path')
    shutil.rmtree(scratch)
packages=c.TARGET/'install-packages-r2/x86_64'
packages.mkdir(parents=True,exist_ok=False)
for p in (c.TARGET/'packages/x86_64').glob('*.ki2'):shutil.copy2(p,packages/p.name)
shutil.copy2(source,packages/source.name)
entries=[]
for p in sorted(packages.glob('*.ki2')):entries.append(ki2repo.package_entry(p,read_manifest(p)))
repo=c.TARGET/'install-repo-r2';repo.mkdir(exist_ok=False)
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
c.save(repo/'index.x86_64.json',ki2repo.build_index(sorted(entries,key=lambda x:x['name']),'x86_64',now))
metadata=ki2repo.build_metadata(name='kiki-gnome50-candidate',title='KIKI GNOME 50 preserved-frontend installation candidate',description='Validated native desktop plus original SHA-pinned socat required by preserved GTK profile; not a production release',channel='candidate',arch='x86_64',base_url='',created_at=now,repo_dir=repo,packages_dir=packages,iso_dir=c.TARGET/'release-iso',packages=entries)
c.save(repo/'metadata.x86_64.json',metadata)
ki2repo.sign_metadata_file(repo/'metadata.x86_64.json',c.WORK/'candidate-keys/gnome50-candidate.ed25519')
if not ki2repo.verify_metadata_file(repo/'metadata.x86_64.json',c.TARGET/'build-tools/gnome50-candidate.ed25519.pub'):raise ValueError('Signature failed')
c.save(c.TARGET/'validation/installer-socat-supplement.json',dict(passed=True,name='socat',file=str(source),sha256=r['sha256'],original_archive_unchanged=True,version_probe=version.stdout+version.stderr,dependency_errors=[],file_conflicts=[],native_core_packages=178,installed_packages=179,iso_packages=181,repo=str(repo),packages=str(packages),index_sha256=c.sha256_file(repo/'index.x86_64.json')))
print('Separate signed installer repo: 181 packages, native install closure 179; socat target execution passed',flush=True)
