import hashlib,json,re,shutil,tarfile,urllib.request,subprocess,sys
from pathlib import Path
out=Path(__file__).resolve().parent;work=Path('/tmp/kiki-gnome-native-apps-20261028');records=json.loads((out/'sources.json').read_text())
sdkmeta=next((work/'freedesktop-sdk-metadata/source').iterdir())
(out/'metadata/xdg-desktop-portal.bst').write_text((sdkmeta/'elements/components/xdg-desktop-portal-base.bst').read_text())
subprocess.run([sys.executable,str(out/'prepare-sources.py'),'xdg-desktop-portal','xdg-desktop-portal-gnome'],check=True)
records=json.loads((out/'sources.json').read_text())
items=[('fuse3','libfuse/libfuse','components/fuse3.bst'),('pipewire','PipeWire/pipewire','components/pipewire-base.bst'),('gstreamer','GStreamer/gstreamer','include/gstreamer-source.yml')]
items += [('xdg-user-dirs','xdg/xdg-user-dirs','components/xdg-user-dirs.bst')]
items += [('portal-libglnx','GNOME/libglnx','ff64d52116ae74f0d25e24f089db28921ea171ff'),('portal-gvdb','GNOME/gvdb','c6f2359cc1d00f16e0a0e2527fa0bc1882b8b5ab')]
for name,project,ref in items:
 if '/' in ref:
  text=(sdkmeta/'elements'/ref).read_text();commit=re.search(r'  ref: .*?-g([a-f0-9]{40})',text)[1]
 else:commit=ref
 url=('https://gitlab.freedesktop.org/'+project+'/-/archive/'+commit+'/xdg-user-dirs-'+commit+'.tar.gz') if project.startswith('xdg/') else 'https://codeload.github.com/'+project+'/tar.gz/'+commit
 path=work/'sources'/(name+'-'+commit+'.tar.gz')
 old=next((r for r in records if r['name']==name),None)
 if not path.exists():path.write_bytes(urllib.request.urlopen(url,timeout=90).read())
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 if old:assert digest==old['sha256']
 root=work/name/'source'
 if not root.exists():
  root.mkdir(parents=True)
  with tarfile.open(path) as t:
   for m in t:
    if m.name.startswith('/') or '..' in Path(m.name).parts:raise ValueError('unsafe source archive')
   t.extractall(root)
 record=dict(name=name,url=url,file=str(path),sha256=digest,commit=commit,metadata_commit='da39a00d43df80bcf17898c2ebf7035df59a6a39')
 records=[r for r in records if r['name']!=name]+[record];(out/'sources.json').write_text(json.dumps(records,indent=2)+'\n');print('Verified',name,flush=True)
 if name.startswith('portal-'):
  dest=next((work/'xdg-desktop-portal/source').iterdir())/'subprojects'/name.removeprefix('portal-')
  if not (dest/'meson.build').exists():shutil.copytree(next(root.iterdir()),dest,dirs_exist_ok=True)
