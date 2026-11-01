import json
from pathlib import Path
import shutil
import tempfile
import urllib.request

import ki2http
import ki2repo
import ki2repository
from test_ki2http import HttpRepositoryTests


class RepositoryTests(HttpRepositoryTests):
    def setUp(self):
        super().setUp()
        self.store_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.store_temp.cleanup)
        self.resign()
        channel = {'name': 'candidate', 'sources': str(self.root.parent), 'pattern': self.root.name,
                   'key_file': self.public.name, 'packages': 'packages/x86_64',
                   'key_sha256': ki2http.sha(self.public)}
        self.config = {'store': self.store_temp.name, 'channels': [channel]}
        self.repository = ki2repository.Repository(self.config, self.client)
        self.addCleanup(self.repository.lease.close)

    def resign(self, created='2026-10-28T12:00:00+00:00'):
        metadata = {'created_at': created, 'index': {'sha256': ki2http.sha(self.root / 'repo/index.x86_64.json'), 'package_count': 1}}
        self.metadata.write_text(json.dumps(ki2repo.sign_metadata_ed25519(metadata, self.private)))

    def test_atomic_idempotent_publication_excludes_private_files(self):
        self.assertEqual(self.repository.scan(), [])
        before = dict(self.repository.records)
        self.assertEqual(self.repository.scan(), [])
        self.assertEqual(self.repository.records, before)
        self.assertIn('/ki2/candidate/repo/index.x86_64.json', self.repository.allowed)
        self.assertIsNone(self.repository.get('/ki2/candidate/never-serve.pem'))
        self.assertEqual(len(self.repository.records), 1)

    def test_cloud_iso_serves_only_named_unchanged_hashed_parts(self):
        jobs=Path(self.store_temp.name)/'jobs';job='a'*32;folder=jobs/job/'cloud-artifact';folder.mkdir(parents=True)
        payload=b'public ISO artifact only';import hashlib
        digest=hashlib.sha256(payload).hexdigest();part=folder/(digest+'.part');part.write_bytes(payload)
        (folder/'index.json').write_text(json.dumps({'schema':'kiki-cloud-artifact-v1','parts':[{'sha256':digest,'bytes':len(payload)}]}))
        self.repository.config['cloud_iso_jobs']=str(jobs)
        route='/ki2/build-iso/'+job+'/'+digest+'.part'
        self.assertEqual(self.repository.get(route)[0],part)
        self.assertIsNone(self.repository.get('/ki2/build-iso/'+job+'/../candidate.key'))
        self.assertIsNone(self.repository.get('/ki2/build-iso/'+job+'/'+'b'*64+'.part'))
        part.write_bytes(b'changed')
        self.assertIsNone(self.repository.get(route))

    def test_bad_payload_does_not_publish_or_replace_previous_channel(self):
        self.package.write_bytes(b'broken')
        errors = self.repository.scan()
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.repository.records, {})
        self.assertIsNone(self.repository.get('/ki2/candidate/repo/index.x86_64.json'))

    def test_signer_key_must_match_configured_pin(self):
        self.config['channels'][0]['key_sha256'] = 'a' * 64
        self.assertIn('untrusted signing key', self.repository.scan()[0]['error'])
        self.assertEqual(self.repository.records, {})

    def test_published_version_cannot_be_replaced(self):
        self.repository.scan()
        self.resign('2026-10-29T12:00:00+00:00')
        errors = self.repository.scan()
        self.assertIn('immutable published version changed', errors[0]['error'])
        self.assertEqual(len(self.repository.records), 1)

    def test_pending_source_is_never_published(self):
        self.config['channels'][0]['pattern'] = '.pending-*'
        self.assertEqual(self.repository.scan(), [])
        self.assertEqual(self.repository.records, {})

    def test_stable_selection_withholds_unapproved_candidates(self):
        pointer=Path(self.store_temp.name)/'stable.json'
        self.config['channels'][0]['selection_file']=str(pointer)
        self.assertEqual(self.repository.scan(),[])
        self.assertIsNone(self.repository.get('/ki2/candidate/repo/index.x86_64.json'))
        pointer.write_text(json.dumps({'version':self.root.name}))
        self.assertEqual(self.repository.scan(),[])
        self.assertIsNotNone(self.repository.get('/ki2/candidate/repo/index.x86_64.json'))
        self.assertEqual(len(self.repository.records),1)

    def test_publisher_lease_prevents_second_writer(self):
        with self.assertRaises(BlockingIOError):
            ki2repository.Repository(self.config, self.client)

    def test_public_origins_use_exact_package_hash_and_verify_archive_bytes(self):
        archive=Path(self.store_temp.name)/'upstream.tar.xz';archive.write_bytes(b'upstream archive')
        digest=ki2http.sha(archive)
        objects=Path(self.store_temp.name)/'objects';objects.mkdir();shutil.copyfile(archive,objects/digest)
        catalog=Path(self.store_temp.name)/'catalog.json'
        package_hash=ki2http.sha(self.package)
        record={'name':'demo','version':'1','release':'1','source':{'url':'https://example.org/upstream.tar.xz','sha256':digest}}
        catalog.write_text(json.dumps({'binaries':{package_hash:record},'sources':{digest:{'file':'upstream.tar.xz'}}}))
        self.config['provenance']={'catalog':str(catalog),'objects':str(objects)}
        self.repository.scan()
        origin=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(origin['origin']['kind'],'upstream')
        self.assertEqual(self.repository.get(origin['archive_url'])[0].read_bytes(),b'upstream archive')
        (objects/digest).write_bytes(b'tampered')
        self.repository.scan()
        origin=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(origin['archive_url'],'')
        record['name']='unrelated-package'
        catalog.write_text(json.dumps({'binaries':{package_hash:record}}))
        self.repository.scan()
        origin=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(origin['origin']['kind'],'unknown')

    def test_audited_historical_origin_and_archive_are_bound_to_package_bytes(self):
        digest=ki2http.sha(self.package)
        objects=Path(self.store_temp.name)/'audit-objects';objects.mkdir()
        source_hash=__import__('hashlib').sha256(b'old source').hexdigest()
        (objects/source_hash).write_bytes(b'old source')
        record={'sha256':digest,'name':'demo','version':'1','release':'1','recipe_digest':'a'*64,
                'source':{'type':'url','url':'https://example.org/old.tar.xz','sha256':source_hash,'file':'old.tar.xz'},
                'origin_audit':{'source_verified':True,'method':'recipe-digest'}}
        audit=Path(self.store_temp.name)/'audit.json'
        audit.write_text(json.dumps({'schema':'ki2-origin-audit-v1','packages':{digest:record}}))
        self.config['provenance']={'audit_file':str(audit),'audit_objects':str(objects)}
        self.assertEqual(self.repository.scan(),[])
        row=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(row['origin']['kind'],'upstream')
        self.assertTrue(row['origin']['audit']['source_verified'])
        self.assertEqual(self.repository.get(row['archive_url'])[0].read_bytes(),b'old source')
        record['release']='2'
        audit.write_text(json.dumps({'schema':'ki2-origin-audit-v1','packages':{digest:record}}))
        self.repository.scan()
        row=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(row['origin']['kind'],'unknown')
        self.assertEqual(row['archive_url'],'')

    def test_local_update_source_archive_is_verified_before_publication(self):
        objects=Path(self.store_temp.name)/'local-inputs';objects.mkdir()
        archive=objects/'input.tar.gz';archive.write_bytes(b'frozen local source')
        digest=ki2http.sha(archive);archive.rename(objects/digest)
        catalog=Path(self.store_temp.name)/'catalog.json'
        record={'name':'demo','version':'1','release':'1','source':{'type':'local','path':'distro/sources/demo','sha256':digest}}
        catalog.write_text(json.dumps({'binaries':{ki2http.sha(self.package):record},'sources':{digest:{'file':'demo-source.tar.gz'}}}))
        self.config['provenance']={'catalog':str(catalog),'objects':str(objects)}
        self.assertEqual(self.repository.scan(),[])
        row=json.loads(self.repository.get('/ki2/candidate/sources.json')[0].read_bytes())['packages'][0]
        self.assertEqual(row['origin']['kind'],'local')
        self.assertEqual(self.repository.get(row['archive_url'])[0].read_bytes(),b'frozen local source')

    def test_same_filename_with_changed_bytes_does_not_advance_channel(self):
        sources=Path(self.store_temp.name)/'inputs'
        first=sources/'first';second=sources/'second'
        shutil.copytree(self.root,first);shutil.copytree(self.root,second)
        self.config['channels'][0].update(sources=str(sources),pattern='*')
        payload=second/'packages/x86_64'/self.package.name
        payload.write_bytes(b'new bytes under an old package filename')
        index_path=second/'repo/index.x86_64.json'
        index=json.loads(index_path.read_bytes())
        index['packages'][0].update(sha256=ki2http.sha(payload),size=payload.stat().st_size)
        index_path.write_text(json.dumps(index))
        metadata={'created_at':'2026-10-29T12:00:00+00:00','index':{'sha256':ki2http.sha(index_path),'package_count':1}}
        (second/'repo/metadata.x86_64.json').write_text(json.dumps(ki2repo.sign_metadata_ed25519(metadata,self.private)))
        errors=self.repository.scan()
        self.assertTrue(any('promotion refused' in e['error'] for e in errors))
        current=json.loads(self.repository.get('/ki2/candidate/repo/index.x86_64.json')[0].read_bytes())
        self.assertEqual(current['packages'][0]['sha256'],ki2http.sha(self.package))
        self.assertIn('/ki2/versions/candidate/second/repo/index.x86_64.json',self.repository.allowed)
