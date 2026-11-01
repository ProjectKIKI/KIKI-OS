"""One-time import of the already verified desktop baseline for update testing."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
import ki2release as c
import ki2origins

lib=c.Library('/release-store','/backend','/inputs/baseline','/sources','/native-packages','/legacy-backend')
root=Path('/desktop');key=root/'desktop-installer.ed25519.pub'
if c.sha(key)!='b6aaadb5491676d154efc62c0bf20a2f6b1026a741d92698d99c75f18390f4f4':raise ValueError('desktop baseline key changed')
if not lib.repo.verify_metadata_file(root/'repo/metadata.x86_64.json',key):raise ValueError('baseline signature invalid')
index=c.read(root/'repo/index.x86_64.json')
if c.sha(root/'repo/index.x86_64.json')!=c.read(root/'repo/metadata.x86_64.json')['index']['sha256']:raise ValueError('baseline index mismatch')
audits=ki2origins.load_audit(Path(__file__).with_name('source-origins.json'))
selection={}
for package in index['packages']:
    h=package['sha256'];path=root/'packages/x86_64'/package['file']
    if h not in lib.catalog['binaries']:
        source=audits.get(h,{}).get('source')
        lib.add_binary(path,h,'로컬 GNOME·관리자 VM 검증 후보',source,{'desktop_baseline':True})
    selection[package['name']]=h
name='update-baseline-desktop-20261028'
if not (lib.root/'snapshots'/name/'manifest.json').exists():lib.snapshot(name,selection,'업데이트 기준 · 기존 Hyper-V GNOME·관리자 검증 후보')
lib.commit()
config=lib.updates.root/'config.json'
if not config.exists():
    c.save(config,{'enabled':True,'baseline':name,'interval_seconds':21600,'vm_profiles':[{'vm_id':'5ee76510-b29a-47fb-8c67-c9a73596be2e','profile':'gnome50'}]})
print(json.dumps({'baseline':name,'packages':len(selection)}))
