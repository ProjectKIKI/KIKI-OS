import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
if os.name=='posix':
    import pwd
    import ki2xfsbackup as backup


@unittest.skipUnless(os.name=='posix','Linux XFS backup tools')
class XfsBackupTests(unittest.TestCase):
    def test_missing_mount_fails_before_service_stop_or_archive_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'data';source.mkdir();target=root/'backup';target.mkdir()
            config=dict(source=str(source),target=str(target),source_uuid='original',target_uuid='backup',
                        user=pwd.getpwuid(os.getuid()).pw_name,units=['never-stop-this'],
                        status_file=str(root/'status.json'),public_status_file=str(root/'public.json'))
            path=root/'config.json';path.write_text(json.dumps(config))
            with patch('sys.argv',['backup','--config',str(path)]),patch.object(backup.os,'geteuid',return_value=0),patch.object(backup.subprocess,'run') as execute:
                self.assertEqual(backup.main(),1);execute.assert_not_called()
            self.assertFalse((target/'archives').exists())
            self.assertFalse(json.loads((root/'status.json').read_text())['full_restore_verified'])

    def test_wrong_uuid_is_rejected(self):
        with patch.object(Path,'is_mount',return_value=True),patch.object(backup.subprocess,'check_output',return_value='different\n'):
            with self.assertRaisesRegex(ValueError,'UUID'):backup.mount_identity('/backup','expected')

    def test_archive_checksum_changes_after_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'archive';path.write_bytes(b'archive-bytes')
            self.assertEqual(backup.digest(path),hashlib.sha256(b'archive-bytes').hexdigest())
            previous=backup.digest(path);path.write_bytes(b'changed');self.assertNotEqual(backup.digest(path),previous)

    def test_host_configuration_is_recovered_and_compared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input';source.mkdir();(source/'unit.conf').write_text('configuration')
            target=root/'backup';(target/'archives').mkdir(parents=True)
            result=backup.host_configuration(target,'test-run',[str(source)])
            self.assertEqual(result['regular_files_restored_and_verified'],1)
            restored=target/'restore-tests/test-run/host-config'/str(source/'unit.conf').lstrip('/')
            self.assertEqual(restored.read_text(),'configuration')
            with self.assertRaises(ValueError):backup.host_configuration(target,'unsafe',['/'])

    def test_recovery_never_clears_another_maintenance_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'maintenance.json';marker.write_text(json.dumps({'run_id':'other-owner'}))
            state=root/'status.json';state.write_text(json.dumps({'run_id':'our-run','services_stopped':True}))
            config=dict(source=str(root/'data'),target=str(root/'backup'),source_uuid='source',status_file=str(state),
                        user=pwd.getpwuid(os.getuid()).pw_name,maintenance_markers=[str(marker)],units=['test-unit'],public_status_file=str(root/'public.json'))
            path=root/'config.json';path.write_text(json.dumps(config))
            with patch('sys.argv',['backup','--config',str(path),'--recover-only']),patch.object(backup.os,'geteuid',return_value=0),patch.object(backup,'mount_identity'),patch.object(backup.subprocess,'run') as execute:
                with self.assertRaisesRegex(ValueError,'다른 유지보수'):backup.main()
                execute.assert_not_called()
            self.assertEqual(json.loads(marker.read_text())['run_id'],'other-owner')

    def test_maintenance_blocks_build_and_release_submission(self):
        import ki2ci,ki2release
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'ci'
            server=ki2ci.BuildServer(ki2ci.CiConfig(repo,state,'x86_64',1,'test',root/'publish'))
            try:
                (state/'maintenance.json').write_text('{}')
                with self.assertRaisesRegex(ki2ci.CiError,'유지보수'):server.submit('smoke')
                with self.assertRaisesRegex(ki2ci.CiError,'유지보수'):server.submit_update('a'*32,'b'*64)
                self.assertEqual(server.store.list(),[])
            finally:server.close()
            lib=ki2release.Library(root/'release',repo,root/'baseline',root/'sources',root/'packages')
            (lib.root/'maintenance.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'유지보수'):lib.submit('sync',{})
            self.assertEqual(lib.jobs(),[])


if __name__=='__main__':unittest.main()
