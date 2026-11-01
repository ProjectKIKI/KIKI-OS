import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import ki2autobackup as auto
import ki2buildops as ops
import ki2ci
import ki2validation as validation


class ReliabilityTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Linux process groups and backup lock')
    def test_automatic_backup_restores_db_keys_and_revokes_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);auth=root/'auth';auth.mkdir()
            with sqlite3.connect(auth/'auth.sqlite3') as db:
                db.executescript("CREATE TABLE users(name TEXT); INSERT INTO users VALUES('owner'); CREATE TABLE sessions(token TEXT); INSERT INTO sessions VALUES('test');")
            (auth/'signing.key').write_bytes(b'private-fixture')
            config=dict(components={'auth':str(auth)},destination=str(root/'backup'),status_file=str(root/'status.json'),scope='control-state',excluded=['objects'])
            result=auto.run(config)
            self.assertEqual(result['status'],'passed');self.assertFalse(result['full_restore_verified'])
            self.assertEqual(result['restore']['restored_sessions_revoked'],1)
            self.assertEqual(result['auth_databases_checked'],['auth.sqlite3'])
            self.assertEqual(Path(result['archive']).stat().st_mode&0o777,0o600)
            result2=auto.run(config);self.assertNotEqual(result['archive'],result2['archive'])
            self.assertTrue(Path(result['archive']).exists())

    def test_new_file_during_backup_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'a.json').write_text('{}')
            calls=[]
            def idle(unused):
                calls.append(1)
                if len(calls)==2:(source/'new.json').write_text('{}')
            with patch.object(ops,'idle',side_effect=idle):
                with self.assertRaisesRegex(ValueError,'inventory changed'):ops.backup({'source':source},root/'backup.tar.gz')
            self.assertFalse((root/'backup.tar.gz').exists())

    def test_validation_refuses_stale_or_changed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'snapshots/candidate/manifest.json';manifest.parent.mkdir(parents=True);manifest.write_text('{}')
            row=dict(id='a'*32,package='demo',snapshot='candidate',validation={'sha256':'old'},candidate_manifest_sha256=ops.sha(manifest))
            updates=SimpleNamespace(list=lambda:[row],validate_report=lambda key:(row,{'checks':{}},'different'))
            lib=SimpleNamespace(root=root,updates=updates,jobs=lambda:[])
            report=validation.inventory(lib)
            self.assertFalse(report['rows'][0]['all_checks_verified']);self.assertIn('변경',report['rows'][0]['error'])
            self.assertFalse(report['automatic_promotion'])
            manifest.write_text('{"changed":true}')
            self.assertIn('해시',validation.inventory(lib)['rows'][0]['error'])

    @unittest.skipUnless(os.name=='posix','Linux process groups')
    def test_running_build_cancel_kills_silent_child_and_preserves_inputs(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);pidfile=state/'child.pid'
            child='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)'
            command=[sys.executable,'-u','-c',
                     'import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,"-c",'+repr(child)+']);pathlib.Path('+repr(str(pidfile))+').write_text(str(p.pid));print("started",flush=True);time.sleep(120)']
            server=ki2ci.BuildServer(ki2ci.CiConfig(root,state,'x86_64',1,'cancel-test',state/'publish'))
            try:
                with patch.object(ki2ci,'pipeline_steps',return_value=[ki2ci.Step('silent-child',command),ki2ci.Step('must-skip',[sys.executable,'-c','raise Exception()'])]):
                    job=server.submit('smoke')
                    deadline=time.monotonic()+15
                    while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.05)
                    self.assertTrue(pidfile.exists())
                    server.cancel(job['id'])
                    while server.store.read(job['id'])['status']=='running' and time.monotonic()<deadline:time.sleep(.05)
                    result=server.store.read(job['id']);self.assertEqual(result['status'],'cancelled')
                    self.assertEqual(result['steps'][1]['status'],'skipped')
                    self.assertTrue((server.store.jobs_dir/job['id']/'build-inputs.json').exists())
                    self.assertIn('started',server.store.log_path(job['id']).read_text())
                    stat=Path('/proc')/pidfile.read_text()/'stat'
                    self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')
            finally:server.close()

    def test_executed_scap_is_not_automatically_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'snapshots/candidate/manifest.json';manifest.parent.mkdir(parents=True);manifest.write_text('{}')
            row=dict(id='a'*32,package='demo',snapshot='candidate',validation={'sha256':'report'},candidate_manifest_sha256=ops.sha(manifest),security_policy={'sha256':'policy'})
            report={'checks':dict(rebooted=True,gnome_session=True,security_scan_executed=True),'security':{'after':{'rules':[{'result':'fail'}]}}}
            updates=SimpleNamespace(list=lambda:[row],validate_report=lambda key:(row,report,'report'))
            lib=SimpleNamespace(root=root,updates=updates,jobs=lambda:[])
            self.assertEqual(validation.inventory(lib)['rows'][0]['gates']['scap'],'설정 불일치')
            self.assertFalse(validation.inventory(lib)['rows'][0]['all_checks_verified'])
            report['security']['after']['rules'][0]['result']='pass'
            self.assertTrue(validation.inventory(lib)['rows'][0]['all_checks_verified'])


if __name__=='__main__':unittest.main()
