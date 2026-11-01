import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import ki2buildops as ops


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_clean_restore_starts_real_auth_database_and_preserves_ed25519_identity(self):
        import ki2ci_auth as auth
        state=self.root/'auth';store=auth.AuthStore(state);store.bootstrap();code=(state/'setup-code').read_text().strip()
        password='Local restore test password 2026!';self.assertTrue(store.setup(code,'restore-owner',password));token,_=store.new_session('restore-owner')
        config=self.root/'config';config.mkdir();key=config/'test.ed25519'
        subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],check=True,capture_output=True)
        before=subprocess.check_output(['openssl','pkey','-in',str(key),'-pubout'])
        archive=self.root/'recovery.tar.gz';ops.backup(dict(auth=state,config=config),archive);dest=self.root/'clean-install';ops.restore(archive,dest)
        recovered=auth.AuthStore(dest/'components/auth');self.assertTrue(recovered.verify_password('restore-owner',password));self.assertIsNone(recovered.session(token))
        self.assertEqual(subprocess.check_output(['openssl','pkey','-in',str(dest/'components/config/test.ed25519'),'-pubout']),before)

    def test_fresh_restore_preserves_accounts_and_keys_but_revokes_sessions(self):
        catalog=self.root/'catalog';catalog.mkdir();(catalog/'current.json').write_text('{"revision":4}')
        auth=self.root/'auth';auth.mkdir()
        with sqlite3.connect(auth/'auth.sqlite3') as db:
            db.executescript("CREATE TABLE users(name TEXT,password TEXT); INSERT INTO users VALUES('owner','hashed-only'); CREATE TABLE sessions(token TEXT); INSERT INTO sessions VALUES('expired-on-restore');")
        release=self.root/'release';release.mkdir();(release/'private.key').write_text('test-key-material');(release/'private.key').chmod(0o600)
        archive=self.root/'backup.tar.gz';result=ops.backup(dict(catalog=catalog,auth=auth,release=release),archive)
        self.assertEqual(result['status'],'passed');destination=self.root/'new-server';restored=ops.restore(archive,destination)
        self.assertEqual(restored['restored_sessions_revoked'],1)
        self.assertEqual((destination/'components/release/private.key').read_text(),'test-key-material')
        with sqlite3.connect(destination/'components/auth/auth.sqlite3') as db:
            self.assertEqual(db.execute('SELECT name,password FROM users').fetchall(),[('owner','hashed-only')]);self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'must not exist'):ops.restore(archive,destination)

    def test_backup_refuses_active_work_and_never_overwrites(self):
        jobs=self.root/'jobs';(jobs/'job1').mkdir(parents=True);file=jobs/'job1/metadata.json';file.write_text('{"status":"running"}')
        archive=self.root/'backup.tar.gz'
        with self.assertRaisesRegex(ValueError,'active jobs'):ops.backup(dict(jobs=jobs),archive)
        file.write_text('{"status":"failed"}');ops.backup(dict(jobs=jobs),archive)
        with self.assertRaisesRegex(ValueError,'already exists'):ops.backup(dict(jobs=jobs),archive)

    def test_tamper_and_path_traversal_are_rejected_without_creating_destination(self):
        for name in ['../outside','/absolute','components/catalog/../outside','components/catalog/file']:
            archive=self.root/'bad.tar.gz';data=b'bad'
            with tarfile.open(archive,'w:gz') as tar:
                entry=tarfile.TarInfo(name);entry.size=len(data);tar.addfile(entry,io.BytesIO(data))
                manifest=dict(schema='kiki-build-backup-v1',files={name:dict(type='file',bytes=3,sha256='0'*64,mode=0o600)})
                raw=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
            with self.subTest(name=name),self.assertRaises(ValueError):ops.restore(archive,self.root/'target')
            self.assertFalse((self.root/'target').exists())

    def test_health_reports_low_space_without_deleting(self):
        with mock.patch.object(ops.shutil,'disk_usage',return_value=type('Disk',(),{'free':100,'total':10000})()):
            self.assertFalse(ops.health(self.root)['ok'])


if __name__=='__main__':unittest.main()
