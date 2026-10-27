"""Transactional account administration. Authentication secrets never leave the store."""
import hmac
import json
import re
import secrets

ROLES = {'admin': '관리자', 'operator': '운영자', 'viewer': '조회자'}


class AccountError(ValueError):
    pass


class UserAccounts:
    def migrate_users(self, db):
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(users)')}
        for name, definition in [
            ('role', "TEXT NOT NULL DEFAULT 'admin'"),
            ('enabled', 'INTEGER NOT NULL DEFAULT 1'),
            ('must_change', 'INTEGER NOT NULL DEFAULT 0'),
            ('revision', 'INTEGER NOT NULL DEFAULT 1'),
            ('created_at', 'REAL NOT NULL DEFAULT 0'),
            ('updated_at', 'REAL NOT NULL DEFAULT 0'),
        ]:
            if name not in columns:
                db.execute('ALTER TABLE users ADD COLUMN '+name+' '+definition)
        db.execute('''CREATE TABLE IF NOT EXISTS account_events
            (id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
             target TEXT NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL)''')

    def _account(self, db, name):
        row = db.execute('''SELECT name,role,enabled,must_change,revision,created_at,updated_at
                            FROM users WHERE name=?''', (name,)).fetchone()
        return dict(zip(('name', 'role', 'enabled', 'must_change', 'revision', 'created_at', 'updated_at'), row)) if row else None

    def user(self, name):
        with self.connect() as db:
            return self._account(db, name)

    def users(self):
        with self.connect() as db:
            return [self._account(db, row[0]) for row in db.execute('SELECT name FROM users ORDER BY name COLLATE NOCASE')]

    def account_events(self):
        with self.connect() as db:
            return list(db.execute('SELECT at,actor,target,event FROM account_events ORDER BY id DESC LIMIT 30'))

    def _admin(self, db, actor):
        user = self._account(db, actor)
        if not user or not user['enabled'] or user['role'] != 'admin' or user['must_change']:
            raise AccountError('사용자 관리 권한이 없습니다.')

    def _event(self, db, actor, target, event, **details):
        db.execute('INSERT INTO account_events(at,actor,target,event,details) VALUES (?,?,?,?,?)',
                   (self.clock(), actor, target, event, json.dumps(details, ensure_ascii=False)))

    def create_user(self, actor, name, role):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) or name.casefold() in {'.', '..', 'new'}:
            raise AccountError('아이디는 영문·숫자·점·밑줄·하이픈으로 1~64자 입력하세요.')
        if role not in ROLES:
            raise AccountError('권한을 확인하세요.')
        temporary = secrets.token_urlsafe(24)
        salt, hashed = self.password_material(temporary)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admin(db, actor)
            if db.execute('SELECT 1 FROM users WHERE lower(name)=lower(?)', (name,)).fetchone():
                raise AccountError('이미 사용 중인 아이디입니다.')
            db.execute('''INSERT INTO users(name,salt,password,role,enabled,must_change,revision,created_at,updated_at)
                          VALUES (?,?,?,?,1,1,1,?,?)''', (name, salt, hashed, role, self.clock(), self.clock()))
            self._event(db, actor, name, 'created', role=role)
        return temporary

    def manage_user(self, actor, name, revision, action, role=None, enabled=None):
        if action not in {'update', 'reset', 'revoke'}:
            raise AccountError('지원하지 않는 작업입니다.')
        if action == 'update' and (role not in ROLES or enabled not in {0, 1}):
            raise AccountError('권한과 계정 상태를 확인하세요.')
        temporary = secrets.token_urlsafe(24) if action == 'reset' else None
        material = self.password_material(temporary) if temporary else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admin(db, actor)
            current = self._account(db, name)
            if not current:
                raise AccountError('사용자를 찾을 수 없습니다.')
            if str(current['revision']) != str(revision):
                raise AccountError('다른 요청으로 계정 정보가 변경됐습니다. 새로고침 후 다시 시도하세요.')
            if actor == name and (action == 'reset' or (action == 'update' and (role != 'admin' or enabled != 1))):
                raise AccountError('자신의 관리자 권한·활성 상태는 변경할 수 없습니다. 비밀번호는 내 계정에서 변경하세요.')
            if action == 'update':
                if current['role'] == 'admin' and current['enabled'] and not current['must_change'] and (role != 'admin' or not enabled):
                    count = db.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1 AND must_change=0").fetchone()[0]
                    if count <= 1:
                        raise AccountError('마지막으로 사용 가능한 관리자는 비활성화하거나 권한을 낮출 수 없습니다.')
                db.execute('UPDATE users SET role=?,enabled=?,revision=revision+1,updated_at=? WHERE name=?', (role, enabled, self.clock(), name))
                if role != current['role'] or enabled != current['enabled']:
                    db.execute('DELETE FROM sessions WHERE name=?', (name,))
                self._event(db, actor, name, 'updated', role=role, enabled=enabled)
            elif action == 'reset':
                db.execute('UPDATE users SET salt=?,password=?,must_change=1,revision=revision+1,updated_at=? WHERE name=?', (*material, self.clock(), name))
                db.execute('DELETE FROM sessions WHERE name=?', (name,))
                self._event(db, actor, name, 'password_reset')
            else:
                db.execute('DELETE FROM sessions WHERE name=?', (name,))
                db.execute('UPDATE users SET revision=revision+1,updated_at=? WHERE name=?', (self.clock(), name))
                self._event(db, actor, name, 'sessions_revoked')
        return temporary

    def change_password(self, name, old, new):
        if not self.password_policy(new) or hmac.compare_digest(old.encode(), new.encode()):
            raise AccountError('현재 비밀번호와 다른 15~1024자의 비밀번호를 입력하세요.')
        with self.connect() as db:
            row = db.execute('SELECT salt,password,enabled FROM users WHERE name=?', (name,)).fetchone()
        if not row or not row[2] or not hmac.compare_digest(self.hash_password(old, row[0]), row[1]):
            raise AccountError('현재 비밀번호를 확인하세요.')
        salt, hashed = self.password_material(new)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('''UPDATE users SET salt=?,password=?,must_change=0,revision=revision+1,updated_at=?
                                    WHERE name=? AND password=? AND enabled=1''', (salt, hashed, self.clock(), name, row[1])).rowcount
            if not changed:
                raise AccountError('계정 정보가 변경됐습니다. 다시 로그인하세요.')
            db.execute('DELETE FROM sessions WHERE name=?', (name,))
            self._event(db, name, name, 'password_changed')
