import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import ki2security as security
import ki2release as core
import test_ki2release as fixtures


class ProviderTests(unittest.TestCase):
    def test_pagination_and_withdrawn_records(self):
        reader=mock.Mock(side_effect=[{'vulns':[{'id':'CVE-2020-1'}],'next_page_token':'page2'}, {'vulns':[{'id':'CVE-2020-2','withdrawn':'2020'}]}])
        rows=security.osv_query({'ecosystem':'GIT','project':'https://example.org/repo','tag_prefix':'v'},'1.2',reader)
        self.assertEqual([r['id'] for r in rows],['CVE-2020-1']);self.assertEqual(reader.call_args[0][1]['page_token'],'page2')

    def test_incomplete_lookup_is_not_success(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):
            security.osv_query({'ecosystem':'GIT','project':'repo'},'1',lambda *a:{'next_page_token':'always'})

    def test_aliases_kev_fixed_and_untrusted_http_links(self):
        row=security.normalize({'id':'GHSA-123','aliases':['CVE-2020-1'],'affected':[{'ranges':[{'events':[{'fixed':'2.0'}]}]}],
            'references':[{'url':'javascript:alert(1)'},{'url':'https://example.org/advisory'}]},'OSV',{'CVE-2020-1'})
        self.assertEqual(row['id'],'CVE-2020-1');self.assertEqual(row['status'],'potential');self.assertTrue(row['kev'])
        self.assertEqual(row['fixed'],['2.0']);self.assertEqual(row['references'],['https://example.org/advisory'])

    def test_no_arbitrary_provider_urls(self):
        with self.assertRaises(ValueError):security.fetch_json('http://127.0.0.1/private')

    def test_osv_aliases_are_counted_once(self):
        rows=[security.normalize({'id':n,'aliases':['CVE-2020-1']},'OSV',set()) for n in ['GHSA-a','OSV-b']]
        merged=security.merge_findings(rows);self.assertEqual(len(merged),1);self.assertEqual(len(merged[0]['aliases']),3)


