"""전용 XFS 데이터 볼륨의 전체 백업과 격리 복구 비교. root 전용."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess
import tarfile
import time
import urllib.request
import uuid


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def mount_identity(path, expected):
    path=Path(path)
    if not path.is_mount():raise ValueError('필수 볼륨이 마운트되어 있지 않습니다: '+str(path))
    actual=subprocess.check_output(['findmnt','-n','-o','UUID','--target',str(path)],text=True).strip()
    if actual!=expected:raise ValueError('볼륨 UUID가 예상과 다릅니다: '+str(path))


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()


def host_configuration(target, run_id, paths):
    paths=[Path(value) for value in paths if Path(value).exists()]
    if not paths:return None
    if any(not path.is_absolute() or path==Path('/') or target.resolve().is_relative_to(path.resolve()) for path in paths):raise ValueError('호스트 설정 백업 경로를 확인하세요.')
    archive=target/'archives'/('kiki-host-config-'+run_id+'.tar.gz')
    fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    command(['tar','--acls','--xattrs','--selinux','-czpf',str(archive),'-C','/',*[str(path).lstrip('/') for path in paths]])
    dest=target/'restore-tests'/run_id/'host-config';dest.mkdir(parents=True,mode=0o700);dest.parent.chmod(0o700)
    count=0
    with tarfile.open(archive) as stream:
        for member in stream:
            relative=Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('호스트 설정 경로 이탈')
            if not member.isfile():continue
            data=stream.extractfile(member).read()
            if hashlib.sha256(data).hexdigest()!=digest(Path('/')/relative):raise ValueError('호스트 설정 백업 내용이 원본과 다릅니다.')
            path=dest/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o600);count+=1
    return dict(archive=str(archive),sha256=digest(archive),regular_files_restored_and_verified=count)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--recover-only',action='store_true')
    args=parser.parse_args();config=json.loads(args.config.read_text())
    if os.geteuid()!=0:raise ValueError('root 전용 백업 도구입니다.')
    source=Path(config['source']);target=Path(config['target'])
    state=Path(config['status_file']);state.parent.mkdir(parents=True,exist_ok=True)
    previous=json.loads(state.read_text()) if state.exists() else {}
    if args.recover_only:
        if not previous.get('services_stopped'):return 0
        mount_identity(source,config['source_uuid'])
        account=pwd.getpwnam(config.get('user','lab'))
        markers=[Path(value) for value in config.get('maintenance_markers',[])]
        if any(marker.exists() and json.loads(marker.read_text()).get('run_id')!=previous.get('run_id') for marker in markers):raise ValueError('다른 유지보수 작업의 표시를 제거하지 않습니다.')
        for marker in markers:marker.unlink(missing_ok=True)
        command(['runuser','-u',account.pw_name,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(account.pw_uid),'systemctl','--user','start',*config['units']])
        previous.update(status='failed',phase='중단된 백업의 서비스 복구 완료',services_stopped=False,full_restore_verified=False,error='백업이 비정상 종료되어 복구 검사 성공으로 인정하지 않았습니다.')
        state.write_text(json.dumps(previous,ensure_ascii=False,indent=2));state.chmod(0o600)
        published=Path(config['public_status_file']);published.write_text(json.dumps(previous,ensure_ascii=False,indent=2));os.chown(published,account.pw_uid,account.pw_gid);published.chmod(0o600)
        return 0
    run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    report=dict(schema='kiki-auto-backup-v1',scope='full-data-volume',status='running',phase='사전 검사',
                at=dt.datetime.now(dt.timezone.utc).isoformat(),full_restore_verified=False,
                last_success=previous.get('last_success'),last_success_archive=previous.get('last_success_archive'),
                source_uuid=config['source_uuid'],target_uuid=config['target_uuid'],run_id=run_id)
    def save(phase):
        report['phase']=phase;pending=state.with_suffix('.new');pending.write_text(json.dumps(report,ensure_ascii=False,indent=2));pending.chmod(0o600);pending.replace(state)
    account=pwd.getpwnam(config.get('user','lab'))
    def user_systemctl(*args):
        return command(['runuser','-u',account.pw_name,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(account.pw_uid),'systemctl','--user',*args])
    units=config['units'];stopped=False;markers=[];restore=None;lock=None
    try:
        import fcntl
        lock=state.with_suffix('.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        mount_identity(source,config['source_uuid']);mount_identity(target,config['target_uuid'])
        if source.resolve()==target.resolve() or target.resolve().is_relative_to(source.resolve()) or config['source_uuid']==config['target_uuid']:raise ValueError('별도 백업 볼륨이 필요합니다.')
        used=shutil.disk_usage(source).used
        if shutil.disk_usage(target).free<used*2.2+1024**3:raise ValueError('전체 백업과 격리 복구를 함께 수행할 공간이 부족합니다. 기존 백업은 삭제하지 않았습니다.')
        for port,path in [(8091,'/api/jobs'),(8094,'/api/releases')]:
            req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'Host':'127.0.0.1:18090'})
            with urllib.request.urlopen(req,timeout=10) as response:data=json.load(response)
            jobs=data if isinstance(data,list) else data['jobs']
            if any(j['status'] in {'pending','running'} for j in jobs):raise ValueError('진행 중인 작업이 있어 백업을 연기합니다.')
        for value in config.get('maintenance_markers',[]):
            marker=Path(value)
            if marker.exists():raise ValueError('이미 유지보수 중입니다.')
            marker.write_text(json.dumps({'reason':'전체 백업·복구 검사','run_id':run_id}));markers.append(marker)
        save('빌드 서비스 중지')
        stopped=True;report['services_stopped']=True;save('빌드 서비스 중지');user_systemctl('stop',*units)
        archive_dir=target/'archives';archive_dir.mkdir(mode=0o700,exist_ok=True)
        # A reused name must never overwrite a previously completed backup.
        archive=archive_dir/('kiki-full-'+run_id+'.xfsdump')
        fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        log_dir=Path(config['log_dir']);log_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        report['host_configuration']=host_configuration(target,run_id,config.get('host_paths',[]))
        report['archive']=str(archive);report['log']=str(log_dir/(run_id+'.log'))
        subprocess.run(['sync'],check=True)
        save('XFS 전체 백업')
        with Path(report['log']).open('w') as log:
            command(['xfsdump','-l','0','-L','kiki-'+run_id,'-M','kiki-full','-f',str(archive),str(source)],stdout=log,stderr=subprocess.STDOUT)
            report['bytes']=archive.stat().st_size
            save('격리 경로 전체 복구')
            restore=target/'restore-tests'/run_id/'data';restore.mkdir(parents=True,mode=0o700)
            restore.parent.chmod(0o700)
            command(['xfsrestore','-f',str(archive),str(restore)],stdout=log,stderr=subprocess.STDOUT)
        save('원본·복구본 전체 내용 및 속성 비교')
        comparison=Path(report['log']).with_suffix('.rsync')
        with comparison.open('w') as log:
            command(['rsync','--dry-run','-aHAXci','--numeric-ids','--delete',
                     '--exclude=/xfsrestorehousekeepingdir',str(source)+'/',str(restore)+'/'],stdout=log,stderr=subprocess.STDOUT)
        changes=comparison.read_text()
        if changes.strip():raise ValueError('복구본 비교에 차이가 있습니다. 비교 로그를 확인하세요.')
        report['all_files_checksum_and_attributes_equal']=True
        save('백업 파일 SHA-256 검증')
        report['sha256']=digest(archive)
        # Revoke sessions only in the isolated copy, after byte comparison.
        auth=restore/config['auth_relative']
        with sqlite3.connect(auth) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('복구 인증 DB 무결성 오류')
            report['restored_sessions_revoked']=db.execute('SELECT count(*) FROM sessions').fetchone()[0]
            db.execute('DELETE FROM sessions')
        # This is a newly created, verified disposable restore tree only.
        if restore.parent.parent.resolve()!=(target/'restore-tests').resolve() or restore.parent.name!=run_id:raise ValueError('복구 시험 경로 이탈')
        save('검증된 임시 복구본 정리')
        shutil.rmtree(restore.parent)
        report.update(status='passed',full_restore_verified=True,last_success=report['at'],last_success_archive=str(archive),
                      system_boot_restore_verified=False,contains_private_state=True)
        save('전체 데이터 볼륨 복구 검증 완료')
    except Exception as exc:
        report.update(status='deferred' if '진행 중인 작업' in str(exc) else 'failed',error=str(exc))
        save('검사 중단 · 원본과 기존 백업 보존')
    finally:
        for marker in markers:
            try:
                if json.loads(marker.read_text()).get('run_id')==run_id:marker.unlink()
            except OSError:pass
        if stopped:
            user_systemctl('start',*units);report['services_stopped']=False
            save(report['phase'])
        published=Path(config['public_status_file'])
        if published.parent.is_dir():
            published.write_text(json.dumps(report,ensure_ascii=False,indent=2));os.chown(published,account.pw_uid,account.pw_gid);published.chmod(0o600)
        if lock is not None:lock.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return int(report['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
