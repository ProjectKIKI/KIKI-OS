#!/usr/bin/env python3
"""Session-authenticated front door for the existing, loopback-only builder.

Run independently of the build worker so authentication deployments cannot
interrupt a compiler. No credentials, cookies or setup codes reach the worker.
"""
from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import hmac
import html
import http.client
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ki2users import AccountError, ROLES, UserAccounts

COOKIE = 'kiki_build_session'
ITERATIONS = 600_000
IDLE = 30 * 60
LIFETIME = 8 * 60 * 60
PREAUTH = 20 * 60
WINDOW = 15 * 60
FORM_LIMIT = 32768
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'set-cookie', 'content-length'}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'; connect-src 'self'")


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS).hex()


def password_valid(password):
    return 15 <= len(password) <= 1024 and '\x00' not in password


def safe_next(value):
    if not value.startswith('/') or value.startswith('//') or any(c in value for c in '\\\r\n\x00'):
        return '/'
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path in {'/login', '/logout', '/setup'}:
        return '/'
    return value


class AuthStore(UserAccounts):
    hash_password = staticmethod(password_hash)
    password_policy = staticmethod(password_valid)

    @staticmethod
    def password_material(password):
        salt = secrets.token_bytes(32)
        return salt, password_hash(password, salt)

    def __init__(self, directory, clock=time.time):
        self.root = Path(directory)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.database = self.root / 'auth.sqlite3'
        self.clock = clock
        self.audit_lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users
                  (name TEXT PRIMARY KEY, salt BLOB NOT NULL, password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions
                  (token TEXT PRIMARY KEY, csrf TEXT NOT NULL, name TEXT,
                   created REAL NOT NULL, touched REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (peer TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            self.migrate_users(db)
        self.database.chmod(0o600)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def configured(self):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None

    def bootstrap(self, rotate=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                return False
            codefile = self.root / 'setup-code'
            row = db.execute("SELECT value FROM settings WHERE key='setup_expires'").fetchone()
            if not rotate and row and float(row[0]) > self.clock() and codefile.is_file():
                return True
            code = secrets.token_urlsafe(32)
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',
                          [('setup_hash', digest(code)), ('setup_expires', str(self.clock() + 86400))])
            fd = os.open(codefile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(code + '\n')
            codefile.chmod(0o600)
            return True

    def setup(self, code, name, password):
        salt = secrets.token_bytes(32)
        hashed = password_hash(password, salt)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            settings = dict(db.execute('SELECT key,value FROM settings'))
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                return False
            if (not hmac.compare_digest(settings.get('setup_hash', ''), digest(code))
                    or float(settings.get('setup_expires', '0')) <= self.clock()):
                return False
            db.execute('INSERT INTO users(name,salt,password,created_at,updated_at) VALUES (?,?,?,?,?)', (name, salt, hashed, self.clock(), self.clock()))
            db.execute('DELETE FROM settings')
            db.execute('DELETE FROM sessions')
        (self.root / 'setup-code').unlink(missing_ok=True)
        self.audit('admin_registered', name)
        return True

    def verify_password(self, name, password):
        with self.connect() as db:
            row = db.execute('SELECT salt,password,enabled FROM users WHERE name=?', (name,)).fetchone()
        # Unknown users perform the same KDF, and return the same error.
        actual = password_hash(password, row[0] if row else b'\0' * 32)
        return bool(row and row[2] and hmac.compare_digest(actual, row[1]))

    def new_session(self, name=None):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock()
        with self.connect() as db:
            user = self._account(db, name) if name else None
            if name and (not user or not user['enabled'] or user['role'] not in ROLES):
                raise AccountError('사용 가능한 계정이 아닙니다.')
            db.execute('DELETE FROM sessions WHERE created < ? OR touched < ?', (now-LIFETIME, now-IDLE))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (digest(token), csrf, name, now, now))
        return token, dict(user or {}, csrf=csrf, name=name)

    def session(self, token):
        with self.connect() as db:
            row = db.execute('SELECT csrf,name,created,touched FROM sessions WHERE token=?', (digest(token),)).fetchone()
            if not row:
                return None
            csrf, name, created, touched = row
            now = self.clock()
            if now-created >= (LIFETIME if name else PREAUTH) or now-touched >= IDLE:
                db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))
                return None
            user = self._account(db, name) if name else None
            if name and (not user or not user['enabled'] or user['role'] not in ROLES):
                db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))
                return None
            db.execute('UPDATE sessions SET touched=? WHERE token=?', (now, digest(token)))
            return dict(user or {}, csrf=csrf, name=name)

    def revoke(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def limited(self, peer, failure=False):
        now = self.clock()
        with self.connect() as db:
            db.execute('DELETE FROM attempts WHERE at<=?', (now-WINDOW,))
            if failure:
                db.execute('INSERT INTO attempts VALUES (?,?)', (peer, now))
            local = db.execute('SELECT count(*) FROM attempts WHERE peer=?', (peer,)).fetchone()[0]
            total = db.execute('SELECT count(*) FROM attempts').fetchone()[0]
        return local >= 5 or total >= 20

    def reset_password(self, name, password):
        if not password_valid(password):
            raise ValueError('비밀번호는 15~1024자로 입력하세요.')
        salt = secrets.token_bytes(32)
        hashed = password_hash(password, salt)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
                raise ValueError('관리자 계정이 없습니다. 먼저 일회용 코드로 등록하세요.')
            db.execute('UPDATE users SET salt=?,password=?,must_change=0,revision=revision+1,updated_at=? WHERE name=?', (salt, hashed, self.clock(), name))
            db.execute('DELETE FROM sessions WHERE name=?', (name,))
            db.execute('DELETE FROM attempts')
        self.audit('password_reset', name)

    def audit(self, event, name=''):
        with self.audit_lock:
            path = self.root / 'audit.jsonl'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps({'at': self.clock(), 'event': event, 'user': name})+'\n')


