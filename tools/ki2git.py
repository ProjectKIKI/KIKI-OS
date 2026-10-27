"""Fetch one administrator-configured Git branch without touching a worktree.

No push, reset, clean, hooks, submodules or web-supplied remote addresses.
Archives remain available so queued jobs and retries keep their exact source.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import threading
import uuid
from urllib.parse import urlsplit


class GitError(RuntimeError):
    pass


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


class GitSources:
    def __init__(self, root: Path, remote: str, branch: str, *, allow_local=False):
        self.root, self.remote, self.branch = root, remote, branch
        self.allow_local = allow_local  # Only fixture repositories; never exposed by CLI/web.
        parsed = urlsplit(remote)
        if not allow_local and (parsed.scheme != 'https' or not parsed.hostname
                or parsed.password or parsed.username
                or parsed.query or parsed.fragment or any(c in remote for c in '\r\n\x00')):
            raise GitError('Git 원격 주소는 자격 증명을 포함하지 않는 HTTPS 주소여야 합니다. SSH 전송은 허용하지 않습니다.')
        if not branch or branch.startswith('-') or any(c in branch for c in '\r\n\x00'):
            raise GitError('Git 브랜치 이름을 확인하세요.')
        self.root.mkdir(parents=True, exist_ok=True)
        self.mirror = self.root / 'mirror.git'
        self.archives = self.root / 'archives'
        self.archives.mkdir(exist_ok=True)
        self.hooks = self.root / 'empty-hooks'
        self.hooks.mkdir(exist_ok=True)
        self.operation = threading.Lock()
        self.state_lock = threading.RLock()
        self.busy = False
        state = self._read()
        if state and (state['remote'] != remote or state['branch'] != branch):
            raise GitError('다른 원격 저장소·브랜치는 별도 Git 저장 경로로 구성하세요.')
        self._git('check-ref-format', '--branch', branch, mirror=False)

    def _read(self):
        path = self.root / 'state.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def _write(self, state):
        temp = self.root / (uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.root / 'state.json')
        finally:
            temp.unlink(missing_ok=True)

    def status(self):
        with self.state_lock:
            state = self._read()
            return dict(state, enabled=True, remote=self.remote, branch=self.branch,
                        busy=self.busy, history=state.get('history', []),
                        status='running' if self.busy else state.get('status', 'not_synced'))

    def _git(self, *args, mirror=True, stdout=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS='1',
                   GIT_ALLOW_PROTOCOL='https:file' if self.allow_local else 'https')
        command = ['git', '-c', 'core.hooksPath=' + str(self.hooks),
                   '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always',
                   '-c', 'protocol.file.allow=' + ('always' if self.allow_local else 'never'),
                   '-c', 'protocol.ext.allow=never', '-c', 'http.followRedirects=false']
        if mirror:
            command += ['--git-dir=' + str(self.mirror)]
        try:
            result = subprocess.run(command + list(args), env=env, stdin=subprocess.DEVNULL,
                                    stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError('Git 실행에 실패했습니다. 도구 설치·연결·읽기 권한을 확인하세요.') from exc
        if result.returncode:
            # Git stderr can contain credential helper output. Never send it to the UI/logs.
            raise GitError('Git 요청이 실패했습니다. 원격 주소·브랜치·인증·네트워크를 확인하세요.')
        return result.stdout.decode('utf-8', errors='replace').strip() if stdout is None else ''

    def start_sync(self):
        if not self.operation.acquire(blocking=False):
            raise GitError('이미 Git 동기화 또는 소스 준비가 진행 중입니다.')
        self.busy = True
        thread = threading.Thread(target=self._background, name='kiki-git-sync', daemon=True)
        thread.start()

    def _background(self):
        try:
            self._sync()
        except GitError:
            pass  # Safe error text is persisted by _sync.
        finally:
            self.busy = False
            self.operation.release()

    def sync(self):
        with self.operation:
            self.busy = True
            try:
                return self._sync()
            finally:
                self.busy = False

    def _sync(self):
        try:
            if not self.mirror.exists():
                self._git('init', '--bare', str(self.mirror), mirror=False)
            ref = 'refs/remotes/kiki/' + self.branch
            self._git('fetch', '--no-tags', '--no-recurse-submodules', '--depth=1',
                      self.remote, '+refs/heads/' + self.branch + ':' + ref)
            commit = self._git('rev-parse', '--verify', ref + '^{commit}')
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
                raise GitError('Git 커밋 식별자가 올바르지 않습니다.')
            if any(line.startswith('160000 ') for line in self._git('ls-tree', '-r', commit).splitlines()):
                raise GitError('서브모듈이 있는 커밋은 별도 소스 고정 설정이 필요합니다.')
            archive = self.archives / (commit + '.tar')
            if not archive.exists():
                temp = archive.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                try:
                    with temp.open('wb') as stream:
                        self._git('archive', '--format=tar', commit, stdout=stream)
                    self._members(temp)  # Check before making this source available.
                    temp.replace(archive)
                finally:
                    temp.unlink(missing_ok=True)
            self._members(archive)
            previous_record = next((r for r in self.status()['history'] if r['commit'] == commit), None)
            if previous_record and digest(archive) != previous_record['archive_sha256']:
                raise GitError('Git 소스 아카이브 SHA-256이 일치하지 않습니다. 빌드를 중단합니다.')
            record = {'commit': commit, 'archive_sha256': digest(archive),
                      'subject': self._git('show', '-s', '--format=%s', commit)[:300],
                      'committed_at': self._git('show', '-s', '--format=%cI', commit),
                      'synced_at': timestamp()}
            with self.state_lock:
                state = self._read()
                previous = state.get('current', {}).get('commit')
                history = state.get('history', [])
                if not any(item['commit'] == commit for item in history):
                    history.insert(0, record)
                self._write(dict(remote=self.remote, branch=self.branch, current=record,
                                 history=history, checked_at=timestamp(), status='ready', error='',
                                 changed=previous != commit))
            return record
        except Exception as exc:
            error = str(exc) if isinstance(exc, GitError) else 'Git 소스 준비 중 오류가 발생했습니다.'
            with self.state_lock:
                state = self._read()
                state.update(remote=self.remote, branch=self.branch, checked_at=timestamp(),
                             status='failed', error=error)
                self._write(state)
            raise GitError(error) from exc

    @staticmethod
    def _members(archive):
        if archive.stat().st_size > 512 * 1024 * 1024:
            raise GitError('소스 아카이브 크기 한도(512 MiB)를 초과했습니다.')
        with tarfile.open(archive, 'r:') as stream:
            members = stream.getmembers()
        for item in members:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in item.name
                    or any(p.lower() == '.git' or ':' in p for p in path.parts)
                    or not (item.isfile() or item.isdir())):
                raise GitError('소스에 지원하지 않는 경로·링크가 있습니다. 서브모듈·심볼릭 링크는 별도 검토가 필요합니다.')
        return members

    def record(self, commit):
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit or ''):
            raise GitError('확인한 Git 커밋을 선택하세요.')
        record = next((r for r in self.status()['history'] if r['commit'] == commit), None)
        if record is None:
            raise GitError('동기화 이력에 없는 커밋입니다. 먼저 동기화하세요.')
        return dict(record, kind='git', remote=self.remote, branch=self.branch)

    def export(self, commit, destination):
        with self.exclusive():
            record = self.record(commit)
            archive = self.archives / (commit + '.tar')
            if digest(archive) != record['archive_sha256']:
                raise GitError('Git 소스 아카이브 SHA-256이 일치하지 않습니다. 빌드를 중단합니다.')
            members = self._members(archive)
            destination.mkdir(parents=True, exist_ok=False)
            try:
                with tarfile.open(archive, 'r:') as stream:
                    # No links/special files; never use unrestricted extractall.
                    for item in members:
                        path = destination.joinpath(*PurePosixPath(item.name).parts)
                        if item.isdir():
                            path.mkdir(parents=True, exist_ok=True)
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with stream.extractfile(item) as source, path.open('xb') as target:
                                shutil.copyfileobj(source, target)
                            path.chmod(0o755 if item.mode & 0o111 else 0o644)
                if not (destination / 'tools/ki2build.py').is_file() or not (destination / 'distro/recipes').is_dir():
                    raise GitError('KIKI OS 빌드 도구·패키지 명세가 없는 커밋입니다.')
                return record
            except Exception:
                # Do not remove any pre-existing tree; only the new export is left for diagnosis.
                raise

    @contextmanager
    def exclusive(self):
        if not self.operation.acquire(blocking=False):
            raise GitError('이미 Git 동기화 또는 소스 준비가 진행 중입니다. 완료 후 다시 요청하세요.')
        try:
            yield
        finally:
            self.operation.release()
