"""Integrate the signed native GNOME snapshot with this task's rebuilt packages."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

repo=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
sys.path.insert(0,str(repo/'tools'))
import ki2bootiso
import ki2build
import ki2installcatalog
import ki2media
import ki2repo
from ki2stage3candidate import read_manifest

spec=importlib.util.spec_from_file_location('apps',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
work=a.work/'media';packages=work/'packages/x86_64';repository=work/'repo'
packages.mkdir(parents=True,exist_ok=True)
baseline=repo/'dist/ki2/desktop-installer-20261027'
profile=ki2build.load_profile(repo/'distro/profiles/desktop-gnome.toml')
# Verify the original public key pin, signed index and every baseline payload.
assert ki2build.file_sha256(baseline/'desktop-installer.ed25519.pub')=='a3503817f3c2f4dd8517b065f8901c3baad4c6c68e73e123ea24762820b6f5b6'
index_path=baseline/'repo/index.x86_64.json'
assert ki2build.file_sha256(index_path)=='af345df7eff51383c1920308a8170499e8bb8cb1537a88fb4cb8df8af7996431'
metadata=json.loads((baseline/'repo/metadata.x86_64.json').read_text())
assert ki2repo.verify_metadata_ed25519(metadata,baseline/'desktop-installer.ed25519.pub')
assert metadata['index']['sha256']==ki2build.file_sha256(index_path)
records={}
for r in json.loads(index_path.read_text())['packages']:
    p=baseline/'packages/x86_64'/r['file']
    assert p.stat().st_size==r['size'] and ki2build.file_sha256(p)==r['sha256'],r['name']
    records[r['name']]=p
print('Verified original signed GNOME snapshot',len(records),'packages',flush=True)
front=json.loads((out/'frontend-packages.json').read_text())
native=json.loads((a.work/'output-records.json').read_text())
for name,r in {**native,**front}.items():
    if name in {'busybox','kiki-gnome-desktop','coreutils','gawk','findutils','sed','tar','libtool'}:continue
    p=Path(r['file']);assert ki2build.file_sha256(p)==r['sha256'];records[name]=p
records.pop('kiki-desktop-tools',None)
# Native CUPS owns its print clients. Keep the BusyBox applets accessible via
# busybox itself while retiring only the two competing executable aliases.
parent=records['busybox'];raw=read_manifest(parent);dest=a.work/'busybox-print-aliases'
if not dest.exists():ki2build.extract_package_rootfs(parent,dest)
for relative in ['usr/bin/lpr','usr/bin/lpq']:(dest/relative).unlink(missing_ok=True)
records['busybox']=a.package('busybox',raw['version'],dest,raw['dependencies']['runtime'],
    dict(parent_sha256=ki2build.file_sha256(parent),retired_aliases=['usr/bin/lpr','usr/bin/lpq']),
    license=raw['license'],release=str(int(raw['release'])+1))
# Extend the original native-Mesa desktop metapackage rather than replacing its session.
old=read_manifest(records['kiki-gnome-desktop'])
dest=a.work/'desktop-meta';dest.mkdir(exist_ok=True)
ki2build.extract_package_rootfs(records['kiki-gnome-desktop'],dest)
deps=list(dict.fromkeys([n for n in old['dependencies']['runtime'] if n!='kiki-desktop-tools']+['kiki-desktop-defaults','gnome-control-center','nautilus','gnome-console']))
meta=a.package('kiki-gnome-desktop',old['version'],dest,deps,
               dict(parent_sha256=ki2build.file_sha256(records['kiki-gnome-desktop']),desktop_additions='GNOME Control Center, Nautilus, Console, NetworkManager and Hangul'),
               license='GPL-3.0-or-later',release=str(int(old['release'])+1))
records['kiki-gnome-desktop']=meta
retired=work/'retired-preflight-packages';retired.mkdir(exist_ok=True)
expected={p.name for p in records.values()}
for p in packages.glob('*.ki2'):
    if p.name not in expected:
        assert p.resolve().is_relative_to(packages.resolve())
        p.rename(retired/p.name)
for name,p in records.items():
    target=packages/p.name
    if target.exists(): assert ki2build.file_sha256(target)==ki2build.file_sha256(p)
    else: shutil.copy2(p,target)
assert len(list(packages.glob('*.ki2')))==len(records)
key=work/'desktop-installer.ed25519'
def run(*args,**kwargs):
    print('$',*map(str,args),flush=True)
    subprocess.run(list(map(str,args)),cwd=repo,check=True,**kwargs)
if not key.exists():
    run(sys.executable,'tools/ki2repo.py','keygen-ed25519','--private-key',key,'--public-key',Path(str(key)+'.pub'))
public=Path(str(key)+'.pub')
run(sys.executable,'tools/ki2repo.py','--packages-dir',packages,'--repo-dir',repository,'--iso-dir',work/'empty-iso',
    'generate','--include-all-staged','--channel','gnome-native-apps-20261028','--sign-key',key,'--sign-algorithm','ed25519')
run(sys.executable,'tools/ki2repo.py','--repo-dir',repository,'verify','--key',public)
index=json.loads((repository/'index.x86_64.json').read_text())
catalog=ki2bootiso.verify_installer_default_packages(repository,'x86_64','desktop-gnome')
(out/'installer-catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
selected=ki2installcatalog.expand(ki2installcatalog.load(),['desktop-gnome'])['packages']
closure=ki2media.runtime_closure(index,selected)
# Refuse competing owners before assembling a target filesystem.
owners={};conflicts=[]
for name in closure:
    for f in read_manifest(records[name]).get('files',[]):
        if f['type']=='dir':continue
        path=f['path']
        if path in owners:conflicts.append([path,owners[path],name])
        else:owners[path]=name
if conflicts:raise RuntimeError('Target payload ownership conflicts: '+repr(conflicts[:30]))
# Keep a pinned profile for reproducible rootfs assembly of this exact signed set.
snapshot=work/'snapshot';(snapshot/'repo').mkdir(parents=True,exist_ok=True)
shutil.copytree(repository,snapshot/'repo',dirs_exist_ok=True)
if not (snapshot/'packages').exists():(snapshot/'packages').symlink_to(work/'packages',target_is_directory=True)
shutil.copy2(public,snapshot/'desktop-installer.ed25519.pub')
# ki2build accepts repository paths under the workspace; save the small metadata
# there and keep package bytes in WSL through a separate direct assembly context.
recipes={}
for name in closure:
    raw=read_manifest(records[name]);raw.update(architectures=['x86_64'],source=dict(type='local',path=str(records[name])),build=dict(system='prebuilt'))
    raw['dependencies']={'build':[],'runtime':raw.get('dependencies',{}).get('runtime',[])}
    recipes[name]=ki2build.normalize_recipe(raw,records[name])
rootfs=work/'rootfs'
context=ki2build.BuildContext(repo_root=repo,recipe_dir=repo/'distro/recipes',
    arch='x86_64',source_cache=work/'sources',build_dir=work/'build',packages_dir=work/'packages',repo_dir=repository,
    rootfs_dir=rootfs,jobs=2,toolchain_id='gnome-native-apps-20261028',dry_run=False,clean_rootfs=False,allow_unpinned=False,verbose=False)
if not rootfs.exists():ki2build.assemble_rootfs(context,recipes,closure,profile)
else:
    state=json.loads((rootfs/'var/lib/ki2/installed.json').read_text())['packages']
    for name in closure:
        if state.get(name,{}).get('sha256') != ki2build.file_sha256(records[name]):
            ki2build.extract_package_rootfs(records[name],rootfs)
    ki2build.write_rootfs_installed_state(rootfs,[(records[n],read_manifest(records[n])) for n in closure])
run('/usr/sbin/chroot',rootfs,'/sbin/ldconfig')
for binary,args in [('/usr/bin/ls',['--version']),('/lib64/ld-linux-x86-64.so.2',['--list','/usr/bin/vte-2.91-gtk4']),
                    ('/lib64/ld-linux-x86-64.so.2',['--list','/usr/bin/gnome-control-center']),
                    ('/lib64/ld-linux-x86-64.so.2',['--list','/usr/bin/nautilus']),
                    ('/lib64/ld-linux-x86-64.so.2',['--list','/usr/bin/kgx']),
                    ('/lib64/ld-linux-x86-64.so.2',['--list','/usr/sbin/NetworkManager']),
                    ('/usr/libexec/gsd-keyboard',['--help']),('/usr/libexec/ibus-engine-hangul',['--help'])]:
    run('/usr/sbin/chroot',rootfs,binary,*args)
iso=out/'kiki-gnome-native-apps-20261028-r3.iso'
assert not iso.exists()
run(sys.executable,'tools/ki2bootiso.py','--mode','installer','--profile','desktop-gnome',
    '--rootfs-dir',rootfs,'--kernel',rootfs/'boot/vmlinuz-kiki','--repo-dir',repository,'--packages-dir',packages,
    '--media-public-key',public,'--output',iso,'--release-name','gnome-native-apps-20261028','--no-install-image','--no-hyperv-vhdx')
result=dict(file=str(iso),sha256=ki2build.file_sha256(iso),bytes=iso.stat().st_size,packages=len(records),
            desktop_runtime_packages=len(closure),signature='Ed25519',ownership_conflicts=0,rootfs=str(rootfs),
            repository=str(repository),public_key=str(public),fresh_vm_install_tested=False)
Path(str(iso)+'.sha256.json').write_text(json.dumps(result,indent=2)+'\n')
(out/'media-validation.json').write_text(json.dumps(result,indent=2)+'\n')
shutil.copy2(public,out/'desktop-installer.ed25519.pub')
print(json.dumps(result,indent=2),flush=True)
