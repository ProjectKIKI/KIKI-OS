"""Package additive browser candidates; Mozilla binary and native X.Org payload stay explicit."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import ki2build
import ki2repo
from ki2integrity import audit_payload
from build_kiki_browser_x11 import unpack


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=['browser','x11','gtk3'])
    for name in ['source','work','baseline','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--x11-package',type=Path)
    p.add_argument('--gtk3-package',type=Path)
    p.add_argument('--dependency-lock',type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    assert not a.work.exists() and not a.output.exists();a.work.mkdir(parents=True);a.output.mkdir(parents=True)
    records={r['name']:r for r in json.loads((a.baseline/'repo/index.x86_64.json').read_text())['packages']}
    if a.kind=='browser':
        lock=json.loads((root/'distro/manifests/firefox-esr-153.6.0esr.json').read_text())
        archive=a.source/'firefox-153.6.0esr.tar.xz';assert ki2repo.file_sha256(archive)==lock['sha256']
        assert hashlib.sha512(archive.read_bytes()).hexdigest()==lock['sha512']
        status=subprocess.run(['gpg','--homedir',str(a.source/'gnupg'),'--batch','--status-fd=1','--verify',str(a.source/'SHA512SUMS.asc'),str(a.source/'SHA512SUMS')],capture_output=True,text=True,check=True)
        assert 'VALIDSIG '+lock['signing_subkey'] in status.stdout and lock['signing_primary'] in status.stdout
        stage=a.work/'staged';slot=stage/'usr/libexec/kiki-incident-browser'/lock['version'];slot.parent.mkdir(parents=True)
        extracted=unpack(archive,a.work/'unpacked');shutil.move(str(extracted),str(slot))
        shutil.copytree(root/'distro/sources/kiki-incident-browser',stage,dirs_exist_ok=True)
        (stage/'usr/bin/kiki-incident-browser').chmod(0o755)
        assert ki2build.package_entry_mode('usr/libexec/kiki-incident-browser/'+lock['version']+'/firefox',slot/'firefox')==0o755
        assert a.x11_package and a.gtk3_package
        m=ki2repo.read_package_manifest(a.x11_package);records['kiki-browser-x11-libs']=ki2repo.package_entry(a.x11_package,m)
        name='kiki-incident-browser';provenance=dict(kind='official-mozilla-prebuilt',input=lock,signature_status=status.stdout)
    else:
        stage=a.source;assert stage.is_dir();name='kiki-browser-gtk3' if a.kind=='gtk3' else 'kiki-browser-x11-libs'
        provenance=dict(kind='native-source-build',input=json.loads((root/('distro/manifests/kiki-browser-gtk3-20261107.json' if a.kind=='gtk3' else 'distro/manifests/kiki-browser-x11-20261107.json')).read_text()))
    recipe=ki2build.load_recipes(root/'distro/recipes')[name]
    keys=json.loads((a.dependency_lock or root/'distro/manifests/kiki-browser-dependencies-20261107.json').read_text())
    dependencies={}
    for dep in recipe.dependencies['runtime']:
        if dep=='kiki-browser-x11-libs':dependencies[dep]=ki2repo.read_package_manifest(a.x11_package)['build_key']
        elif dep=='kiki-browser-gtk3':dependencies[dep]=ki2repo.read_package_manifest(a.gtk3_package)['build_key']
        else:
            # The baseline index fixes the exact package; the lock supplies its matching build key.
            assert keys[dep]['sha256']==records[dep]['sha256'];dependencies[dep]=keys[dep]['build_key']
    key=ki2build.stable_hash(dict(recipe=recipe.digest,files=ki2build.package_file_manifest(stage),dependencies=dependencies,provenance=provenance))
    archive=a.output/ki2build.package_filename(recipe,'x86_64');ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,stage,archive,key,dependencies)
    audit=audit_payload(archive);assert not audit['errors'],audit
    report=dict(package=ki2repo.package_entry(archive,ki2repo.read_package_manifest(archive)),audit=audit,provenance=provenance)
    (a.output/'build.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
