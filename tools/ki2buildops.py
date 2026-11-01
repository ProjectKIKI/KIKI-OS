#!/usr/bin/env python3
"""KIKI Build v1 recovery tools. No production deletion or channel promotion."""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import time

VERSION='1.0.0'
CONTRACT=dict(schema='kiki-build-contract-v1',version=VERSION,release_stage='stable',architectures=['x86_64'],
              catalog_schema='kiki-web-catalog-v1',group_schema='ki2-package-groups-v1',
              compatibility='v1 additions are optional; incompatible field changes require schema migration',
              stable_promotion='explicit operator action after VM validation',
              exclusions=['distributed workers','atomic full-root rollback','kernel maintenance update through package update form'])
COMPONENTS={'catalog','jobs','release','auth','config','source'}
SKIP={'work','tmp','rootfs','iso-tree','__pycache__','pycache','.git','.venv','node_modules'}


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def relative(value):
    p=PurePosixPath(value)
    if not value or p.is_absolute() or '\\' in value or any(x in {'.','..'} for x in value.split('/')) or '\x00' in value:
        raise ValueError('unsafe backup path')
    return p


def files(root, excluded=()):
    def walk(folder):
        for p in sorted(folder.iterdir()):
            if p.name in SKIP or p.name in excluded or p.name.endswith(('-wal','-shm')):continue
            if p.is_symlink():yield p
            elif p.is_dir():yield from walk(p)
            elif p.is_file():yield p
            else:raise ValueError('special file in backup input')
    return list(walk(root))


def idle(roots):
    for name in ['jobs','release']:
        root=roots.get(name)
        if not root:continue
        search=root if name=='jobs' else root/'jobs'
        for pattern in ['*/metadata.json','*/job.json']:
            for path in search.glob(pattern):
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('status') in ['pending','running']:raise ValueError('active jobs: wait for a maintenance window')


def backup(roots, output, *, excluded=()):
    roots={k:Path(v).resolve(strict=True) for k,v in roots.items()};output=Path(output).absolute()
    if not roots or set(roots)-COMPONENTS:raise ValueError('unsupported backup component')
    if any(not p.is_dir() for p in roots.values()):raise ValueError('components must be directories')
    if any(output.is_relative_to(p) for p in roots.values()):raise ValueError('backup output must be outside its inputs')
    if output.exists():raise ValueError('backup output already exists')
    idle(roots);output.parent.mkdir(parents=True,exist_ok=True)
    def selected(root):return files(root, excluded)
    def inventory():
        return {str(p):(p.lstat().st_size,p.lstat().st_mtime_ns,os.readlink(p) if p.is_symlink() else '')
                for root in roots.values() for p in selected(root) if p.suffix not in {'.sqlite','.sqlite3','.db'}}
    initial_inventory=inventory()
    estimate=sum(p.stat().st_size for root in roots.values() for p in selected(root) if not p.is_symlink())
    if shutil.disk_usage(output.parent).free<estimate+64*1024**2:raise ValueError('not enough disk space for backup; use another volume')
    records={};critical={}
    for key,root in roots.items():
        for p in selected(root):
            if not p.is_symlink() and p.suffix in ['.json','.toml','.key','.pub','.conf']:critical[str(p)]=sha(p)
    try:
        with tempfile.TemporaryDirectory(prefix='kiki-backup-',dir=output.parent) as tmp, output.open('xb') as out:
            output.chmod(0o600)
            with tarfile.open(fileobj=out,mode='w:gz') as archive:
                for key,root in roots.items():
                    for p in selected(root):
                        rel=p.relative_to(root).as_posix();relative(rel);name='components/'+key+'/'+rel
                        mode=p.lstat().st_mode&0o777
                        if p.is_symlink():
                            target=os.readlink(p)
                            if Path(target).is_absolute() or '..' in Path(target).parts or not (p.parent/target).resolve().is_relative_to(root):raise ValueError('backup link leaves component or uses parent traversal')
                            entry=tarfile.TarInfo(name);entry.type=tarfile.SYMTYPE;entry.linkname=target;archive.addfile(entry)
                            records[name]=dict(type='symlink',target=target,mode=mode);continue
                        source=p
                        if p.suffix in ['.sqlite','.sqlite3','.db']:
                            source=Path(tmp)/hashlib.sha256(name.encode()).hexdigest()
                            with sqlite3.connect('file:'+p.as_posix()+'?mode=ro',uri=True) as original,sqlite3.connect(source) as snapshot:original.backup(snapshot)
                        before=source.stat();digest=sha(source)
                        entry=tarfile.TarInfo(name);entry.size=before.st_size;entry.mode=mode;entry.mtime=0
                        with source.open('rb') as data:archive.addfile(entry,data)
                        after=source.stat()
                        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('backup input changed')
                        records[name]=dict(type='file',bytes=entry.size,sha256=digest,mode=mode)
                idle(roots)
                if inventory()!=initial_inventory:raise ValueError('backup inventory changed; retry later')
                if any(sha(Path(p))!=digest for p,digest in critical.items()):raise ValueError('state changed during backup; retry in a maintenance window')
                manifest=dict(schema='kiki-build-backup-v1',build_version=VERSION,created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),components=sorted(roots),files=records,excluded_transient_names=sorted(SKIP),additional_exclusions=sorted(excluded))
                payload=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(payload);entry.mode=0o600;archive.addfile(entry,io.BytesIO(payload))
        return dict(status='passed',files=len(records),bytes=output.stat().st_size,sha256=sha(output),contains_private_state=True)
    except Exception:
        output.unlink(missing_ok=True);raise


