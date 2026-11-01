"""Build the native administrator and a separate signed desktop candidate.

Requires an existing KIKI GTK/Libadwaita SDK and the verified native GNOME
baseline. This does not fetch a new desktop or overwrite an earlier ISO.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parent))
import ki2build
import ki2installcatalog
import ki2media
import ki2repo
from ki2stage3candidate import read_manifest


def export_candidate(work, output, public, baseline):
    repository=work/'repo'; packages=work/'packages/x86_64'
    metadata=json.loads((repository/'metadata.x86_64.json').read_text())
    assert ki2repo.verify_metadata_ed25519(metadata,public)
    assert metadata['index']['sha256']==ki2build.file_sha256(repository/'index.x86_64.json')
    index=json.loads((repository/'index.x86_64.json').read_text())
    assert not (output/'admin-build.json').exists(), 'Completed candidates are immutable'
    (output/'packages/x86_64').mkdir(parents=True,exist_ok=True)
    (output/'repo').mkdir(exist_ok=True)
    public_metadata=[repository/name for name in ['index.x86_64.json','metadata.x86_64.json','channels.json']]
    for source in [*public_metadata, public]:
        if not source.is_file(): continue
        target=output/('repo/'+source.name if source.parent==repository else source.name)
        if target.exists():
            assert target.read_bytes()==source.read_bytes(), 'Unexpected existing candidate metadata'
        else: shutil.copy2(source,target)
    records={}
    for record in index['packages']:
        name=record['file']; assert Path(name).name==name
        source=packages/name; expected=record['sha256']
        assert ki2build.file_sha256(source)==expected
        records[record['name']]=source
        target=output/'packages/x86_64'/name
        if target.exists() and ki2build.file_sha256(target)==expected: continue
        # Incomplete exports can be resumed. Never write through an existing
        # hardlink: replacing its directory entry preserves the baseline inode.
        target.unlink(missing_ok=True)
        original=baseline/'packages/x86_64'/name
        if original.exists() and ki2build.file_sha256(original)==expected:
            try:
                os.link(original,target)
                continue
            except OSError:
                pass
        temporary=target.with_suffix('.ki2.part')
        if shutil.disk_usage(output).free < source.stat().st_size + 64*1024*1024:
            raise RuntimeError('Not enough free space to export '+name+'; keep 64 MiB free and resume with --resume-export')
        with source.open('rb') as src, temporary.open('wb') as dst:
            shutil.copyfileobj(src,dst,1024*1024)
        assert ki2build.file_sha256(temporary)==expected
        temporary.replace(target)
    closure=ki2media.runtime_closure(index,ki2installcatalog.expand(ki2installcatalog.load(),['desktop-gnome'])['packages'])
    assert 'kiki-admin' in closure
    owners={}
    for name in closure:
        for item in read_manifest(records[name]).get('files',[]):
            if item['type']=='dir': continue
            assert item['path'] not in owners,(item['path'],owners.get(item['path']),name)
            owners[item['path']]=name
    result=dict(schema='kiki-admin-build-v1',candidate=str(output),packages=len(records),desktop_packages=len(closure),
                public_key_sha256=ki2build.file_sha256(public),index_sha256=ki2build.file_sha256(output/'repo/index.x86_64.json'),
                changed={n:dict(file=str(records[n]),sha256=ki2build.file_sha256(records[n])) for n in ['kiki-admin','ki2ctl']},
                ownership_conflicts=0,signature='Ed25519',iso_rebuilt=False,fresh_vm_install_tested=False)
    (output/'admin-build.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sign-key',type=Path,required=True)
    p.add_argument('--resume-export',action='store_true',help='resume an incomplete export from the existing signed working repository')
    args=p.parse_args()
    repo=Path(__file__).resolve().parents[1]; sdk=args.sdk.resolve(); work=args.work.resolve()
    baseline=args.baseline.resolve(); output=args.output.resolve()
    assert not args.sign_key.resolve().is_relative_to(work/'repo'), 'Signing keys must stay outside repository metadata'
    assert not args.sign_key.resolve().is_relative_to(output), 'Signing keys must stay outside public candidates'
    assert not output.exists() or args.resume_export, 'Choose a new candidate output; existing snapshots are immutable'
    key=Path(str(args.sign_key)+'.pub')
    public=baseline/'desktop-installer.ed25519.pub'
    assert ki2build.file_sha256(public)=='b6aaadb5491676d154efc62c0bf20a2f6b1026a741d92698d99c75f18390f4f4'
    assert ki2build.file_sha256(baseline/'repo/index.x86_64.json')=='eb14c3907902b6a3f85ce044849b58237b7f0e0ae80acaf256be976e624d5aa6'
    metadata=json.loads((baseline/'repo/metadata.x86_64.json').read_text())
    assert ki2repo.verify_metadata_ed25519(metadata,public)
    assert metadata['index']['sha256']==ki2build.file_sha256(baseline/'repo/index.x86_64.json')
    assert key.read_bytes()==public.read_bytes(), 'Use the baseline candidate signing identity'
    if args.resume_export:
        export_candidate(work,output,public,baseline)
        return
    packages=work/'packages/x86_64'; packages.mkdir(parents=True,exist_ok=True)
    records={}
    for record in json.loads((baseline/'repo/index.x86_64.json').read_text())['packages']:
        source=baseline/'packages/x86_64'/record['file']
        assert ki2build.file_sha256(source)==record['sha256'],record['name']
        records[record['name']]=source
    recipes=ki2build.load_recipes(repo/'distro/recipes')
    env=dict(os.environ,PKG_CONFIG_SYSROOT_DIR=str(sdk),PKG_CONFIG_LIBDIR=':'.join(str(sdk/p) for p in ['usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig']))
    libdirs=[sdk/p for p in ['usr/lib','usr/lib64','lib64']]
    cflags='--sysroot='+str(sdk)+' -O2 -pipe -Wall -Wextra -Werror -fstack-protector-strong'
    ldflags='--sysroot='+str(sdk)+' '+' '.join('-L'+str(d)+' -Wl,-rpath-link,'+str(d) for d in libdirs)+' -Wl,-z,relro,-z,now'
    subprocess.run(['make','-B','-C',str(repo/'cmd/kiki-admin'),'CFLAGS='+cflags,'LDFLAGS='+ldflags],env=env,check=True)
    staged=work/'staged/kiki-admin'; staged.mkdir(parents=True,exist_ok=True)
    subprocess.run(['make','-C',str(repo/'cmd/kiki-admin'),'install','DESTDIR='+str(staged),'CFLAGS='+cflags,'LDFLAGS='+ldflags],env=env,check=True)
    replacements={"kiki-admin":staged,"ki2ctl":repo/'distro/sources/ki2ctl'}
    for name,root in replacements.items():
        recipe=recipes[name]
        package=packages/ki2build.package_filename(recipe,'x86_64')
        if name=='ki2ctl':
            root=work/'staged/ki2ctl'; shutil.copytree(replacements[name],root,dirs_exist_ok=True)
            (root/'usr/bin/ki2ctl').chmod(0o755)
        # Python compilation caches are development artifacts, never payloads.
        for path in root.rglob('*.pyc'):
            path.unlink()
        assert not any(root.rglob('*.pyc'))
        ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,root,package,ki2build.stable_hash(ki2build.package_file_manifest(root)),{})
        records[name]=package
    # Reuse unchanged baseline bytes and replace only explicitly rebuilt names.
    for name,source in records.items():
        target=packages/source.name
        if not target.exists(): shutil.copy2(source,target)
    assert {p.name for p in packages.glob('*.ki2')}=={p.name for p in records.values()}
    repository=work/'repo'
    subprocess.run([sys.executable,str(repo/'tools/ki2repo.py'),'--packages-dir',str(packages),'--repo-dir',str(repository),'--iso-dir',str(work/'iso'),
                    'generate','--include-all-staged','--channel','kiki-admin-20261028','--sign-key',str(args.sign_key),'--sign-algorithm','ed25519'],check=True)
    subprocess.run([sys.executable,str(repo/'tools/ki2repo.py'),'--repo-dir',str(repository),'verify','--key',str(public)],check=True)
    index=json.loads((repository/'index.x86_64.json').read_text())
    selected=ki2installcatalog.expand(ki2installcatalog.load(),['desktop-gnome'])['packages']
    closure=ki2media.runtime_closure(index,selected)
    assert 'kiki-admin' in closure
    owners={}
    for name in closure:
        for item in read_manifest(records[name]).get('files',[]):
            if item['type']=='dir': continue
            assert item['path'] not in owners,(item['path'],owners.get(item['path']),name)
            owners[item['path']]=name
    export_candidate(work,output,public,baseline)


if __name__=='__main__': main()
