"""Compose a new signed, installed-GA-only overlay without rebuilding or replacing inputs."""
import argparse
import datetime
import json
from pathlib import Path
import shutil

import ki2media
import ki2repo
from ki2integrity import audit_payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['base','candidate','sign-key']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--extra-package',type=Path,action='append',required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    base=a.base.resolve();target=a.candidate.resolve();assert not target.exists() and not a.sign_key.resolve().is_relative_to(target)
    pub=base/'paper-pixel.ed25519.pub';lock=json.loads((root/'distro/manifests/kiki-operations-20261107-baseline.json').read_text())
    report=json.loads((base/'operations-build.json').read_text());index=json.loads((base/'repo/index.x86_64.json').read_text())
    assert ki2repo.file_sha256(pub)==lock['public_key_sha256']
    assert ki2repo.file_sha256(base/'repo/index.x86_64.json')==report['index_sha256']
    assert ki2repo.verify_metadata_ed25519(json.loads((base/'repo/metadata.x86_64.json').read_text()),pub)
    assert ki2repo.run_openssl(['pkey','-in',str(a.sign_key),'-pubout'])==pub.read_bytes()
    records={r['name']:r for r in index['packages']};assert all(records[n]['sha256']==sha for n,sha in lock['installed'].items())
    paths=set()
    for file in (base/'packages/x86_64').glob('*.ki2'):
        row=next(r for r in index['packages'] if r['file']==file.name);assert ki2repo.file_sha256(file)==row['sha256']
        paths.update(f['path'] for f in ki2repo.read_package_manifest(file)['files'] if f['type']!='dir')
    extra=[];manifests={}
    allowed={
        'kiki-incident-browser':('/opt/kiki/firefox-esr/','/usr/libexec/kiki-incident-browser/','/usr/bin/kiki-incident-browser','/usr/share/applications/org.kiki.IncidentBrowser.desktop','/usr/share/kiki-incident-browser/'),
        'kiki-browser-x11-libs':('/usr/lib/libX','/usr/share/X11/locale/','/usr/share/licenses/kiki-browser-x11-libs/'),
        'kiki-browser-gtk3':('/usr/libexec/kiki-incident-browser/153.6.0esr/compat/','/usr/share/licenses/kiki-browser-gtk3/'),
    }
    for file in a.extra_package:
        audit=audit_payload(file);assert not audit['errors'],audit
        m=ki2repo.read_package_manifest(file);row=ki2repo.package_entry(file,m);name=row['name']
        assert name in allowed and name not in records and name not in manifests
        own={f['path'] for f in m['files'] if f['type']!='dir'}
        assert all(path.startswith(allowed[name]) for path in own) and not paths.intersection(own)
        paths.update(own);manifests[name]=m;index['packages'].append(row);extra.append(dict(package=row,audit=audit,archive=str(file)))
    keys=json.loads((root/'distro/manifests/kiki-browser-dependencies-20261107.json').read_text())
    for name,m in manifests.items():
        for dep,key in m['dependency_keys'].items():
            if dep in manifests:assert manifests[dep]['build_key']==key
            else:assert keys[dep]['build_key']==key and keys[dep]['sha256']==records[dep]['sha256']
    index['packages'].sort(key=lambda r:r['name']);index['created_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    ki2media.runtime_closure(index,['kiki-operations',*manifests])
    shutil.copytree(base,target);packages=target/'packages/x86_64'
    for file in a.extra_package:assert not (packages/file.name).exists();shutil.copy2(file,packages/file.name)
    ki2repo.write_json(target/'repo/index.x86_64.json',index)
    metadata=ki2repo.build_metadata(name='kiki-operations-ga-test',title='KIKI Operations incident-ai candidate',description='Thin installed-GA overlay with isolated browser; not for ISO',channel=target.name,arch='x86_64',base_url='',created_at=index['created_at'],repo_dir=target/'repo',packages_dir=packages,iso_dir=target/'iso',packages=index['packages'])
    ki2repo.write_json(target/'repo/metadata.x86_64.json',ki2repo.sign_metadata_ed25519(metadata,a.sign_key))
    report.update(parent_candidate_index_sha256=report['index_sha256'],index_sha256=ki2repo.file_sha256(target/'repo/index.x86_64.json'),records=len(index['packages']),available_archives=len(list(packages.glob('*.ki2'))),extra_packages=extra,not_for_iso=True)
    ki2repo.write_json(target/'operations-build.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