def page(title, content):
    from ki2ci_theme import public_page
    return public_page(title, content)


def hidden(csrf, next_path='/'):
    return (f"<input type='hidden' name='_csrf' value='{html.escape(csrf, quote=True)}'>"
            f"<input type='hidden' name='next' value='{html.escape(next_path, quote=True)}'>")


def make_handler(store, upstream, origins, secure=False, release_upstream=None, host_gateway=None, repository_upstream=None):
    # This opt-in address is the host loopback gateway of the pinned slirp profile.
    # Never accept arbitrary private networks or DNS names as worker destinations.
    worker_hosts = {'127.0.0.1', 'localhost', '::1'}
    if host_gateway is not None:
        if host_gateway != '10.0.2.2':
            raise ValueError('Use the fixed slirp host gateway 10.0.2.2')
        worker_hosts.add(host_gateway)
    target = urlsplit(upstream)
    if (target.scheme != 'http' or target.hostname not in worker_hosts
            or target.username or target.password or target.path not in {'', '/'}
            or target.query or target.fragment):
        raise ValueError('Upstream must use loopback or the configured container host gateway')
    allowed_hosts = {urlsplit(o).netloc for o in origins}
    release_target = urlsplit(release_upstream) if release_upstream else None
    if release_target and (release_target.scheme != 'http' or release_target.hostname not in worker_hosts
                           or release_target.username or release_target.password or release_target.path not in {'','/'}
                           or release_target.query or release_target.fragment):
        raise ValueError('Release worker must use fixed loopback HTTP')
    repository_target = urlsplit(repository_upstream) if repository_upstream else None
    if repository_target and (repository_target.scheme != 'http' or repository_target.hostname not in worker_hosts
                              or repository_target.username or repository_target.password
                              or repository_target.path not in {'', '/'} or repository_target.query or repository_target.fragment):
        raise ValueError('Repository must use fixed loopback HTTP')
    origin_schemes = {}
    for origin in origins:
        u = urlsplit(origin)
        if (u.scheme not in {'http', 'https'} or not u.hostname or u.username or u.password
                or u.path or u.query or u.fragment):
            raise ValueError('Use explicit origins without a path')
        if u.scheme == 'http' and u.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Non-loopback access requires HTTPS')
        if u.netloc in origin_schemes and origin_schemes[u.netloc] != u.scheme:
            raise ValueError('Each host must have one configured origin scheme')
        origin_schemes[u.netloc] = u.scheme
    if not origin_schemes:
        raise ValueError('At least one origin is required')
    if secure and any(scheme != 'https' for scheme in origin_schemes.values()):
        raise ValueError('Secure cookies and HTTPS origins must agree')

    class Handler(BaseHTTPRequestHandler):
        server_version = 'KIKI-Auth'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):
            # Deliberately omit query strings, bodies, headers and credentials.
            print(self.command, urlsplit(self.path).path[:160], args[1] if len(args)>1 else '', flush=True)

        def reply(self, status, body=b'', content='text/html; charset=utf-8', extra=()):
            self.send_response(status)
            self.security_headers()
            self.send_header('Content-Type', content)
            self.send_header('Content-Length', str(len(body)))
            for key, value in extra:
                self.send_header(key, value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def security_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            # no-referrer makes native form POSTs send Origin: null in browsers.
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', CSP)

        def cookie(self, token, expire=False):
            value = f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if expire else LIFETIME}'
            return value + ('; Secure' if origin_schemes.get(self.headers.get('Host')) == 'https' else '')

        def token(self):
            try:
                jar = SimpleCookie(self.headers.get('Cookie', ''))
                token = jar[COOKIE].value if COOKIE in jar else ''
                return token if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else ''
            except CookieError:
                return ''

        def redirect(self, path, cookie=None):
            extra = [('Location', path)]
            if cookie is not None:
                extra.append(('Set-Cookie', cookie))
            self.reply(303, extra=extra)

        def error(self, status, message):
            self.reply(status, page('요청을 처리할 수 없습니다', f'<h1>요청을 처리할 수 없습니다</h1><p>{html.escape(message)}</p><a href="/login">로그인 화면</a>'))

        def valid_request(self):
            raw_target = self.requestline.split()[1]
            if (self.headers.get_all('Host', []) != [self.headers.get('Host')]
                    or self.headers.get('Host') not in allowed_hosts
                    or raw_target.startswith('//')
                    or not self.path.startswith('/') or self.path.startswith('//')
                    or any(c in self.path for c in '\\\r\n\x00')):
                self.error(400, '접속 주소를 확인해 주세요.')
                return False
            return True

        def form(self):
            if (self.headers.get('Origin') not in origins
                    or urlsplit(self.headers.get('Origin', '')).netloc != self.headers.get('Host')
                    or self.headers.get('Sec-Fetch-Site') in {'cross-site', 'same-site'}):
                self.error(403, '다른 출처의 요청은 허용되지 않습니다.')
                return None
            if (self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded'
                    or self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1):
                self.error(400, '올바른 폼 요청이 필요합니다.')
                return None
            try:
                length = int(self.headers.get('Content-Length', '0'))
                catalog_route = urlsplit(self.path).path in {'/package-groups/save', '/package-groups/restore', '/packages/metadata','/packages/register','/assistant/analyze','/assistant/draft','/assistant/metadata','/assistant/plan'}
                limit=65536 if catalog_route else 131072 if urlsplit(self.path).path.startswith('/releases/') else FORM_LIMIT
                if not 0 < length <= limit:
                    raise ValueError()
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError()
                values = parse_qs(body.decode('utf-8'), keep_blank_values=True, max_num_fields=32 if catalog_route else 16)
                if any(len(v) != 1 for v in values.values()):
                    raise ValueError()
                return {k: v[0] for k, v in values.items()}, body
            except (ValueError, UnicodeError):
                self.error(400, '요청 크기나 입력 형식을 확인해 주세요.')
                return None

        def login_page(self, setup=False, error='', status=200):
            session = store.session(self.token())
            new_cookie = None
            if not session or session['name']:
                token, session = store.new_session()
                new_cookie = self.cookie(token)
            next_path = safe_next(parse_qs(urlsplit(self.path).query).get('next', ['/'])[0])
            content = '<div class="eyebrow">KIKI 빌드 관리</div>'
            content += '<h1>관리자 계정 등록</h1><p>서버에서 일회용 설정 코드를 확인하고 첫 관리자 계정을 등록하세요.</p>' if setup else '<h1>빌드 콘솔 로그인</h1><p>패키지와 OS 빌드 상태를 확인하고 작업을 관리합니다.</p>'
            if error:
                content += f'<p class="error" role="alert">{html.escape(error)}</p>'
            if not setup and parse_qs(urlsplit(self.path).query).get('password_changed') == ['1']:
                content += '<p role="status">비밀번호가 변경됐습니다. 새 비밀번호로 로그인하세요.</p>'
            content += f'<form method="post" action="/{"setup" if setup else "login"}">'+hidden(session['csrf'], next_path)
            if setup:
                content += '<label for="code">일회용 설정 코드</label><input id="code" name="code" type="password" required autocomplete="off" maxlength="128">'
            content += '<label for="username">아이디</label><input id="username" name="username" autocomplete="username" required maxlength="64" placeholder="등록한 아이디">'
            content += f'<label for="password">비밀번호</label><input id="password" name="password" type="password" autocomplete="{"new-password" if setup else "current-password"}" required maxlength="1024"'+(' minlength="15"' if setup else '')+'>'
            if setup:
                content += '<small>15자 이상. 긴 문장 형태의 비밀번호를 사용할 수 있습니다.</small><label for="confirm">비밀번호 확인</label><input id="confirm" name="confirm" type="password" autocomplete="new-password" required minlength="15" maxlength="1024">'
            content += '<button type="submit">'+('관리자 계정 등록' if setup else '로그인')+'</button></form>'
            content += '<p>설정 코드는 SSH로 접속한 서버의 <code>auth/state/setup-code</code> 파일에 있습니다. 등록 후 자동으로 폐기됩니다.</p>' if setup else '<p>세션은 30분 동안 활동이 없으면 만료됩니다.</p>'
            self.reply(status, page('관리자 계정 등록' if setup else '로그인', content), extra=[('Set-Cookie', new_cookie)] if new_cookie else [])

        def health(self):
            if self.path == '/healthz' or (self.command in {'HEAD', 'OPTIONS'} and self.path in {'/', '*'}):
                self.reply(200, b'ok\n', 'text/plain; charset=utf-8')
                return True
            return False

        def do_GET(self):
            if self.health():
                return
            if self.path == '/' and not self.token():
                self.reply(200, page('빌드 콘솔',
                    '<h1>KIKI OS 빌드 콘솔</h1><p>로그인 후 패키지와 OS 빌드를 관리하세요.</p>'
                    '<a href="/login">로그인</a>'))
                return
            if not self.valid_request():
                return
            path = urlsplit(self.path).path
            if repository_target and (path == '/ki2' or path.startswith('/ki2/')):
                self.public_repository()
                return
            assets = {'/build-theme.css': ('ki2ci_theme.css', 'text/css; charset=utf-8'),
                      '/build-theme.js': ('ki2ci_theme.js', 'text/javascript; charset=utf-8')}
            if path in assets:
                filename, content_type = assets[path]
                asset = Path(__file__).with_name(filename)
                if not asset.is_file():
                    self.error(404, '화면 파일을 찾을 수 없습니다.')
                    return
                self.reply(200, asset.read_bytes(), content_type)
                return
            session = store.session(self.token())
            if path in {'/login', '/setup'}:
                if session and session['name']:
                    self.redirect(safe_next(parse_qs(urlsplit(self.path).query).get('next', ['/'])[0]))
                elif (path == '/setup') == store.configured():
                    self.redirect('/login' if store.configured() else '/setup')
                else:
                    self.login_page(setup=path == '/setup')
                return
            if not session or not session['name']:
                if path.startswith('/api/'):
                    self.reply(401, b'{"error":"authentication_required"}', 'application/json')
                else:
                    self.redirect('/login?'+urlencode({'next': safe_next(self.path)}))
                return
            if session.get('must_change') and path not in {'/account', '/logout', '/auth/session.js'}:
                self.redirect('/account')
                return
            if path == '/account' or path == '/users' or path.startswith('/users/'):
                self.accounts_get(session, path)
                return
            if path == '/auth/session.js':
                self.reply(200, b"const originalFetch=window.fetch;window.fetch=async(...args)=>{const r=await originalFetch(...args);if(r.status===401)window.location.replace('/login?next='+encodeURIComponent(location.pathname+location.search));return r;};window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});", 'text/javascript; charset=utf-8')
                return
            ui = Path(__file__).with_name('ki2ci_ui.js')
            if path == '/build-console.js' and ui.is_file():
                self.reply(200, ui.read_bytes(), 'text/javascript; charset=utf-8')
                return
            if path == '/logout':
                self.error(405, '로그아웃 버튼을 사용해 주세요.')
                return
            self.proxy(session)

        def do_HEAD(self):
            self.do_GET()

        def do_OPTIONS(self):
            if not self.health():
                self.reply(405, extra=[('Allow', 'GET, HEAD, POST')])

        def do_POST(self):
            if not self.valid_request():
                return
            path = urlsplit(self.path).path
            if repository_target and (path == '/ki2' or path.startswith('/ki2/')):
                self.reply(405, extra=[('Allow', 'GET, HEAD')])
                return
            session = store.session(self.token())
            if not session:
                self.error(401, '세션이 만료되었습니다. 다시 로그인해 주세요.')
                return
            parsed = self.form()
            if parsed is None:
                return
            data, body = parsed
            if not hmac.compare_digest(data.get('_csrf', '').encode('utf-8'), session['csrf'].encode('utf-8')):
                self.error(403, '화면을 새로고침한 뒤 다시 시도해 주세요.')
                return
            if path in {'/login', '/setup'}:
                peer = self.client_address[0]
                if store.limited(peer):
                    self.error(429, '로그인 시도가 너무 많습니다. 15분 후 다시 시도해 주세요.')
                    return
                name, password = data.get('username', ''), data.get('password', '')
                accepted = False
                if path == '/setup':
                    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) or not password_valid(password) or password != data.get('confirm'):
                        self.login_page(True, '아이디 형식과 15자 이상의 비밀번호, 비밀번호 확인을 확인해 주세요.', 400)
                        return
                    accepted = store.setup(data.get('code', ''), name, password)
                elif len(password) <= 1024 and len(name) <= 64:
                    accepted = store.verify_password(name, password)
                if not accepted:
                    store.limited(peer, failure=True)
                    store.audit('authentication_failed')
                    self.login_page(path == '/setup', '입력한 인증 정보를 확인해 주세요.', 401)
                    return
                store.revoke(self.token())
                try:
                    token, logged_in = store.new_session(name)
                except AccountError as exc:
                    self.error(401, str(exc))
                    return
                store.audit('login', name)
                self.redirect('/account' if logged_in.get('must_change') else safe_next(data.get('next', '/')), self.cookie(token))
                return
            if not session['name']:
                self.error(401, '로그인이 필요합니다.')
                return
            if path == '/logout':
                store.revoke(self.token())
                store.audit('logout', session['name'])
                self.redirect('/login', self.cookie('', expire=True))
                return
            if path == '/account/password' or path == '/users' or path.startswith('/users/'):
                self.accounts_post(session, path, data)
                return
            # A manager may revoke access while this request reads its form.
            session = store.session(self.token())
            if not session or not session['name']:
                self.error(401, '접속 권한이 회수되었거나 세션이 만료되었습니다. 다시 로그인하세요.')
                return
            if session.get('must_change'):
                self.error(403, '먼저 내 계정에서 임시 비밀번호를 변경하세요.')
                return
            if session.get('role') not in {'admin', 'operator'}:
                self.error(403, '조회자는 빌드·패키지·ISO·릴리즈를 변경할 수 없습니다.')
                return
            if path=='/assistant/settings' and session.get('role')!='admin':
                self.error(403,'Local LLM 연결 설정은 관리자만 변경할 수 있습니다.');return
            self.proxy(session, body)

        def accounts_get(self, session, path):
            from ki2users_views import account_page, users_page, user_page
            if path == '/account':
                self.reply(200, account_page(session))
                return
            if session.get('role') != 'admin' or session.get('must_change'):
                self.error(403, '사용자 관리는 관리자만 사용할 수 있습니다.')
                return
            if path == '/users':
                query = parse_qs(urlsplit(self.path).query).get('q', [''])[0][:64]
                self.reply(200, users_page(session, store.users(), store.account_events(), query))
            elif path == '/users/new':
                self.reply(200, user_page(session, None))
            else:
                name = path.removeprefix('/users/')
                user = store.user(name) if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) else None
                if not user:
                    self.error(404, '사용자를 찾을 수 없습니다.')
                    return
                self.reply(200, user_page(session, user))

        def accounts_post(self, session, path, data):
            from ki2users_views import temporary_page, account_page, user_page
            name = session['name']
            try:
                if path == '/account/password':
                    peer = 'password:'+name
                    if store.limited(peer):
                        self.error(429, '변경 시도가 너무 많습니다. 15분 후 다시 시도하세요.')
                        return
                    if data.get('password') != data.get('confirm'):
                        raise AccountError('새 비밀번호와 확인 값이 다릅니다.')
                    try:
                        store.change_password(name, data.get('current', ''), data.get('password', ''))
                    except AccountError:
                        store.limited(peer, failure=True)
                        raise
                    self.redirect('/login?password_changed=1', self.cookie('', expire=True))
                    return
                if session.get('role') != 'admin' or session.get('must_change'):
                    self.error(403, '사용자 관리는 관리자만 사용할 수 있습니다.')
                    return
                if path == '/users/create':
                    target_name = data.get('username', '')
                    temporary = store.create_user(name, target_name, data.get('role', ''))
                elif path.startswith('/users/') and path.endswith('/manage'):
                    target_name = path[len('/users/'):-len('/manage')]
                    if data.get('action') in {'reset', 'revoke'} and data.get('confirm_action') != 'yes':
                        raise AccountError('작업 확인란에 동의해야 합니다.')
                    temporary = store.manage_user(name, target_name, data.get('revision'), data.get('action'),
                                                  data.get('role'), 1 if data.get('enabled') == '1' else 0)
                else:
                    self.error(404, '지원하지 않는 사용자 작업입니다.')
                    return
                if temporary:
                    self.reply(200, temporary_page(session, target_name, temporary))
                else:
                    self.redirect('/users/'+target_name if target_name != name else '/users')
            except AccountError as exc:
                if path == '/account/password':
                    self.reply(400, account_page(session, str(exc)))
                else:
                    self.reply(400, user_page(session, store.user(data.get('username', '') if path == '/users/create' else path[len('/users/'):-len('/manage')]), str(exc)))

        def public_repository(self):
            # This anonymous boundary accepts only read requests for the dedicated repository.
            # No cookies, authorization headers, redirects, or build-worker routing cross it.
            if self.path == '/ki2':
                self.redirect('/ki2/')
                return
            if (not re.fullmatch(r'/ki2/[A-Za-z0-9/._+~-]*', self.path)
                    or any(part in {'.', '..'} for part in self.path.split('/'))):
                self.reply(404)
                return
            connection = http.client.HTTPConnection(repository_target.hostname, repository_target.port, timeout=30)
            sent = False
            try:
                connection.request(self.command, self.path, headers={'Host': '127.0.0.1', 'Accept-Encoding': 'identity'})
                response = connection.getresponse()
                if response.status not in {200, 404, 503}:
                    self.reply(502)
                    return
                length = int(response.getheader('Content-Length', '-1'))
                if not 0 <= length <= 1024 * 1024 * 1024:
                    raise ValueError('invalid repository response size')
                self.send_response(response.status)
                self.security_headers()
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
                self.send_header('Content-Length', str(length))
                self.end_headers()
                sent = True
                if self.command != 'HEAD':
                    while length:
                        block = response.read(min(length, 65536))
                        if not block:
                            self.close_connection = True
                            break
                        self.wfile.write(block)
                        length -= len(block)
            except (OSError, ValueError, http.client.HTTPException):
                if not sent:
                    self.reply(502)
                self.close_connection = True
            finally:
                connection.close()

        def proxy(self, session, body=None):
            route = urlsplit(self.path).path
            destination = release_target if release_target and (route in {'/versions','/iso-build','/cpu-profiles','/releases','/updates','/artifacts','/api/artifacts'} or route.startswith(('/library/','/iso-build/','/api/releases','/releases/','/updates/','/api/updates'))) else target
            connection = http.client.HTTPConnection(destination.hostname, destination.port, timeout=100 if route.startswith('/assistant/') else 30)
            sent = False
            try:
                # Outer Host, Origin and CSRF were checked before this method.
                # Workers retain one fixed internal origin for both entry points.
                headers = {'Host': '127.0.0.1:18090', 'Accept-Encoding': 'identity', 'X-KIKI-Actor': session['name']}
                if 'Origin' in self.headers:headers['Origin']='http://127.0.0.1:18090'
                for name in ['Content-Type', 'Accept']:
                    if name in self.headers:
                        headers[name] = self.headers[name]
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                content_type = response.getheader('Content-Type', '')
                transformed = None
                if content_type.startswith('text/html'):
                    # Console pages are bounded; KI2 downloads stream separately.
                    raw = response.read(4*1024*1024+1)
                    if len(raw) > 4*1024*1024:
                        raise ValueError('upstream HTML too large')
                    text = raw.decode('utf-8')
                    try:
                        from ki2ci_ko import localize_html
                    except ImportError:
                        pass
                    else:
                        text = localize_html(text, route)
                    text = re.sub(r'(<form\b[^>]*\bmethod\s*=\s*[\'\"]post[\'\"][^>]*>)', lambda m: m[0]+hidden(session['csrf']), text, flags=re.I)
                    if session.get('role') == 'viewer':
                        text = re.sub(r'(<form\b[^>]*\bmethod\s*=\s*[\'\"]post[\'\"][^>]*>)(.*?)(</form>)',
                                      lambda m: m[1]+"<fieldset disabled style='border:0;margin:0;padding:0'><legend>조회 전용 · 운영자 권한 필요</legend>"+m[2]+"</fieldset>"+m[3], text, flags=re.I | re.S)
                    from ki2ci_theme import decorate
                    text = decorate(text, session, route)
                    transformed = text.encode('utf-8')
                elif content_type.startswith('application/json') and route.startswith(('/api/plan','/api/jobs')):
                    raw = response.read(4*1024*1024+1)
                    if len(raw) > 4*1024*1024:
                        raise ValueError('upstream JSON too large')
                    try:
                        from ki2ci_ko import localize_json
                    except ImportError:
                        transformed = raw
                    else:
                        transformed = json.dumps(localize_json(json.loads(raw)), ensure_ascii=False).encode('utf-8')
                self.send_response(response.status)
                self.security_headers()
                connection_headers = {s.strip().lower() for s in response.getheader('Connection', '').split(',')}
                for name, value in response.getheaders():
                    if name.lower() not in HOP | connection_headers | {'cache-control', 'content-security-policy', 'x-frame-options', 'x-content-type-options', 'referrer-policy'}:
                        self.send_header(name, value)
                if transformed is not None:
                    self.send_header('Content-Length', str(len(transformed)))
                elif response.getheader('Content-Length') is not None:
                    self.send_header('Content-Length', response.getheader('Content-Length'))
                else:
                    self.send_header('Connection', 'close')
                    self.close_connection = True
                self.end_headers()
                sent = True
                if transformed is not None:
                    self.wfile.write(transformed)
                else:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (OSError, http.client.HTTPException, ValueError):
                self.close_connection = True
                if not sent:
                    self.error(502, '빌드 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.')
            finally:
                connection.close()

    return Handler


class AuthHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Bound slow-client/KDF concurrency; the build worker keeps its own resources.
    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'serve', 'reset-password'])
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8092)
    parser.add_argument('--upstream', default='http://127.0.0.1:8091')
    parser.add_argument('--release-upstream', default=None)
    parser.add_argument('--public-repository-config', type=Path, default=Path(__file__).with_name('ki2repository-public.json'),
                        help='Optional read-only /ki2/ upstream configuration; no other route becomes public')
    parser.add_argument('--origin', action='append')
    parser.add_argument('--secure-cookie', action='store_true')
    parser.add_argument('--slirp-network', action='store_true',
                        help='Use the pinned isolated slirp address 10.0.2.100 and host gateway 10.0.2.2')
    parser.add_argument('--rotate-setup', action='store_true')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    store = AuthStore(args.state_dir)
    if args.command == 'init':
        pending = store.bootstrap(args.rotate_setup)
        print('Initial setup code file: '+str(store.root/'setup-code') if pending else 'Administrator already configured')
    elif args.command == 'reset-password':
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('New password: ')
        if not password_valid(password):
            parser.error('Password must contain 15 to 1024 characters')
        if not args.password_stdin and not hmac.compare_digest(password.encode('utf-8'), getpass.getpass('Confirm password: ').encode('utf-8')):
            parser.error('Passwords do not match')
        store.reset_password(args.username, password)
        print('Password updated; target account sessions revoked')
    else:
        if args.slirp_network and args.bind != '10.0.2.100':
            parser.error('The isolated slirp listener must bind 10.0.2.100')
        if not args.slirp_network and not ipaddress.ip_address(args.bind).is_loopback:
            parser.error('Use loopback or the explicitly configured isolated container network')
        host_gateway = '10.0.2.2' if args.slirp_network else None
        origins = args.origin or ['http://127.0.0.1:18090', 'http://localhost:18090']
        repository_upstream = None
        if args.public_repository_config.is_file():
            repository_upstream = json.loads(args.public_repository_config.read_text())['upstream']
        handler = make_handler(store, args.upstream, origins, args.secure_cookie, args.release_upstream, host_gateway, repository_upstream)
        print('KIKI authenticated web service ready', flush=True)
        with AuthHTTPServer((args.bind, args.port), handler) as server:
            signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown,daemon=True).start())
            server.serve_forever()


if __name__ == '__main__':
    main()
