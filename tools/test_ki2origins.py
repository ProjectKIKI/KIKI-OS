import unittest
import json
from pathlib import Path
import tempfile
import ki2origins as origins


class OriginTests(unittest.TestCase):
    def test_upstream_archive_is_not_confused_with_recipe_git(self):
        result=origins.source_origin({'source':{'url':'https://download.gnome.org/sources/gtk/4.22/gtk-4.22.4.tar.xz','sha256':'a'*64},'provenance':{'git':{'remote':'https://git.example.org/kiki.git','commit':'b'*40}}})
        self.assertEqual(result['kind'],'upstream')
        self.assertEqual(result['host'],'download.gnome.org')
        self.assertIn('빌드 레시피 Git 저장소',origins.links(result))
        self.assertIn('레시피 커밋',origins.links(result))

    def test_local_path_and_missing_commit_are_explicit(self):
        result=origins.source_origin({'source':{'type':'local','path':'cmd/kiki-admin'}})
        self.assertEqual(result['local_path'],'cmd/kiki-admin')
        self.assertIn('커밋 미기록',origins.links(result))
        self.assertIn('출처 확인 필요',origins.links(origins.source_origin({})))

    def test_credentials_queries_and_private_locations_are_not_exported(self):
        for value in ['https://user:secret@example.org/src.tar','https://example.org/src?token=secret','file:///home/lab/private',
                      'javascript:alert(1)','https://127.0.0.1/src.tar','https://localhost/src','https://host.internal/a']:
            self.assertEqual(origins.public_url(value),'')
        for path in ['/home/lab/private','C:/Users/test/private','../../private']:
            self.assertEqual(origins.source_origin({'source':{'type':'local','path':path}})['local_path'],'')

    def test_untrusted_text_is_html_escaped(self):
        result=origins.source_origin({'source':{'type':'local','path':'cmd/<script>bad</script>'}})
        page=origins.page('test',[{'name':'<img src=x>','version':'1','release':'1','origin':result}])
        self.assertNotIn('<img src=x>',page)
        self.assertNotIn('<script>bad',page)
        self.assertIn('&lt;img',page)

    def test_nested_native_source_and_bootstrap_remain_distinct(self):
        result=origins.source_origin({'source':{'source':{'url':'https://example.org/src.tar.xz','sha256':'b'*64},'options':['--disable-tests']}})
        self.assertEqual(result['kind'],'upstream')
        result=origins.source_origin({'source':{'type':'bootstrap','path':'tools/prepare.py','url':'https://example.org/project'}})
        self.assertEqual(result['kind'],'bootstrap')
        self.assertIn('원 프로젝트',origins.links(result))
        self.assertEqual(origins.source_origin({'source':'legacy/package.ki2'})['kind'],'unknown')

    def test_audit_does_not_assign_source_to_a_different_package(self):
        package={'sha256':'a'*64,'name':'demo','version':'1','release':'1'}
        audit=dict(package,source={'type':'local','path':'cmd/demo'},origin_audit={'note':'checked'})
        self.assertEqual(origins.audited_record(package,{}, {'a'*64:audit})['source']['path'],'cmd/demo')
        for field,value in [('sha256','b'*64),('name','other'),('version','2'),('release','2')]:
            self.assertEqual(origins.audited_record(dict(package,**{field:value}),{}, {'a'*64:audit}),{})

    def test_invalid_audit_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'audit.json'
            path.write_text(json.dumps({'schema':'ki2-origin-audit-v1','packages':{'a'*64:{'sha256':'b'*64}}}))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):origins.load_audit(path)
