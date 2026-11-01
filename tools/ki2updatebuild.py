#!/usr/bin/env python3
"""Build a frozen update with the ordinary KI2 engine and pinned binary inputs."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read_plan(path, expected=None):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>2*1024*1024:raise ValueError('invalid update plan file')
    plan=json.loads(path.read_text())
    claimed=plan.pop('sha256',None)
    if plan.get('schema')!='ki2-update-build-v1' or digest(plan)!=claimed or expected and claimed!=expected:
        raise ValueError('update plan digest mismatch')
    if not re.fullmatch('[a-f0-9]{32}',plan.get('id','')):raise ValueError('invalid update ID')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}',plan.get('base','')):raise ValueError('invalid baseline')
    if not plan.get('recipes') or not isinstance(plan.get('packages'),dict):raise ValueError('empty update plan')
    for name,p in plan['packages'].items():
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9+._-]*',name) or p.get('name')!=name or not re.fullmatch('[a-f0-9]{64}',p.get('sha256','')):
            raise ValueError('invalid baseline package')
        if Path(p['file']).name!=p['file'] or not p['file'].endswith('.ki2'):raise ValueError('invalid package filename')
    plan['sha256']=claimed
    return plan


def execute(plan_path,expected,objects,snapshots,job_root,repo_root,jobs=2):
    plan=read_plan(plan_path,expected);objects=Path(objects);snapshots=Path(snapshots);job_root=Path(job_root)
    sys.path.insert(0,str(Path(repo_root)/'tools'))
    import ki2build as b
    from ki2integrity import audit_payload
    snapshot=snapshots/plan['base']
    if b.file_sha256(snapshot/'manifest.json')!=plan['base_manifest_sha256']:raise ValueError('baseline changed')
    manifest=json.loads((snapshot/'manifest.json').read_text())
    if manifest['packages']!={n:p['sha256'] for n,p in plan['packages'].items()}:raise ValueError('baseline selection mismatch')
    if not b.__dict__.get('BuildContext'):raise ValueError('KI2 engine unavailable')
    if plan.get('local_archives'):
        frozen=job_root/'update-source';frozen.mkdir(exist_ok=True)
        for name in ['distro','tools','cmd','internal','vendor','assets','go.mod','go.sum']:
            src=Path(repo_root)/name;dst=frozen/name
            if src.is_dir():shutil.copytree(src,dst,symlinks=True,dirs_exist_ok=True)
            elif src.is_file():shutil.copyfile(src,dst)
        import tarfile
        for entry in plan['local_archives']:
            relative=entry['path']
            if Path(relative).is_absolute() or '..' in Path(relative).parts:raise ValueError('unsafe local build input')
            archive=objects/entry['sha256']
            if b.file_sha256(archive)!=entry['sha256']:raise ValueError('local source input changed')
            target=frozen/relative
            if not target.resolve().is_relative_to(frozen.resolve()):raise ValueError('local build input escaped workspace')
            if target.exists():shutil.rmtree(target) if target.is_dir() else target.unlink()
            with tarfile.open(archive,'r:gz') as tar:
                members=tar.getmembers();links={m.name for m in members if m.issym()}
                for member in members:
                    if '..' in Path(member.name).parts or member.name.startswith('/') or not (member.name==relative or member.name.startswith(relative+'/')):raise ValueError('archive escaped local input')
                    if any(member.name.startswith(link+'/') for link in links):raise ValueError('archive path traverses a symlink')
                    if member.islnk():raise ValueError('local source hardlink unsupported')
                # Absolute leaf symlinks are legitimate filesystem inputs. All member paths and
                # symlink ancestors were checked above; no archive member can write through one.
                try:tar.extractall(frozen,filter='fully_trusted')
                except TypeError:tar.extractall(frozen)
        repo_root=frozen
    recipes={};seed=job_root/'update-work/packages/x86_64';seed.mkdir(parents=True,exist_ok=True)
    for name,p in plan['packages'].items():
        src=objects/p['sha256']
        if src.is_symlink() or b.file_sha256(src)!=p['sha256']:raise ValueError('baseline input hash mismatch: '+name)
        actual=b.read_package_manifest(src)
        if any(str(actual[k])!=str(p[k]) for k in ['name','version','release','arch']):raise ValueError('baseline identity mismatch')
        target=seed/p['file']
        if not target.exists():
            try:os.link(src,target)
            except OSError:shutil.copyfile(src,target)
        raw=dict(name=name,version=p['version'],release=p['release'],summary=p.get('summary',name),license=p.get('license','unknown'),
                 architectures=[p['arch']],source={'type':'local','path':str(target)},
                 dependencies={'runtime':p['dependencies'].get('runtime',[]),'build':[]},build={'system':'copy'})
        recipes[name]=b.normalize_recipe(raw,Path('pinned-baseline.json'))
    changed={}
    for raw in plan['recipes']:
        r=b.normalize_recipe(raw,Path('frozen-update.json'))
        if r.name in changed:raise ValueError('duplicate update recipe')
        if r.build.get('system') in {'stage2-stub','host-files','prebuilt'}:raise ValueError('unsupported update build system')
        changed[r.name]=r;recipes[r.name]=r
    tools={}
    for raw in plan.get('tool_recipes',[]):
        r=b.normalize_recipe(raw,Path('frozen-build-tool.json'))
        if r.name not in {'pkgconf','linux-headers'} or r.name in recipes or r.source.get('type')!='url':raise ValueError('unsupported supplementary build tool')
        tools[r.name]=r;recipes[r.name]=r
    ctx=b.BuildContext(repo_root=Path(repo_root),recipe_dir=job_root/'recipes',build_dir=job_root/'update-work/build',
        packages_dir=seed.parent,repo_dir=job_root/'repo',source_cache=job_root/'sources',rootfs_dir=None,arch='x86_64',jobs=jobs,
        toolchain_id='pinned-update-'+plan['base_manifest_sha256'][:16],dry_run=False,clean_rootfs=False,allow_unpinned=False,verbose=True)
    # Preparation has already downloaded and pinned source bytes. Compilation must
    # use those bytes, rather than making a second, potentially hanging network fetch.
    ctx.source_cache.mkdir(parents=True,exist_ok=True)
    for recipe in list(changed.values())+list(tools.values()):
        if recipe.source.get('type')!='url':continue
        for source in [recipe.source]+recipe.source.get('extra',[]):
            archive=objects/source['sha256']
            if not archive.is_file() or b.file_sha256(archive)!=source['sha256']:raise ValueError('frozen source is unavailable: '+recipe.name)
            filename=source.get('file') or Path(source['url']).name
            if Path(filename).name!=filename:raise ValueError('unsafe source filename')
            target=ctx.source_cache/filename
            if target.exists() and b.file_sha256(target)!=source['sha256']:raise ValueError('conflicting frozen source filenames')
            shutil.copyfile(archive,target)
    state={n:b.BuildRecord(p['sha256'],str(seed/p['file']),p.get('registered_at',''),recipes[n].digest,{}) for n,p in plan['packages'].items() if n not in changed}
    b.save_state(ctx,state)
    order=b.dependency_closure(recipes,sorted(changed),'x86_64',include_build_deps=True)
    order=[n for n in order if n in changed or n in tools]
    if set(order)!=set(changed)|set(tools):raise ValueError('update dependency plan incomplete')
    b.build_recipes(ctx,recipes,order)
    output=job_root/'packages/x86_64';output.mkdir(parents=True,exist_ok=True);built={}
    for name,r in changed.items():
        src=b.package_path(ctx,r);audit=audit_payload(src)
        if audit['errors']:raise ValueError('payload audit failed: '+name)
        target=output/src.name;shutil.copyfile(src,target)
        built[name]={'file':target.name,'sha256':b.file_sha256(target),'recipe_digest':r.digest}
    result={'schema':'ki2-update-build-result-v1','plan':plan['id'],'plan_sha256':expected,'packages':built}
    (job_root/'update-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--expected',required=True)
    p.add_argument('--objects',type=Path,default=Path('/update-objects'));p.add_argument('--snapshots',type=Path,default=Path('/update-snapshots'))
    p.add_argument('--job-root',type=Path,required=True);p.add_argument('--repo-root',type=Path,required=True);p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args();execute(a.plan,a.expected,a.objects,a.snapshots,a.job_root,a.repo_root,a.jobs)
