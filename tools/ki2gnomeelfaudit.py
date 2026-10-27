#!/usr/bin/env python3
"""Audit candidate ELF requirements against explicit native/bootstrap suppliers."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import ki2sessioncandidate as c


def manifest(archive):
    with tarfile.open(archive,'r|*') as t:
        for m in t:
            if m.name=='manifest.json':return json.load(t.extractfile(m))
    raise ValueError('Missing manifest')


def main():
    latest={}
    for f in (c.TARGET/'validation').glob('*-build.json'):
        r=json.loads(f.read_text())
        if not r.get('file'):continue
        if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Candidate SHA mismatch: '+r['name'])
        latest[r['name']]=r
    records={}
    for r in json.loads((c.BASE/'snapshot.json').read_text())['packages']:
        if r['name'] not in latest and not r['name'].startswith('kiki-'):
            records[r['name']]=dict(r,file=str(c.BASE/'packages/x86_64'/r['file']))
    records.update(latest)
    root_scope='--root' in sys.argv
    if root_scope:
        planned=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
        latest={r['name']:r for r in planned['packages']}
        records.update(latest)
    manifests={name:manifest(r['file']) for name,r in records.items()}
    suppliers={}
    for name,m in manifests.items():
        if name.startswith('kiki-') and name!='kiki-mesa-bootstrap':continue
        for f in m['files']:
            if f['type'] in ['file','symlink'] and '.so' in Path(f['path']).name:
                suppliers.setdefault(Path(f['path']).name,set()).add(name)
    cache=c.WORK/'elf-audit';cache.mkdir(exist_ok=True)
    canonical={'libgcc_s.so.1':'libgcc','libstdc++.so.6':'libstdcxx','libz.so.1':'zlib'}
    results=[];errors=[];additions={}
    for name,r in sorted(latest.items()):
        m=manifests[name];files={x['path']:x for x in m['files']};needed=set();rpaths=[];count=0
        with tarfile.open(r['file'],'r|*') as t:
            for entry in t:
                if not entry.isfile() or not entry.name.startswith('rootfs/'):continue
                stream=t.extractfile(entry)
                magic=stream.read(4)
                if magic!=b'\x7fELF':continue
                f=files['/'+entry.name.removeprefix('rootfs/')]
                data=magic+stream.read();digest=hashlib.sha256(data).hexdigest()
                if digest!=f['sha256']:raise ValueError('ELF manifest mismatch')
                path=cache/(digest+'.elf')
                if not path.exists():path.write_bytes(data)
                dynamic=subprocess.run(['readelf','-d',str(path)],capture_output=True,text=True,check=True).stdout
                deps=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
                needed.update(deps);count+=1
                for value in re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]',dynamic):
                    rpaths.append(dict(path=f['path'],value=value))
                    if any(x in value for x in ['/home/','/mnt/','/tmp/']):errors.append(dict(package=name,path=f['path'],reason='Build path in runtime search path',value=value))
        runtime=set(m.get('dependencies',{}).get('runtime',[]));required=set()
        for soname in sorted(needed):
            owners=suppliers.get(soname,set())
            if soname in canonical and canonical[soname] in owners:owners={canonical[soname]}
            if name in owners:continue
            if not owners:errors.append(dict(package=name,reason='Unresolved ELF supplier',needed=soname));continue
            if len(owners)>1:
                chosen=owners & runtime
                if len(chosen)!=1:
                    errors.append(dict(package=name,reason='Ambiguous ELF supplier',needed=soname,owners=sorted(owners)));continue
                owners=chosen
            required.update(owners)
        additions[name]=sorted(required-runtime)
        results.append(dict(name=name,file=r['file'],sha256=r['sha256'],elf_files=count,needed=sorted(needed),runtime_paths=rpaths,additional_direct_dependencies=additions[name]))
    filename='desktop-root-elf-suppliers.json' if root_scope else 'desktop-elf-suppliers.json'
    c.save(c.TARGET/'validation'/filename,dict(packages=results,errors=errors,runtime_additions=additions,scope='Native root ELF suppliers' if root_scope else 'Current candidate ELF suppliers; baseline bundle packages excluded; no index promotion'))
    print('ELF supplier audit:',len(latest),'packages;',len(errors),'unresolved/path issues;',sum(bool(x) for x in additions.values()),'metadata additions required',flush=True)


if __name__=='__main__':main()