def restore(archive_path, destination):
    destination=Path(destination).absolute()
    if destination.exists():raise ValueError('restore destination must not exist')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive_path,'r:gz') as archive:
        members=archive.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)) or names.count('manifest.json')!=1:raise ValueError('duplicate/missing backup entries')
        manifest_member=archive.getmember('manifest.json')
        if not manifest_member.isfile() or manifest_member.size>8*1024**2:raise ValueError('invalid backup manifest')
        manifest=json.load(archive.extractfile(manifest_member))
        if manifest.get('schema')!='kiki-build-backup-v1' or set(names)-{'manifest.json'}!=set(manifest['files']):raise ValueError('backup manifest coverage mismatch')
        total=0
        for member in members:
            if member.name=='manifest.json':continue
            p=relative(member.name);record=manifest['files'][member.name]
            if len(p.parts)<3 or p.parts[0]!='components' or p.parts[1] not in COMPONENTS:raise ValueError('unknown backup component')
            if member.isfile() and record['type']=='file':
                if member.size!=record['bytes'] or member.size>8*1024**3:raise ValueError('backup length mismatch')
                total+=member.size
            elif member.issym() and record['type']=='symlink':
                target=member.linkname
                combined=Path('/restore').joinpath(*p.parts).parent/target
                if Path(target).is_absolute() or '..' in Path(target).parts or not combined.resolve().is_relative_to(Path('/restore/components')/p.parts[1]) or target!=record['target']:raise ValueError('unsafe backup link')
            else:raise ValueError('unsupported backup entry type')
        if shutil.disk_usage(destination.parent).free<total+64*1024**2:raise ValueError('not enough disk space to restore')
        with tempfile.TemporaryDirectory(prefix='.kiki-restore-',dir=destination.parent) as temporary:
            stage=Path(temporary)/'restored';stage.mkdir(mode=0o700)
            for member in members:
                if not member.isfile() or member.name=='manifest.json':continue
                record=manifest['files'][member.name];path=stage/member.name;path.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as src,path.open('xb') as out:shutil.copyfileobj(src,out,1024**2)
                if sha(path)!=record['sha256']:raise ValueError('backup file SHA mismatch')
                path.chmod(record['mode']&0o777)
            for member in members:
                if member.issym():
                    path=stage/member.name;path.parent.mkdir(parents=True,exist_ok=True);path.symlink_to(member.linkname)
            revoked=0
            for database in (stage/'components/auth').glob('*.sqlite3') if (stage/'components/auth').exists() else []:
                with sqlite3.connect(database) as connection:
                    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone():
                        revoked+=connection.execute('SELECT count(*) FROM sessions').fetchone()[0];connection.execute('DELETE FROM sessions')
            (stage/'restored-backup-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            stage.rename(destination)
        return dict(status='passed',files=len(manifest['files']),restored_sessions_revoked=revoked)


def health(root):
    root=Path(root);disk=shutil.disk_usage(root)
    return dict(schema='kiki-build-health-v1',version=VERSION,ok=disk.free>=1024**3,free_bytes=disk.free,total_bytes=disk.total,
                warning='디스크 여유가 10GiB 미만입니다.' if disk.free<10*1024**3 else '',backup_restore_required=True)


def retention_plan(jobs,keep=10):
    rows=sorted(jobs.glob('*/metadata.json'),reverse=True);terminal=[]
    for file in rows:
        row=json.loads(file.read_text(encoding='utf-8'))
        if row.get('status') in ['failed','cancelled','interrupted','succeeded']:terminal.append((file.parent,row))
    result=[];deadline=time.monotonic()+0.25
    for folder,row in terminal[keep:]:
        work=folder/'work'
        if not work.exists() or work.is_symlink():continue
        size=0;complete=True
        if time.monotonic()>=deadline:complete=False
        else:
            for p in work.rglob('*'):
                if time.monotonic()>=deadline:complete=False;break
                if p.is_file() and not p.is_symlink():size+=p.stat().st_size
        result.append(dict(job=row['id'],status=row['status'],scope='transient work directory only',bytes=size,size_complete=complete,automatic_delete=False))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('backup');b.add_argument('--component',action='append',required=True,help='catalog=/absolute/path; repeat for jobs,release,auth,config,source');b.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('restore');r.add_argument('--archive',type=Path,required=True);r.add_argument('--destination',type=Path,required=True)
    d=sub.add_parser('doctor');d.add_argument('--root',type=Path,required=True)
    t=sub.add_parser('retention-plan');t.add_argument('--jobs',type=Path,required=True);t.add_argument('--keep',type=int,default=10)
    sub.add_parser('contract');args=p.parse_args()
    try:
        if args.action=='backup':result=backup(dict(v.split('=',1) for v in args.component),args.output)
        elif args.action=='restore':result=restore(args.archive,args.destination)
        elif args.action=='doctor':result=health(args.root)
        elif args.action=='retention-plan':result=retention_plan(args.jobs,max(1,args.keep))
        else:result=CONTRACT
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,tarfile.TarError,sqlite3.Error) as error:p.exit(1,type(error).__name__+': '+str(error)+'\n')


if __name__=='__main__':raise SystemExit(main())
