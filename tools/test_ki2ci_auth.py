import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode

import ki2ci_auth as auth

PASSWORD = 'Test-only long password 2026!'
ORIGIN = 'http://localhost:18090'


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100_000
        self.store = auth.AuthStore(self.tmp.name, clock=lambda: self.now)
        self.store.bootstrap()
        self.code = (self.store.root/'setup-code').read_text().strip()

    def register(self):
        self.assertTrue(self.store.setup(self.code, 'admin', PASSWORD))

    def test_setup_code_is_hashed_single_use_and_removed(self):
        self.assertNotIn(self.code.encode(), self.store.database.read_bytes())
        self.register()
        self.assertFalse((self.store.root/'setup-code').exists())
        self.assertFalse(self.store.setup(self.code, 'intruder', PASSWORD))
        self.assertTrue(self.store.verify_password('admin', PASSWORD))
        self.assertFalse(self.store.verify_password('missing', PASSWORD))
        self.assertNotIn(PASSWORD.encode(), self.store.database.read_bytes())

    def test_expired_and_rotated_setup_code(self):
        self.now += 86401
        self.assertFalse(self.store.setup(self.code, 'admin', PASSWORD))
        self.store.bootstrap(rotate=True)
        self.assertNotEqual(self.code, (self.store.root/'setup-code').read_text().strip())

    def test_session_tokens_are_hashed_and_persist_across_restart(self):
        self.register()
        token, _ = self.store.new_session('admin')
        self.assertNotIn(token.encode(), self.store.database.read_bytes())
        restarted = auth.AuthStore(self.tmp.name, clock=lambda: self.now)
        self.assertEqual(restarted.session(token)['name'], 'admin')
        restarted.revoke(token)
        self.assertIsNone(self.store.session(token))

    def test_idle_and_absolute_expiry(self):
        self.register()
        token, _ = self.store.new_session('admin')
        self.now += auth.IDLE
        self.assertIsNone(self.store.session(token))
        token, _ = self.store.new_session('admin')
        for _ in range(16):
            self.now += auth.IDLE-1
            self.assertIsNotNone(self.store.session(token))
        self.now += 16
        self.assertIsNone(self.store.session(token))

    def test_preauth_has_shorter_lifetime(self):
        token, _ = self.store.new_session()
        self.now += auth.PREAUTH
        self.assertIsNone(self.store.session(token))

    def test_rate_limit_and_window(self):
        for _ in range(5):
            self.store.limited('peer', failure=True)
        self.assertTrue(self.store.limited('peer'))
        self.assertFalse(self.store.limited('other'))
        self.now += auth.WINDOW
        self.assertFalse(self.store.limited('peer'))

    def test_password_reset_revokes_sessions(self):
        self.register()
        token, _ = self.store.new_session('admin')
        self.store.reset_password('admin', 'Another long test-only password!')
        self.assertIsNone(self.store.session(token))
        self.assertFalse(self.store.verify_password('admin', PASSWORD))

    def test_next_and_password_policy(self):
        for value in ['https://evil.test', '//evil.test', '/\\evil.test', '/\nhello', '/login', '/logout']:
            self.assertEqual(auth.safe_next(value), '/')
        self.assertEqual(auth.safe_next('/jobs/123?view=log'), '/jobs/123?view=log')
        self.assertFalse(auth.password_valid('short'))
        self.assertTrue(auth.password_valid('긴 문장 형태의 테스트용 비밀번호입니다.'))

    def test_legacy_schema_migration_preserves_password_and_session(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'auth.sqlite3'
            salt, hashed = self.store.password_material(PASSWORD)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE users(name TEXT PRIMARY KEY,salt BLOB NOT NULL,password TEXT NOT NULL)')
                db.execute('INSERT INTO users VALUES (?,?,?)', ('legacy', salt, hashed))
                db.execute('CREATE TABLE sessions(token TEXT PRIMARY KEY,csrf TEXT NOT NULL,name TEXT,created REAL NOT NULL,touched REAL NOT NULL)')
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (auth.digest('legacy-token'), 'legacy-csrf', 'legacy', self.now, self.now))
            db.close()
            migrated = auth.AuthStore(root, clock=lambda: self.now)
            self.assertTrue(migrated.verify_password('legacy', PASSWORD))
            self.assertEqual(migrated.session('legacy-token')['role'], 'admin')
            self.assertEqual(migrated.user('legacy')['must_change'], 0)
            self.assertEqual(auth.AuthStore(root).user('legacy')['revision'], 1)
            with migrated.connect() as db:
                self.assertEqual(db.execute('SELECT salt,password FROM users').fetchone(), (salt, hashed))

    def add_user(self, name='reader', role='viewer'):
        return self.store.create_user('admin', name, role)

    def test_new_user_temporary_password_and_case_duplicate_policy(self):
        self.register()
        password = self.add_user()
        self.assertTrue(self.store.verify_password('reader', password))
        self.assertEqual(self.store.user('reader')['must_change'], 1)
        self.assertNotIn(password.encode(), self.store.database.read_bytes())
        for name in ['READER', 'a/b', '..', 'new', '<script>', 'x'*65]:
            with self.assertRaises(auth.AccountError):
                self.add_user(name)
        self.assertNotIn(password, str(self.store.account_events()))

    def test_user_changes_revoke_only_target_sessions_and_prevent_stale_write(self):
        self.register(); self.add_user()
        admin, _ = self.store.new_session('admin'); reader, _ = self.store.new_session('reader')
        self.store.manage_user('admin', 'reader', 1, 'update', 'operator', 1)
        self.assertIsNone(self.store.session(reader)); self.assertIsNotNone(self.store.session(admin))
        with self.assertRaises(auth.AccountError):
            self.store.manage_user('admin', 'reader', 1, 'update', 'viewer', 0)
        self.assertEqual(self.store.user('reader')['role'], 'operator')
        self.store.manage_user('admin', 'reader', 2, 'update', 'operator', 0)
        self.assertFalse(self.store.verify_password('reader', 'wrong'))
        with self.assertRaises(auth.AccountError):self.store.new_session('reader')

    def test_self_lock_and_pending_admin_cannot_manage_accounts(self):
        self.register()
        for action, role, enabled in [('update', 'viewer', 1), ('update', 'admin', 0), ('reset', None, None)]:
            with self.assertRaises(auth.AccountError):
                self.store.manage_user('admin', 'admin', 1, action, role, enabled)
        self.add_user('pending', 'admin')
        with self.assertRaises(auth.AccountError):
            self.store.create_user('pending', 'third', 'admin')
        self.store.manage_user('admin', 'pending', 1, 'update', 'viewer', 0)
        self.assertEqual(self.store.user('admin')['enabled'], 1)

    def test_password_change_revokes_sessions_and_reset_forces_change(self):
        self.register(); temporary = self.add_user()
        target, _ = self.store.new_session('reader'); admin, _ = self.store.new_session('admin')
        self.store.change_password('reader', temporary, PASSWORD)
        self.assertIsNone(self.store.session(target)); self.assertIsNotNone(self.store.session(admin))
        self.assertFalse(self.store.user('reader')['must_change'])
        reset = self.store.manage_user('admin', 'reader', 2, 'reset')
        self.assertTrue(self.store.user('reader')['must_change'])
        self.assertTrue(self.store.verify_password('reader', reset))
        self.assertFalse(self.store.verify_password('reader', PASSWORD))
        self.store.reset_password('reader', PASSWORD)
        self.assertIsNotNone(self.store.session(admin))

    def test_concurrent_cross_demotion_preserves_one_admin(self):
        self.register(); temporary = self.add_user('second', 'admin')
        self.store.change_password('second', temporary, PASSWORD)
        barrier = threading.Barrier(2); results = []
        def demote(actor, target):
            revision = self.store.user(target)['revision']; barrier.wait()
            try:
                self.store.manage_user(actor, target, revision, 'update', 'viewer', 1)
                results.append('ok')
            except auth.AccountError:
                results.append('blocked')
        threads = [threading.Thread(target=demote, args=pair) for pair in [('admin','second'),('second','admin')]]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertCountEqual(results, ['ok', 'blocked'])
        self.assertEqual(sum(u['role']=='admin' and u['enabled'] and not u['must_change'] for u in self.store.users()), 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hits = []
        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.hits.append((self.path, dict(self.headers)))
                body = b'KI2-PAYLOAD' if self.path.endswith('.ki2') else (b'{"status":"running"}' if self.path.startswith('/api/') else b'<html><head></head><body><h1>Builds</h1><form method="post" action="/jobs"><button>Queue</button></form></body></html>')
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream' if self.path.endswith('.ki2') else ('application/json' if self.path.startswith('/api/') else 'text/html; charset=utf-8'))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                cls.hits.append((self.path, dict(self.headers)))
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(303); self.send_header('Location', '/jobs/new'); self.end_headers()
            def log_message(self, *args):
                pass
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.backend_thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.backend_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown(); cls.backend.server_close(); cls.backend_thread.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = auth.AuthStore(self.tmp.name)
        self.store.bootstrap()
        self.code = (self.store.root/'setup-code').read_text().strip()
        self.store.setup(self.code, 'admin', PASSWORD)
        handler = auth.make_handler(self.store, f'http://127.0.0.1:{self.backend.server_port}', [ORIGIN])
        handler.log_message = lambda *args: None
        self.server = auth.AuthHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''
        self.hits.clear()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        h = {'Host': 'localhost:18090'}
        if self.cookie:
            h['Cookie'] = self.cookie
        body = None
        if data is not None:
            body = urlencode(data).encode()
            h.update({'Content-Type': 'application/x-www-form-urlencoded', 'Origin': ORIGIN})
        h.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse(); payload = r.read(); response_headers = dict(r.getheaders()); status = r.status
        conn.close()
        if 'Set-Cookie' in response_headers:
            self.cookie = response_headers['Set-Cookie'].split(';')[0]
        return status, response_headers, payload

    def csrf(self):
        status, _, body = self.request('GET', '/login')
        self.assertEqual(status, 200)
        return re.search(rb'name=[\'"]_csrf[\'"] value=[\'"]([^\'"]+)', body)[1].decode()

    def login(self, next_path='/'):
        csrf = self.csrf()
        preauth = self.cookie
        r = self.request('POST', '/login', {'_csrf': csrf, 'username': 'admin', 'password': PASSWORD, 'next': next_path})
        self.assertEqual(r[0], 303)
        self.assertNotEqual(preauth, self.cookie)
        return r

    def test_all_reads_and_downloads_require_login(self):
        for path in ['/jobs', '/packages', '/profiles', '/jobs/123/artifacts/example.ki2', '/build-console.js', '/auth/session.js', '/versions', '/iso-build', '/library/files/binary/'+('a'*64)]:
            self.assertEqual(self.request('GET', path)[0], 303)
        for path in ['/api/jobs', '/api/jobs/123/log', '/api/packages', '/api/releases']:
            self.assertEqual(self.request('GET', path)[0], 401)
        self.assertEqual(self.hits, [])

    def test_login_rotates_session_and_preserves_deep_link(self):
        status, headers, _ = self.login('/jobs/current')
        self.assertEqual(headers['Location'], '/jobs/current')
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        self.assertEqual(self.request('GET', '/api/jobs')[0], 200)
        self.assertNotIn('Cookie', self.hits[-1][1])

    def test_forms_receive_csrf_and_logout_control(self):
        self.login()
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertEqual(len(re.findall(rb'name=[\'\"]_csrf[\'\"]', body)), 2)
        self.assertIn('로그아웃'.encode(), body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Referrer-Policy'], 'same-origin')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_csrf_and_origin_block_mutations_before_backend(self):
        self.login()
        for headers, token in [({}, ''), ({}, '한글'), ({'Origin': 'http://evil.test'}, 'anything'), ({'Origin': ''}, 'anything')]:
            self.assertEqual(self.request('POST', '/jobs', {'_csrf': token, 'pipeline': 'smoke'}, headers)[0], 403)
        self.assertEqual(self.hits, [])

    def test_authenticated_form_post_reaches_backend(self):
        self.login()
        token = self.cookie.split('=', 1)[1]
        csrf = self.store.session(token)['csrf']
        self.assertEqual(self.request('POST', '/jobs', {'_csrf': csrf, 'pipeline': 'smoke'})[0], 303)
        self.assertEqual(self.hits[-1][0], '/jobs')

    def test_logout_revokes_cookie_and_download_access(self):
        self.login(); old = self.cookie
        csrf = self.store.session(self.cookie.split('=', 1)[1])['csrf']
        self.assertEqual(self.request('POST', '/logout', {'_csrf': csrf})[0], 303)
        self.cookie = old
        self.assertEqual(self.request('GET', '/jobs/123/artifacts/example.ki2')[0], 303)

    def test_binary_stream_is_not_transformed(self):
        self.login()
        status, headers, payload = self.request('GET', '/jobs/123/artifacts/example.ki2')
        self.assertEqual(status, 200); self.assertEqual(payload, b'KI2-PAYLOAD')
        self.assertEqual(headers['Content-Length'], str(len(payload)))

    def test_theme_assets_are_available_for_login_without_exposing_worker(self):
        for path, kind in [('/build-theme.css', 'text/css'), ('/build-theme.js', 'text/javascript')]:
            status, headers, body = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith(kind))
            self.assertTrue(body)
            self.assertEqual(self.request('GET', path, headers={'Host':'evil.test'})[0], 400)
        self.assertEqual(self.hits, [])
        self.assertEqual(self.request('GET','/ki2ci_theme.py')[0],303)

    def test_wrong_password_and_rate_limit(self):
        csrf = self.csrf()
        for _ in range(5):
            self.assertEqual(self.request('POST', '/login', {'_csrf': csrf, 'username': 'admin', 'password': 'incorrect'})[0], 401)
        self.assertEqual(self.request('POST', '/login', {'_csrf': csrf, 'username': 'admin', 'password': PASSWORD})[0], 429)

    def test_host_and_redirect_injection(self):
        self.assertEqual(self.request('GET', '/login', headers={'Host': 'evil.test'})[0], 400)
        self.assertEqual(self.request('GET', '//evil.test/')[0], 400)
        self.assertEqual(self.login('//evil.test/')[1]['Location'], '/')

    def test_setup_requires_code_and_is_one_time(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM users')
        self.store.bootstrap()
        code = (self.store.root/'setup-code').read_text().strip()
        status, _, body = self.request('GET', '/setup')
        csrf = re.search(rb'name=[\'"]_csrf[\'"] value=[\'"]([^\'"]+)', body)[1].decode()
        form = {'_csrf': csrf, 'code': 'bad', 'username': 'admin', 'password': PASSWORD, 'confirm': PASSWORD}
        self.assertEqual(self.request('POST', '/setup', form)[0], 401)
        form['code'] = code
        self.assertEqual(self.request('POST', '/setup', form)[0], 303)
        self.assertTrue(self.store.configured())
        self.assertFalse((self.store.root/'setup-code').exists())

    def test_expired_session_denies_read_and_post(self):
        self.login()
        self.store.clock = lambda: 10**12
        self.assertEqual(self.request('GET', '/api/jobs')[0], 401)
        self.assertEqual(self.request('POST', '/jobs', {'_csrf': 'stale'})[0], 401)

    def test_upstream_failure_returns_502(self):
        self.login()
        with socket.socket() as unused:
            unused.bind(('127.0.0.1', 0))
            port = unused.getsockname()[1]
        handler = auth.make_handler(self.store, f'http://127.0.0.1:{port}', [ORIGIN])
        handler.log_message = lambda *args: None
        self.server.RequestHandlerClass = handler
        self.assertEqual(self.request('GET', '/')[0], 502)

    def test_llm_settings_require_admin_while_operator_may_request_drafts(self):
        _,session=self.as_user('llm-builder','operator')
        form={'_csrf':session['csrf'],'endpoint':'http://127.0.0.1:8080/v1','model':'kiki-ops','enabled':'yes'}
        self.assertEqual(self.request('POST','/assistant/settings',form)[0],403);self.assertEqual(self.hits,[])
        self.assertEqual(self.request('POST','/assistant/draft',{'_csrf':session['csrf'],'description':'read-only draft'})[0],303)
        self.assertEqual(self.hits[-1][0],'/assistant/draft')

    def test_arbitrary_upstream_and_plaintext_public_origin_rejected(self):
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://evil.test', [ORIGIN])
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://127.0.0.1:8091', ['http://public.example:8092'])
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://127.0.0.1:8091', [ORIGIN, 'https://localhost:18090'])

    def test_public_repository_only_exposes_read_only_prefix_without_credentials(self):
        destination=f'http://127.0.0.1:{self.backend.server_port}'
        handler=auth.make_handler(self.store,destination,[ORIGIN],repository_upstream=destination)
        handler.log_message=lambda *args:None
        self.server.RequestHandlerClass=handler
        status,headers,body=self.request('GET','/ki2/candidate/packages/demo.ki2',headers={'Cookie':'secret=private','Authorization':'Bearer private'})
        self.assertEqual(status,200)
        self.assertEqual(body,b'KI2-PAYLOAD')
        self.assertNotIn('Set-Cookie',headers)
        self.assertNotIn('Cookie',self.hits[-1][1])
        self.assertNotIn('Authorization',self.hits[-1][1])
        self.assertEqual(self.request('GET','/ki2/candidate/packages/gtk+-3-3.24.52-1.x86_64.ki2')[0],200)
        for path in ['/ki2/../api/jobs','/ki2/%2e%2e/api/jobs','/ki2/candidate/repo/index.x86_64.json?next=/api/jobs']:
            self.assertEqual(self.request('GET',path)[0],404)
        self.assertEqual(self.request('POST','/ki2/candidate/repo/index.x86_64.json',{'anything':'yes'})[0],405)
        self.assertEqual(self.request('GET','/api/jobs')[0],401)
        self.assertEqual(self.request('GET','/versions')[0],303)

    def test_public_repository_cannot_target_external_host(self):
        with self.assertRaises(ValueError):
            auth.make_handler(self.store,'http://127.0.0.1:8091',[ORIGIN],repository_upstream='http://example.com')

    def web(self):
        handler=auth.make_handler(self.store,f'http://127.0.0.1:{self.backend.server_port}',
                                 [ORIGIN,'https://build.example'])
        handler.log_message=lambda *args:None
        self.server.RequestHandlerClass=handler

    def test_container_gateway_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://10.0.2.2:8091', [ORIGIN])
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://127.0.0.1:8091', [ORIGIN],
                              release_upstream='http://10.0.2.2:8094')

    def test_container_gateway_accepts_only_the_pinned_address(self):
        auth.make_handler(self.store, 'http://10.0.2.2:8091', [ORIGIN],
                          release_upstream='http://10.0.2.2:8094', host_gateway='10.0.2.2')
        for address in ['10.0.2.3', '10.250.254.229', 'host.containers.internal']:
            with self.assertRaises(ValueError):
                auth.make_handler(self.store, 'http://10.0.2.2:8091', [ORIGIN], host_gateway=address)
        with self.assertRaises(ValueError):
            auth.make_handler(self.store, 'http://10.0.2.3:8091', [ORIGIN], host_gateway='10.0.2.2')

    def test_public_landing_and_health_need_no_session(self):
        self.web()
        for method,path in [('GET','/healthz'),('HEAD','/healthz'),('GET','/'),('HEAD','/'),('OPTIONS','/'),('OPTIONS','*')]:
            status,headers,body=self.request(method,path,headers={'Host':'10.250.254.229:8092'})
            self.assertEqual(status,200,(method,path))
            self.assertNotIn('Set-Cookie',headers)
            if method=='HEAD':self.assertEqual(body,b'')
            if method=='GET' and path=='/':self.assertIn(b'href="/login"',body)
        self.assertEqual(self.hits,[])

    def test_one_listener_keeps_public_and_tunnel_cookie_policies_separate(self):
        self.web()
        status,headers,_=self.request('GET','/login',headers={'Host':'build.example'})
        self.assertEqual(status,200);self.assertIn('; Secure',headers['Set-Cookie'])
        self.cookie=''
        status,headers,_=self.request('GET','/login')
        self.assertEqual(status,200);self.assertNotIn('; Secure',headers['Set-Cookie'])

    def test_web_blocks_anonymous_data_and_invalid_host(self):
        self.web()
        self.assertEqual(self.request('GET','/api/jobs',headers={'Host':'build.example'})[0],401)
        self.assertEqual(self.request('GET','/login',headers={'Host':'evil.test'})[0],400)
        self.assertEqual(self.request('POST','/jobs',{'_csrf':'fake'},headers={'Host':'build.example'})[0],401)
        self.assertEqual(self.hits,[])

    def test_public_login_and_actions_keep_origin_and_csrf_validation(self):
        self.web();outer={'Host':'build.example'}
        _,_,body=self.request('GET','/login',headers=outer)
        csrf=re.search(rb'name=[\'"]_csrf[\'"] value=[\'"]([^\'"]+)',body)[1].decode()
        headers=dict(outer,Origin='https://build.example')
        self.assertEqual(self.request('POST','/login',{'_csrf':csrf,'username':'admin','password':PASSWORD},headers)[0],303)
        self.assertEqual(self.request('POST','/jobs',{'_csrf':'wrong'},headers)[0],403)
        csrf=self.store.session(self.cookie.split('=',1)[1])['csrf']
        self.assertEqual(self.request('POST','/jobs',{'_csrf':csrf,'pipeline':'smoke'},headers)[0],303)
        self.assertEqual(self.hits[-1][1]['Origin'],'http://127.0.0.1:18090')
        self.assertEqual(self.request('POST','/jobs',{'_csrf':csrf},dict(outer,Origin=ORIGIN))[0],403)
        self.assertEqual(self.request('GET','/',headers=outer)[0],200)
        self.assertEqual(self.hits[-1][0],'/')
        self.assertEqual(self.hits[-1][1]['Host'],'127.0.0.1:18090')

    def test_forwarded_headers_cannot_change_cookie_security(self):
        self.web()
        for scheme in ['http','https','invalid']:
            self.cookie=''
            status,headers,_=self.request('GET','/login',headers={
                'Host':'build.example','X-Forwarded-Proto':scheme,'X-Forwarded-For':'127.0.0.1'})
            self.assertEqual(status,200);self.assertIn('; Secure',headers['Set-Cookie'])
        self.cookie=''
        status,headers,_=self.request('GET','/login',headers={'X-Forwarded-Proto':'https'})
        self.assertEqual(status,200);self.assertNotIn('; Secure',headers['Set-Cookie'])

    def as_user(self, name, role, ready=True):
        temporary = self.store.create_user('admin', name, role)
        if ready:self.store.change_password(name, temporary, PASSWORD)
        token, session = self.store.new_session(name)
        self.cookie = auth.COOKIE+'='+token
        return temporary, session

    def test_viewer_reads_downloads_and_denies_all_worker_mutations(self):
        _, session = self.as_user('reader', 'viewer')
        self.assertEqual(self.request('GET', '/jobs')[0], 200)
        self.assertEqual(self.request('GET', '/jobs/a.ki2')[2], b'KI2-PAYLOAD')
        self.hits.clear()
        for path in ['/package-groups/save', '/package-groups/restore', '/packages/metadata', '/jobs', '/api/jobs', '/kernel-build', '/git/sync', '/releases/register', '/releases/r1/manage', '/iso-build/create', '/library/import',
                     '/updates/check','/updates/create','/updates/security/check','/updates/security/acknowledge','/updates/'+('a'*32)+'/build','/updates/'+('a'*32)+'/validate',
                     '/updates/'+('a'*32)+'/accept-validation','/updates/'+('a'*32)+'/promote']:
            self.assertEqual(self.request('POST', path, {'_csrf':session['csrf']})[0], 403, path)
        self.assertEqual(self.hits, [])
        self.assertIn(b'<fieldset disabled', self.request('GET', '/jobs')[2])
        self.assertEqual(self.request('GET', '/users')[0], 403)

    def test_operator_queues_build_but_cannot_manage_accounts(self):
        _, session = self.as_user('builder', 'operator')
        self.assertEqual(self.request('POST', '/jobs', {'_csrf':session['csrf']})[0], 303)
        self.assertEqual(self.request('POST', '/git/sync', {'_csrf':session['csrf']})[0], 303)
        self.hits.clear()
        self.assertEqual(self.request('POST', '/users/create', {'_csrf':session['csrf'], 'username':'evil', 'role':'admin'})[0], 403)
        self.assertEqual(self.request('GET', '/users/admin')[0], 403)
        self.assertEqual(self.hits, [])
        self.assertIsNone(self.store.user('evil'))

    def test_access_revoked_during_form_read_never_reaches_worker(self):
        _, session = self.as_user('builder', 'operator')
        original = self.server.RequestHandlerClass.form
        store = self.store
        def revoked_form(handler):
            result = original(handler)
            store.manage_user('admin', 'builder', store.user('builder')['revision'], 'update', 'viewer', 1)
            return result
        self.server.RequestHandlerClass.form = revoked_form
        self.assertEqual(self.request('POST', '/jobs', {'_csrf':session['csrf']})[0], 401)
        self.assertEqual(self.hits, [])

    def test_forced_change_cannot_reach_console_until_own_password_changed(self):
        temporary, session = self.as_user('reader', 'viewer', ready=False)
        self.assertEqual(self.request('GET', '/jobs')[1]['Location'], '/account')
        self.assertEqual(self.request('POST', '/jobs', {'_csrf':session['csrf']})[0], 403)
        self.assertEqual(self.request('GET', '/account')[0], 200)
        form = {'_csrf':session['csrf'], 'current':temporary, 'password':PASSWORD, 'confirm':PASSWORD}
        response = self.request('POST', '/account/password', form)
        self.assertEqual(response[0], 303)
        self.assertFalse(self.store.user('reader')['must_change'])
        self.assertIn('Max-Age=0', response[1]['Set-Cookie'])
        self.assertEqual(self.request('GET', '/jobs')[0], 303)
        self.assertEqual(self.hits, [])

    def test_admin_creation_one_time_secret_reset_disable_and_audit(self):
        self.login(); session = self.store.session(self.cookie.split('=',1)[1])
        self.assertEqual(self.request('GET', '/users')[0], 200)
        self.assertEqual(self.request('GET', '/users/new')[0], 200)
        status, headers, body = self.request('POST', '/users/create', {'_csrf':session['csrf'], 'username':'reader', 'role':'viewer'})
        self.assertEqual(status, 200); self.assertEqual(headers['Cache-Control'], 'no-store')
        secret = re.search(rb"aria-label='[^']+'>([^<]+)</p>", body)[1].decode()
        self.assertTrue(self.store.verify_password('reader', secret))
        self.assertNotIn(secret.encode(), self.request('GET', '/users/reader')[2])
        self.assertNotIn(secret.encode(), self.request('GET', '/users')[2])
        self.assertEqual(self.request('POST', '/users/reader/manage', {'_csrf':session['csrf'], 'revision':'1','action':'reset'})[0],400)
        self.assertEqual(self.request('POST', '/users/reader/manage', {'_csrf':session['csrf'], 'revision':'1','action':'update','role':'viewer'})[0],303)
        self.assertFalse(self.store.verify_password('reader', secret))
        self.assertEqual(self.request('POST', '/users/admin/manage', {'_csrf':session['csrf'], 'revision':'1','action':'update','role':'viewer','enabled':'1'})[0],400)
        self.assertEqual(self.store.user('admin')['role'], 'admin')
        self.assertEqual([r[3] for r in self.store.account_events()], ['updated','created'])

    def test_admin_operations_require_origin_and_csrf_and_user_routes_never_proxy(self):
        self.login(); session = self.store.session(self.cookie.split('=',1)[1])
        form = {'_csrf':session['csrf'], 'username':'reader', 'role':'viewer'}
        self.assertEqual(self.request('POST','/users/create',form,{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/users/create',dict(form,_csrf='bad'))[0],403)
        self.assertEqual(self.request('GET','/users/does-not-exist')[0],404)
        self.assertEqual(self.request('POST','/users/not-a-route',form)[0],404)
        self.assertEqual(self.hits,[])

    def test_invalid_current_password_does_not_change_or_revoke_account(self):
        self.login(); session = self.store.session(self.cookie.split('=',1)[1])
        form = {'_csrf':session['csrf'],'current':'incorrect','password':'Different long password 2026!', 'confirm':'Different long password 2026!'}
        self.assertEqual(self.request('POST','/account/password',form)[0],400)
        self.assertTrue(self.store.verify_password('admin',PASSWORD))
        self.assertEqual(self.request('GET','/users')[0],200)


if __name__ == '__main__':
    unittest.main()
