"""자동 백업·격리 복구 검사. 기존 산출물을 정리하거나 덮어쓰지 않습니다."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import uuid
import ki2buildops as ops
from ki2catalog import atomic


def run(config):
    roots={key:Path(value) for key,value in config['components'].items()}
    status=Path(config['status_file'])
    output=Path(config['destination'])
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    previous=json.loads(status.read_text()) if status.exists() else {}
    report=dict(schema='kiki-auto-backup-v1',at=dt.datetime.now(dt.timezone.utc).isoformat(),
                scope=config.get('scope','full'),exclusions=config.get('excluded',[]),
                last_success=previous.get('last_success'),last_success_archive=previous.get('last_success_archive'),status='running',full_restore_verified=False)
    try:
        # Serialize timers/manual runs; a second run must not overlap a restore drill.
        import fcntl
        with (output/'.backup.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for path in config.get('idle_jobs',[]):ops.idle({'jobs':Path(path)})
            used=sum(path.stat().st_size for path in output.glob('kiki-*.tar.gz'))
            if used>=config.get('max_total_bytes',2*1024**3):raise ValueError('백업 보관 한도 도달: 기존 백업을 자동 삭제하지 않습니다.')
            archive=output/('kiki-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.tar.gz')
            result=ops.backup(roots,archive,excluded=report['exclusions'])
            with tempfile.TemporaryDirectory(prefix='.restore-drill-',dir=output) as tmp:
                dest=Path(tmp)/'restored'
                restored=ops.restore(archive,dest)
                db_checks=[]
                for db in (dest/'components/auth').glob('*.sqlite3'):
                    with sqlite3.connect(db) as connection:
                        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('복구 인증 DB 무결성 오류')
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone():
                            if connection.execute('SELECT count(*) FROM sessions').fetchone()[0]:raise ValueError('복구 세션 폐기 실패')
                        db_checks.append(db.name)
                report.update(status='passed',archive=str(archive),backup=result,restore=restored,
                              auth_databases_checked=db_checks,last_success=report['at'],last_success_archive=str(archive),
                              full_restore_verified=report['scope']=='full' and not report['exclusions'])
    except (OSError,ValueError,sqlite3.Error) as error:
        report.update(status='deferred' if 'active jobs' in str(error) or isinstance(error,BlockingIOError) else 'failed',error=str(error))
    atomic(status,report)
    return report


def page(path):
    from html import escape
    try:report=json.loads(Path(path).read_text())
    except FileNotFoundError:report={'status':'미실행','last_success':None}
    return '<div class="panel"><h2>자동 백업·복구 검증</h2><p>부분 백업은 전체 서버 복구 성공으로 표시하지 않습니다. 기존 백업·릴리즈·VM을 자동 삭제하지 않습니다.</p><pre>'+escape(json.dumps(report,ensure_ascii=False,indent=2))+'</pre></div>'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    config=json.loads(parser.parse_args().config.read_text())
    report=run(config);print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if report['status']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
