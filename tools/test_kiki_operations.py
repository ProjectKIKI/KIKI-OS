import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import importlib.machinery
import contextlib
import io

SOURCE=Path(__file__).resolve().parents[1]/'distro/sources/kiki-operations/usr/libexec/kiki-operations-backend.py'
spec=importlib.util.spec_from_file_location('operations',SOURCE)
ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)


class OperationsDataTests(unittest.TestCase):
    def test_cpu_guest_not_counted_twice_and_regression_rejected(self):
        before=ops.cpu_counters('cpu 10 0 10 80 0 0 0 0 8 0\n')
        after=ops.cpu_counters('cpu 20 0 20 160 0 0 0 0 16 0\n')
        self.assertEqual(ops.cpu_percent(before,after),20.0)
        with self.assertRaises(ValueError):ops.cpu_percent(after,before)

    def test_available_memory_includes_reclaimable_cache(self):
        self.assertEqual(ops.memory('MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 750 kB')['percent'],25.0)
        with self.assertRaises(KeyError):ops.memory('MemTotal: 1000 kB')

    def test_service_failure_sorted_without_description_splitting(self):
        rows=ops.services('sshd.service loaded active running OpenSSH server daemon\nexample@a.service loaded failed failed Example instance\n')
        self.assertEqual(rows[0]['unit'],'example@a.service')
        self.assertEqual(rows[1]['description'],'OpenSSH server daemon')
        with self.assertRaises(ValueError):ops.services('invalid service output')

    def test_runtime_never_scans_package_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            proc=Path(d);(proc/'stat').write_text('cpu 10 0 10 80 0 0 0 0\n');(proc/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 500 kB\n')
            calls=[]
            def run(argv):
                calls.append(argv);return 'sshd.service loaded active running OpenSSH\n'
            def wait(seconds):
                self.assertLess(seconds,0.5);(proc/'stat').write_text('cpu 20 0 20 160 0 0 0 0\n')
            disk=types.SimpleNamespace(f_blocks=100,f_bfree=40,f_bavail=35,f_frsize=4096)
            result=ops.runtime(proc=proc,runner=run,sleep=wait,statvfs=lambda _:disk)
            self.assertEqual(result['cpu_percent'],20.0);self.assertEqual(result['failed_count'],0)
            self.assertEqual(result['warnings'],[])
            self.assertEqual([c[0] for c in calls],['/usr/bin/systemctl'])

    def test_unavailable_data_is_unknown_not_healthy_zero(self):
        with tempfile.TemporaryDirectory() as d:
            def fail(*args):raise RuntimeError('D-Bus unavailable')
            def diskfail(_):raise OSError('No filesystem')
            result=ops.runtime(proc=Path(d),runner=fail,sleep=lambda _:None,statvfs=diskfail)
            self.assertIsNone(result['failed_count']);self.assertIsNone(result['services'])
            self.assertIsNone(result['cpu_percent']);self.assertEqual(len(result['warnings']),4)

    def test_summary_validates_existing_admin_schema(self):
        good=json.dumps(dict(ok=True,schema='kiki-admin-v1',installed=[{},{}],warnings=[]))
        self.assertEqual(ops.summary(lambda *a,**kw:good)['installed_count'],2)
        with self.assertRaises(ValueError):ops.summary(lambda *a,**kw:'{"ok":true,"schema":"other"}')


class ServiceConnectionsTests(unittest.TestCase):
    def test_unit_rejected_before_any_command(self):
        def forbidden(*args,**kw):self.fail('Invalid target reached executor')
        for unit in ['--help.service','a.service\n','a;id.service','../x.service','a.service b.service',None]:
            with self.subTest(unit=unit),self.assertRaises(ValueError):ops.service_logs(unit,forbidden)

    def test_user_logs_preserve_scope_notice_and_exact_target(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args);return json.dumps(dict(ok=True,unit='a.service',output='-- No entries --',notice='Restricted journal access'))
        result=ops.service_logs('a.service',run)
        self.assertEqual(result['scope'],'user');self.assertEqual(result['notice'],'Restricted journal access')
        self.assertEqual(calls,[['/usr/bin/kiki-adminctl','logs','a.service']])
        with self.assertRaises(ValueError):ops.service_logs('b.service',run)

    def test_only_existing_system_log_plan_contract_is_accepted(self):
        good=dict(ok=True,action='system-logs',target='a.service',token='a'*64,details='fixed journal query')
        calls=[]
        def run(args,**kw):calls.append(args);return json.dumps(good)
        self.assertEqual(ops.system_log_plan('a.service',run)['token'],'a'*64)
        self.assertEqual(calls[0],['/usr/bin/kiki-adminctl','plan','system-logs','a.service'])
        for change in [dict(action='restart'),dict(target='b.service'),dict(token='bad')]:
            with self.assertRaises(ValueError):ops.system_log_plan('a.service',lambda *a,**kw:json.dumps({**good,**change}))

    def test_terminal_uses_fixed_argv_without_shell_or_elevation(self):
        for mode in ['status','logs']:
            p=ops.terminal_plan(mode,r'example@a\x2db.service')
            self.assertEqual(p['argv'][:3],['/usr/bin/kgx','--','/usr/libexec/kiki-operations-console'])
            self.assertEqual(p['argv'][3:],[mode,r'example@a\x2db.service'])
            self.assertNotIn('sudo',p['inspection_argv']);self.assertNotIn('pkexec',p['inspection_argv']);self.assertNotIn('sh',p['inspection_argv'])
        self.assertEqual(ops.inspection_argv('status','a.service'),['/usr/bin/systemctl','--no-pager','--full','status','--','a.service'])
        with self.assertRaises(ValueError):ops.terminal_plan('shell','a.service')

    def test_console_retains_result_until_acknowledged(self):
        path=SOURCE.with_name('kiki-operations-console')
        loader=importlib.machinery.SourceFileLoader('console',str(path));spec=importlib.util.spec_from_loader(loader.name,loader)
        console=importlib.util.module_from_spec(spec);loader.exec_module(console)
        calls=[];ack=[]
        def run(argv,**kw):calls.append(argv);return types.SimpleNamespace(returncode=3)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code=console.main(['status','a.service'],runner=run,contract={'inspection_argv':ops.inspection_argv},pause=lambda:ack.append(True))
        self.assertEqual(code,0);self.assertEqual(ack,[True]);self.assertIn('종료 코드: 3',output.getvalue())
        self.assertEqual(calls,[ops.inspection_argv('status','a.service')])

    def test_existing_json_error_is_not_lost(self):
        with patch.object(ops.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='{"ok":false,"error":"restricted"}',stderr='')):
            with self.assertRaisesRegex(RuntimeError,'restricted'):ops.command(['/usr/bin/kiki-adminctl','logs','a.service'])


class IncidentConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.config=Path(self.directory.name)/'incident.json'
        self.config.write_text(json.dumps(dict(url='https://incident-ai.lab.terminal-lab.kr/')))

    def plan(self, logs='',scope='none', **extra):
        return ops.incident_plan('example.service',dict(hostname='candidate-only',scope=scope,logs=logs,observed_at='2026-11-07T12:00:00+09:00',**extra),self.config)

    def test_draft_uses_exact_analysis_route_without_putting_logs_in_url(self):
        result=self.plan('RELATED_EVENT',scope='system')
        self.assertEqual(result['url'],'https://incident-ai.lab.terminal-lab.kr/#ask')
        self.assertIn('example.service',result['draft']);self.assertIn('Polkit',result['draft'])
        self.assertIn('RELATED_EVENT',result['draft']);self.assertNotIn('RELATED_EVENT',result['url'])
        self.assertTrue(result['requires_web_paste']);self.assertEqual(result['transport'],'clipboard-and-browser')

    def test_token_cookie_url_password_and_truncated_private_key_are_masked(self):
        raw='password=hunter2\nAuthorization: Bearer top-secret\nCookie: session=abc\nurl=https://user:password@host/\n-----BEGIN PRIVATE KEY-----\nprivate-material'
        result=self.plan(raw,scope='user')
        for secret in ['hunter2','top-secret','session=abc','user:password','private-material']:
            self.assertNotIn(secret,result['draft'])
        self.assertGreaterEqual(result['redactions'],5)

    def test_web_utf16_limit_retains_recent_events_and_marks_partial_line(self):
        result=self.plan('old-line\n'+'😀'*2000+'RECENT_END',scope='user')
        self.assertLessEqual(len(result['draft'].encode('utf-16-le'))//2,1000)
        self.assertTrue(result['draft'].endswith('RECENT_END'));self.assertTrue(result['truncated'])
        self.assertIn('[앞부분 생략]',result['draft'])

    def test_empty_user_journal_does_not_claim_full_system_is_healthy(self):
        result=self.plan('-- No entries --',scope='user')
        self.assertEqual(result['included_lines'],0);self.assertIn('현재 사용자에게 보이는 로그',result['draft'])
        self.assertIn('로그 원문은 포함하지 않았습니다',result['draft'])
        self.assertTrue(self.plan(scope='none',source_truncated=True)['truncated'])

    def test_invalid_scope_unit_and_unbounded_context_are_rejected(self):
        for logs,scope in [('secret','none'),('','root'),('x'*65537,'user')]:
            with self.subTest(scope=scope),self.assertRaises(ValueError):self.plan(logs,scope=scope)
        with self.assertRaises(ValueError):ops.incident_plan('--bad.service',{},self.config)

    def test_connection_config_cannot_redirect_data_to_other_origins(self):
        for url in ['http://incident-ai.lab.terminal-lab.kr/','https://other.example/',
                    'https://user:pw@incident-ai.lab.terminal-lab.kr/','https://incident-ai.lab.terminal-lab.kr/?token=bad',
                    'https://incident-ai.lab.terminal-lab.kr:8443/','https://incident-ai.lab.terminal-lab.kr/other']:
            self.config.write_text(json.dumps(dict(url=url)))
            with self.subTest(url=url),self.assertRaises(ValueError):self.plan()
        self.config.unlink()
        with self.assertRaises(FileNotFoundError):self.plan()


if __name__=='__main__':unittest.main()
