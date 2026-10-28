import json
from pathlib import Path
import subprocess
import sys

repo=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
sys.path.insert(0,str(repo/'tools'))
import ki2media
import ki2build

report=json.loads((out/'media-validation.json').read_text())
iso=Path(report['file'])
assert ki2build.file_sha256(iso)==report['sha256']
root=Path('/tmp/kiki-gnome-native-apps-20261028')/('readback-'+iso.stem)
(root/'kiki').mkdir(parents=True,exist_ok=True)
subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),'-extract','/kiki/repo',str(root/'kiki/repo'),
                '-extract','/kiki/packages',str(root/'kiki/packages'),'-extract','/kiki/installer-catalog.json',str(root/'kiki/installer-catalog.json')],check=True)
public=Path('/tmp/kiki-gnome-native-apps-20261028/media/desktop-installer.ed25519.pub')
count=ki2media.verify_media(root,public)
assert count==report['packages']
catalog=json.loads((root/'kiki/installer-catalog.json').read_text())
desktop=next(p for p in catalog['profiles'] if p['id']=='desktop-gnome')
assert desktop['available'] and desktop['packages']==report['desktop_runtime_packages'] and desktop['ai_default']=='off'
result=dict(status='passed',iso_sha256=report['sha256'],verified_packages=count,signature='Ed25519',
            desktop_profile=desktop,index_sha256=ki2build.file_sha256(root/'kiki/repo/index.x86_64.json'))
(out/'iso-readback-validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2),flush=True)
