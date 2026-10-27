#!/usr/bin/env python3
"""Stage only the fresh-install-validated ISO and archive set in a standard repo layout."""
import datetime
import json
from pathlib import Path
import shutil
import ki2sessioncandidate as c
import ki2repo

report_path=c.TARGET/'validation/gnome-fresh-install-runtime.json'
report=json.loads(report_path.read_text())
preserved=json.loads((c.TARGET/'validation/original-preservation-current.json').read_text())
if not report.get('passed') or not report.get('fresh_install_tested') or not preserved['passed']:raise ValueError('Fresh runtime/preservation gate failed')
source_repo=c.TARGET/'install-repo-r3'
if c.sha256_file(source_repo/'index.x86_64.json')!=report['installed_index_sha256']:raise ValueError('Installed index changed')
index=json.loads((source_repo/'index.x86_64.json').read_text())
dest=c.TARGET/'validated-candidate';dest.mkdir(exist_ok=False)
packages=dest/'packages/x86_64';packages.mkdir(parents=True)
for r in index['packages']:
    source=c.TARGET/'install-packages-r2/x86_64'/r['file']
    if c.sha256_file(source)!=r['sha256']:raise ValueError('Archive changed: '+r['name'])
    shutil.copy2(source,packages/source.name)
    if c.sha256_file(packages/source.name)!=r['sha256']:raise ValueError('Archive copy mismatch')
iso=dest/'iso';iso.mkdir()
source_iso=c.REPO/report['iso_file']
if c.sha256_file(source_iso)!=report['iso_sha256']:raise ValueError('Validated ISO changed')
shutil.copy2(source_iso,iso/source_iso.name)
if c.sha256_file(iso/source_iso.name)!=report['iso_sha256']:raise ValueError('ISO copy mismatch')
shutil.copy2(Path(str(source_iso)+'.sha256.json'),iso/(source_iso.name+'.sha256.json'))
repo=dest/'repo';repo.mkdir()
shutil.copy2(source_repo/'index.x86_64.json',repo/'index.x86_64.json')
metadata=ki2repo.build_metadata(name='kiki-gnome50-login-candidate',title='KIKI GNOME 50 fresh-install validated candidate',description='Kernel 6.1.187, preserved GTK installer, fresh offline installation and GDM password Wayland login verified; minimum desktop, not a production release',channel='candidate',arch='x86_64',base_url='',created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),repo_dir=repo,packages_dir=packages,iso_dir=iso,packages=index['packages'])
ki2repo.write_json(repo/'metadata.x86_64.json',metadata)
ki2repo.sign_metadata_file(repo/'metadata.x86_64.json',c.WORK/'candidate-keys/gnome50-candidate.ed25519')
public=dest/'gnome50-candidate.ed25519.pub';shutil.copy2(c.TARGET/'build-tools/gnome50-candidate.ed25519.pub',public)
if not ki2repo.verify_metadata_file(repo/'metadata.x86_64.json',public):raise ValueError('Final candidate signature failed')
gate=json.loads((c.TARGET/'gate.json').read_text())
gate.update(validated_repository='validated-candidate',index_sha256=c.sha256_file(repo/'index.x86_64.json'),metadata_sha256=c.sha256_file(repo/'metadata.x86_64.json'),fresh_report_sha256=c.sha256_file(report_path),published_iso=(iso/source_iso.name).relative_to(c.REPO).as_posix(),release_ready=False)
c.save(dest/'validation.json',gate);c.save(c.TARGET/'gate.json',gate)
shutil.copy2(report_path,dest/'fresh-install-runtime.json')
shutil.copy2(c.REPO/'docs/kiki-stage3-gnome50-candidate-20261017.ko.md',dest/'README.ko.md')
print('Published verified candidate layout: 181 archives, one fresh-validated ISO, Ed25519 signature PASS; release_ready=false',flush=True)