class SecurityTests(unittest.TestCase):
    package=fixtures.LibraryTests.package
    def setUp(self):
        fixtures.LibraryTests.setUp(self)
        self.manager=self.lib.updates;self.scan=self.manager.security
        package=self.package();p=self.lib.add_binary(package,core.sha(package),'fixture',{'type':'url','url':'https://example.org/demo-1.0.tar.gz','sha256':'a'*64})
        self.lib.snapshot('base',{'demo':p['sha256']},'fixture')
        core.save(self.manager.root/'config.json',{'baseline':'base','enabled':False})
        self.scan.mapping_file=self.root/'mappings.json'
        core.save(self.scan.mapping_file,{'packages':{'demo':{'ecosystem':'OSS-Fuzz','project':'demo','source_prefixes':['https://example.org/demo-']}}})
        self.job={'values':{'base':'base'},'id':'security-job','kind':'update-security','status':'running'}
        self.update=mock.patch.object(self.lib,'update');self.update.start();self.addCleanup(self.update.stop)
    def reader(self,url,data=None):
        if 'cisa.gov' in url:return {'vulnerabilities':[]}
        return {'vulns':[{'id':'CVE-2020-0001','modified':'2026-01-01','summary':'test'}]}

    def test_scans_and_deduplicates_notifications(self):
        self.scan.scan(self.job,self.reader);self.scan.scan(self.job,self.reader)
        result=self.scan.result();self.assertEqual(result['coverage']['potential'],1);self.assertEqual(len(result['notifications']),1)
        self.scan.acknowledge('base');self.scan.scan(self.job,self.reader)
        self.assertTrue(self.scan.result()['notifications'][0]['read'])

    def test_trimmed_notification_history_does_not_repeat_unchanged_advisories(self):
        self.scan.scan(self.job,self.reader);result=self.scan.result();result['notifications']=[]
        core.save(self.scan.root/'base.json',result);self.scan.scan(self.job,self.reader)
        self.assertEqual(self.scan.result()['notifications'],[])

    def test_provider_failure_preserves_old_findings(self):
        self.scan.scan(self.job,self.reader)
        with mock.patch.object(self.scan,'cached',side_effect=TimeoutError('offline')):self.scan.scan(self.job,self.reader)
        row=self.scan.result()['rows'][0];self.assertEqual(row['status'],'error');self.assertEqual(len(row['findings']),1)
        self.assertTrue(self.scan.result()['kev_error'])

    def test_unmapped_is_not_a_clean_package(self):
        core.save(self.scan.mapping_file,{'packages':{}});self.scan.scan(self.job,self.reader)
        self.assertEqual(self.scan.result()['coverage']['unmapped'],1)

    def test_different_source_cannot_reuse_a_name_mapping(self):
        core.save(self.scan.mapping_file,{'packages':{'demo':{'ecosystem':'OSS-Fuzz','project':'demo','source_prefixes':['https://other.org/']}}})
        self.scan.scan(self.job,self.reader);self.assertEqual(self.scan.result()['rows'][0]['status'],'unmapped')

    def test_no_results_means_only_no_known_match(self):
        self.scan.scan(self.job,lambda url,data=None:{'vulnerabilities':[]} if 'cisa.gov' in url else {})
        self.assertEqual(self.scan.result()['rows'][0]['status'],'no-known-match')

    def test_sbom_is_bound_to_signed_package_hash(self):
        bom=self.scan.sbom('base');self.assertEqual(bom['bomFormat'],'CycloneDX');self.assertEqual(len(bom['components']),1)
        self.assertEqual(bom['components'][0]['hashes'][0]['content'],self.manager.baseline('base')[1]['demo']['sha256'])

    def test_security_jobs_use_existing_dedup_queue(self):
        self.update.stop()
        self.lib.submit('update-security',{'base':'base'})
        with self.assertRaisesRegex(ValueError,'같은 요청'):self.lib.submit('update-security',{'base':'base'})

    def test_ui_escapes_advisory_content(self):
        import ki2updates_views as views
        self.scan.scan(self.job,lambda url,data=None:{'vulnerabilities':[]} if 'cisa.gov' in url else {'vulns':[{'id':'CVE-2020-0001','summary':'<script>bad</script>'}]})
        body=views.security(self.manager,lambda title,body:body,{})
        self.assertNotIn('<script>bad',body);self.assertIn('&lt;script&gt;',body)

    def test_nvd_paginates_and_keeps_previous_findings_on_provider_failure(self):
        core.save(self.manager.root/'config.json',{'baseline':'base','security':{'nvd':True}})
        mapping=self.scan.mappings();mapping['packages']['demo']['cpe']='cpe:2.3:a:vendor:demo:{version}:*:*:*:*:*:*:*';core.save(self.scan.mapping_file,mapping)
        calls=[]
        def reader(url,data=None):
            if 'cisa.gov' in url:return {'vulnerabilities':[]}
            if 'osv.dev' in url:return {}
            calls.append(url);number=1 if 'startIndex=0' in url else 2
            return {'totalResults':2,'vulnerabilities':[{'cve':{'id':'CVE-2020-000'+str(number),'lastModified':'today'}}]}
        with mock.patch.object(security.time,'sleep'):self.scan.scan(self.job,reader)
        self.assertEqual(len(calls),2);self.assertEqual(len(self.scan.result()['rows'][0]['findings']),2)
        original=self.scan.cached
        def failed(identity,loader):
            if isinstance(identity,list) and identity[0]=='nvd':raise TimeoutError('NVD offline')
            return original(identity,loader)
        with mock.patch.object(self.scan,'cached',side_effect=failed):self.scan.scan(self.job,reader)
        row=self.scan.result()['rows'][0];self.assertEqual(row['status'],'error');self.assertEqual(len(row['findings']),2)


if __name__=='__main__':unittest.main()
