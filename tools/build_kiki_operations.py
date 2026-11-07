"""Build one native GTK app and an exact installed-GA test overlay; no ISO or upgrades."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import ki2build
import ki2repo
import ki2media
from ki2integrity import audit_payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--sign-key',type=Path,required=True)
    p.add_argument('--lock',type=Path,help='Explicit installed-GA/dependency lock; original default remains reproducible')
    p.add_argument('--extra-package',type=Path,action='append',default=[],help='Verified, additive candidate dependency; never replace a baseline package')
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    lock=json.loads((a.lock or root/'distro/manifests/kiki-operations-20261106-baseline.json').read_text())
    base=a.baseline.resolve();sdk=a.sdk.resolve();work=a.work.resolve();target=a.candidate.resolve()
    assert not work.exists() and not target.exists(),'Build and candidate paths must be new'
    assert not a.sign_key.resolve().is_relative_to(target)
    indexpath=base/'repo/index.x86_64.json';pub=base/'paper-pixel.ed25519.pub'
    assert ki2repo.file_sha256(indexpath)==lock['index_sha256']
    assert ki2repo.file_sha256(pub)==lock['public_key_sha256']
    metadata=json.loads((base/'repo/metadata.x86_64.json').read_text())
    assert metadata['index']['sha256']==lock['index_sha256'] and ki2repo.verify_metadata_ed25519(metadata,pub)
    index=json.loads(indexpath.read_text());records={r['name']:r for r in index['packages']}
    assert all(records[n]['sha256']==sha for n,sha in lock['installed'].items())
    assert ki2repo.run_openssl(['pkey','-in',str(a.sign_key),'-pubout'])==pub.read_bytes()
    work.mkdir(parents=True);source=work/'source'
    shutil.copytree(root/'cmd/kiki-operations',source,ignore=shutil.ignore_patterns('kiki-operations','ui-test','*.o'))
    env=dict(os.environ,PKG_CONFIG_SYSROOT_DIR=str(sdk),PKG_CONFIG_LIBDIR=':'.join(str(sdk/p) for p in ['usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig']))
    cflags='--sysroot='+str(sdk)+' -O2 -pipe -Wall -Wextra -Werror -fstack-protector-strong'
    ldflags='--sysroot='+str(sdk)+' '+' '.join('-L'+str(sdk/p)+' -Wl,-rpath-link,'+str(sdk/p) for p in ['usr/lib','usr/lib64','lib64'])+' -Wl,-z,relro,-z,now'
    subprocess.run(['make','-C',str(source),'all','ui-test','CFLAGS='+cflags,'LDFLAGS='+ldflags],env=env,check=True)
    staged=work/'staged';shutil.copytree(root/'distro/sources/kiki-operations',staged)
    shutil.copy2(source/'kiki-operations',staged/'usr/bin/kiki-operations')
    for name in ['usr/bin/kiki-operations','usr/bin/kiki-operationsctl','usr/libexec/kiki-operations-backend.py','usr/libexec/kiki-operations-console']:
        if (staged/name).exists():(staged/name).chmod(0o755)
    for p in staged.rglob('__pycache__'):shutil.rmtree(p)
    subprocess.run(['glib-compile-schemas','--strict','--dry-run',str(staged/'usr/share/glib-2.0/schemas')],check=True)
    recipe=ki2build.load_recipes(root/'distro/recipes')['kiki-operations']
    assert set(recipe.dependencies['runtime'])==set(lock['dependency_build_keys'])
    target.mkdir(parents=True);packages=target/'packages/x86_64';packages.mkdir(parents=True)
    package=packages/ki2build.package_filename(recipe,'x86_64')
    key=ki2build.stable_hash(dict(recipe=recipe.digest,files=ki2build.package_file_manifest(staged),baseline=lock['index_sha256'],dependencies=lock['dependency_build_keys']))
    ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,staged,package,key,lock['dependency_build_keys'])
    audit=audit_payload(package);assert not audit['errors'],audit
    new=ki2repo.package_entry(package,ki2repo.read_package_manifest(package));assert new['name'] not in records
    # Never overwrite an existing owned file, including in non-installed base entries.
    newpaths={f['path'] for f in ki2repo.read_package_manifest(package)['files'] if f['type']!='dir'}
    assert all(path.startswith(('/usr/bin/kiki-operations','/usr/libexec/kiki-operations','/usr/share/kiki-operations/','/usr/share/applications/org.kiki.Operations','/usr/share/icons/hicolor/scalable/apps/org.kiki.Operations','/usr/share/glib-2.0/schemas/org.kiki.Operations')) for path in newpaths)
    index['packages'].append(new);index['packages'].sort(key=lambda r:r['name']);index['created_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();ki2media.runtime_closure(index,['kiki-operations'])
    (target/'repo').mkdir();ki2repo.write_json(target/'repo/index.x86_64.json',index);shutil.copy2(pub,target/pub.name)
    # Supply only the three new/previous overlay archives. GA packages must already be installed.
    for archive in (base/'packages/x86_64').glob('*.ki2'):
        entry=next(r for r in index['packages'] if r['file']==archive.name)
        assert ki2repo.file_sha256(archive)==entry['sha256'];shutil.copy2(archive,packages/archive.name)
    extras=[]
    for archive in a.extra_package:
        extra_audit=audit_payload(archive);assert not extra_audit['errors'],extra_audit
        entry=ki2repo.package_entry(archive,ki2repo.read_package_manifest(archive))
        extra_paths={f['path'] for f in ki2repo.read_package_manifest(archive)['files'] if f['type']!='dir'}
        allowed={
            'kiki-incident-browser':('/opt/kiki/firefox-esr/','/usr/libexec/kiki-incident-browser/','/usr/bin/kiki-incident-browser','/usr/share/applications/org.kiki.IncidentBrowser.desktop','/usr/share/kiki-incident-browser/'),
            'kiki-browser-x11-libs':('/usr/lib/libX','/usr/share/X11/locale/','/usr/share/licenses/kiki-browser-x11-libs/'),
            'kiki-browser-gtk3':('/usr/libexec/kiki-incident-browser/153.6.0esr/compat/','/usr/share/licenses/kiki-browser-gtk3/'),
        }
        assert entry['name'] in allowed and all(path.startswith(allowed[entry['name']]) for path in extra_paths),'Unexpected candidate dependency namespace'
        assert not extra_paths.intersection(newpaths),'Extra package would overwrite operations files'
        newpaths.update(extra_paths)
        assert entry['name'] not in {r['name'] for r in index['packages']},'Extra package would replace an existing record'
        assert not (packages/archive.name).exists(),'Extra archive collision'
        shutil.copy2(archive,packages/archive.name);index['packages'].append(entry);extras.append(dict(package=entry,audit=extra_audit))
    index['packages'].sort(key=lambda r:r['name']);ki2media.runtime_closure(index,['kiki-operations']+[e['package']['name'] for e in extras])
    ki2repo.write_json(target/'repo/index.x86_64.json',index)
    meta=ki2repo.build_metadata(name='kiki-operations-ga-test',title='KIKI Operations installed-GA candidate',description='Thin installed-GA overlay, not for ISO',channel=target.name,arch='x86_64',base_url='',created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),repo_dir=target/'repo',packages_dir=packages,iso_dir=target/'iso',packages=index['packages'])
    ki2repo.write_json(target/'repo/metadata.x86_64.json',ki2repo.sign_metadata_ed25519(meta,a.sign_key))
    result=dict(schema='kiki-operations-build-v1',baseline_index_sha256=lock['index_sha256'],index_sha256=ki2repo.file_sha256(target/'repo/index.x86_64.json'),public_key_sha256=lock['public_key_sha256'],package=new,available_archives=len(list(packages.glob('*.ki2'))),extra_packages=extras,records=len(index['packages']),preserved_installed=221,not_for_iso=True,source_code_sha256=ki2repo.file_sha256(root/'cmd/kiki-operations/main.c'),sdk=str(sdk),compiler=subprocess.check_output(['cc','--version'],text=True).splitlines()[0],audit=audit)
    ki2repo.write_json(target/'operations-build.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
