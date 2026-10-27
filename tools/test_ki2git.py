import io
import json
import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

import ki2ci
from ki2git import GitSources, GitError
from ki2git_views import git_page


class GitSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'origin'
        self.remote.mkdir()
        self.git('init', '-b', 'stage3')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.remote / 'tools').mkdir()
        (self.remote / 'tools/ki2build.py').write_text('# fixture\n')
        (self.remote / 'distro/recipes').mkdir(parents=True)
        (self.remote / 'distro/recipes/base.toml').write_text('''[[recipe]]
name = "fixture"
version = "1.0"
release = 1
summary = "test"
license = "MIT"
architectures = ["x86_64"]
[recipe.source]
type = "local"
path = "source"
[recipe.build]
system = "copy"
[[recipe]]
name = "linux"
version = "6.1.187"
release = 2
summary = "fixture kernel"
license = "GPL-2.0-only"
architectures = ["x86_64"]
[recipe.source]
type = "url"
url = "https://example.invalid/linux.tar.xz"
sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
[recipe.build]
system = "kernel"
config_fragments = ["distro/kernel/test.config"]
''')
        self.first = self.commit('one')
        self.sources = GitSources(self.root / 'git', str(self.remote), 'stage3', allow_local=True)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.remote), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, content):
        (self.remote / 'version.txt').write_text(content)
        self.git('add', '.')
        self.git('commit', '-m', content)
        return self.git('rev-parse', 'HEAD')

    def test_sync_exports_committed_source_and_preserves_dirty_worktree(self):
        (self.remote / 'version.txt').write_text('uncommitted work')
        first = self.sources.sync()
        self.assertEqual(first['commit'], self.first)
        source = self.root / 'job-source'
        self.sources.export(self.first, source)
        self.assertEqual((source / 'version.txt').read_text(), 'one')
        self.assertEqual((self.remote / 'version.txt').read_text(), 'uncommitted work')
        second = self.commit('two')
        self.sources.sync()
        self.assertEqual((source / 'version.txt').read_text(), 'one')
        self.sources.export(self.first, self.root / 'retry-source')
        self.assertEqual((self.root / 'retry-source/version.txt').read_text(), 'one')
        self.assertEqual(self.sources.status()['current']['commit'], second)
        self.assertEqual(len(self.sources.status()['history']), 2)
        self.sources.sync()
        self.assertEqual(len(self.sources.status()['history']), 2)

    def test_failed_fetch_keeps_last_verified_commit_and_history(self):
        self.sources.sync()
        self.git('branch', '-m', 'gone')
        with self.assertRaises(GitError):
            self.sources.sync()
        state = self.sources.status()
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['current']['commit'], self.first)
        self.sources.export(self.first, self.root / 'old-source')
        self.assertEqual((self.root / 'old-source/version.txt').read_text(), 'one')

    def test_corrupt_archive_is_not_reblessed_by_resync(self):
        first = self.sources.sync()
        archive = self.sources.archives / (self.first + '.tar')
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(GitError, 'SHA-256'):
            self.sources.export(self.first, self.root / 'corrupt')
        with self.assertRaisesRegex(GitError, 'SHA-256'):
            self.sources.sync()
        self.assertEqual(self.sources.status()['current']['archive_sha256'], first['archive_sha256'])

    def test_existing_directory_and_unknown_commit_are_rejected(self):
        self.sources.sync()
        preserved = self.root / 'preserved'
        preserved.mkdir()
        (preserved / 'keep').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.sources.export(self.first, preserved)
        self.assertEqual((preserved / 'keep').read_text(), 'keep')
        with self.assertRaises(GitError):
            self.sources.export('a' * 40, self.root / 'unknown')

    def test_remote_credentials_protocols_and_changed_config_are_rejected(self):
        for remote in ['https://user:secret@host/repo', 'file:///tmp/repo', 'ext::shell', 'http://host/repo',
                       'ssh://git@host/repo', 'git@host:repo']:
            with self.subTest(remote=remote), self.assertRaises(GitError):
                GitSources(self.root / 'invalid', remote, 'stage3')
        self.sources.sync()
        with self.assertRaises(GitError):
            GitSources(self.sources.root, str(self.remote), 'other', allow_local=True)

    def test_production_git_process_only_allows_https(self):
        result = subprocess.CompletedProcess([], 0, stdout=b'stage3', stderr=b'')
        with mock.patch('ki2git.subprocess.run', return_value=result) as run:
            GitSources(self.root / 'https-only', 'https://example.invalid/kiki.git', 'stage3')
        self.assertEqual(run.call_args.kwargs['env']['GIT_ALLOW_PROTOCOL'], 'https')
        self.assertIn('protocol.allow=never', run.call_args.args[0])

    def test_unsafe_archive_links_and_parent_paths_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('/absolute', tarfile.REGTYPE)]:
            archive = self.root / 'unsafe.tar'
            with tarfile.open(archive, 'w') as stream:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = '../../escape'
                stream.addfile(member, io.BytesIO(b''))
            with self.assertRaises(GitError):
                self.sources._members(archive)

    def test_queue_and_retry_pin_source_and_execute_in_private_tree(self):
        self.sources.sync()
        repo = Path(__file__).resolve().parents[1]
        config = ki2ci.CiConfig(repo, self.root / 'build', 'x86_64', 1, 'fixture', self.root / 'publish')
        server = ki2ci.BuildServer(config)
        self.addCleanup(server.close)
        server.git = self.sources
        with mock.patch.object(server, '_start_worker'):
            job = server.submit('security', source='git', commit=self.first)
        second = self.commit('two')
        self.sources.sync()
        code = "from pathlib import Path; assert Path('version.txt').read_text() == 'one'; Path('result').write_text('ok')"
        with mock.patch.object(ki2ci, 'pipeline_steps', return_value=[ki2ci.Step('verify source', [sys.executable, '-c', code])]):
            ki2ci.run_job(config, server.store, job['id'])
        result = server.store.read(job['id'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['source']['commit'], self.first)
        self.assertEqual(self.sources.status()['current']['commit'], second)
        self.assertFalse((repo / 'result').exists())
        with mock.patch.object(server, '_start_worker'):
            retry = server.retry(job['id'])
            package = server.submit_package('fixture', source='git', commit=self.first)
            server.cancel(package['id'])
            package_retry = server.retry(package['id'])
        self.assertEqual(retry['source']['commit'], self.first)
        self.assertEqual(package_retry['source']['commit'], self.first)
        with self.assertRaises(ki2ci.CiError):
            server.submit('publish', source='git', commit=self.first)
        with self.assertRaises(ki2ci.CiError):
            server.submit_package('unknown', source='git', commit=self.first)
        self.assertFalse(any(j['status']=='pending' and j.get('package')=='unknown' for j in server.store.list()))
        page = git_page(self.sources.status())
        self.assertIn(second, page)
        self.assertIn('action="/git/sync"', page)
        handler = object.__new__(ki2ci.make_handler(server))
        self.assertIn(self.first.encode(), handler.package_build_page('git', self.first))

    def test_sync_requests_serialize(self):
        self.sources.operation.acquire()
        try:
            with self.assertRaises(GitError):
                self.sources.start_sync()
        finally:
            self.sources.operation.release()

    def test_latest_build_fetches_at_execution_and_retry_pins_actual_commit(self):
        self.sources.sync()
        config = ki2ci.CiConfig(Path(__file__).resolve().parents[1], self.root/'latest-build', 'x86_64', 1, 'test', self.root/'publish')
        server = ki2ci.BuildServer(config);server.git = self.sources
        self.addCleanup(server.close)
        with mock.patch.object(server, '_start_worker'):
            job = server.submit_package('fixture')
        self.assertEqual(job['source']['kind'], 'git-latest')
        self.assertFalse((server.store.jobs_dir/job['id']/'source').exists())
        second = self.commit('two')
        code = "from pathlib import Path; assert Path('version.txt').read_text() == 'two'"
        steps = [ki2ci.Step('actual source', [sys.executable, '-c', code])]
        with mock.patch.object(ki2ci, 'package_build_steps', return_value=steps):
            ki2ci.run_job(config, server.store, job['id'], git_sources=self.sources)
        actual = server.store.read(job['id'])
        self.assertEqual(actual['status'], 'succeeded')
        self.assertEqual(actual['source']['commit'], second)
        self.assertEqual(actual['source_request']['viewed_commit'], self.first)
        self.commit('three')
        with mock.patch.object(server, '_start_worker'):
            retry = server.retry(job['id'])
        with mock.patch.object(self.sources, 'sync', side_effect=AssertionError('retry must not fetch newer source')):
            with mock.patch.object(ki2ci, 'package_build_steps', return_value=steps):
                ki2ci.run_job(config, server.store, retry['id'], git_sources=self.sources)
        self.assertEqual(server.store.read(retry['id'])['status'], 'succeeded')
        self.assertEqual(retry['source']['commit'], second)

    def test_latest_fetch_failure_never_executes_preserved_source(self):
        self.sources.sync()
        config = ki2ci.CiConfig(Path(__file__).resolve().parents[1], self.root/'failed-fetch', 'x86_64', 1, 'test', self.root/'publish')
        server = ki2ci.BuildServer(config);server.git = self.sources
        self.addCleanup(server.close)
        with mock.patch.object(server, '_start_worker'):
            job = server.submit_package('fixture')
        self.git('branch', '-m', 'gone')
        with mock.patch.object(ki2ci, 'run_step') as run:
            ki2ci.run_job(config, server.store, job['id'], git_sources=self.sources)
        run.assert_not_called()
        self.assertEqual(server.store.read(job['id'])['status'], 'failed')

    def test_http_sync_status_and_commit_catalog(self):
        repo = Path(__file__).resolve().parents[1]
        config = ki2ci.CiConfig(repo, self.root / 'http-build', 'x86_64', 1, 'test', self.root / 'publish')
        server = ki2ci.BuildServer(config)
        self.addCleanup(server.close)
        server.git = self.sources
        handler = ki2ci.make_handler(server)
        handler.log_message = lambda *args: None
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        def request(method, path, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', httpd.server_port)
            headers = {'Content-Type':'application/x-www-form-urlencoded'} if body else {}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result
        try:
            self.assertEqual(request('POST', '/git/sync', 'action=sync')[0], 303)
            for _ in range(100):
                status, body = request('GET', '/api/git')
                state = json.loads(body)
                if not state['busy']:
                    break
                time.sleep(.05)
            self.assertEqual(state['status'], 'ready')
            self.assertEqual(state['current']['commit'], self.first)
            status, page = request('GET', '/git')
            self.assertEqual(status, 200)
            self.assertIn(self.first.encode(), page)
            status, page = request('GET', '/package-build?source=git&commit=' + self.first)
            self.assertEqual(status, 200)
            self.assertIn(b'value=\'fixture\'', page)
            self.assertEqual(request('GET', '/package-build?source=git&commit=' + 'f'*40)[0], 400)
            status, page = request('GET', '/package-build')
            self.assertEqual(status, 200)
            self.assertIn(b"name='source' value='git-latest'", page)
            status, page = request('GET', '/kernel-build')
            self.assertEqual(status, 200)
            self.assertIn(b'Linux 6.1.187-2', page)
            with mock.patch.object(server, '_start_worker'):
                self.assertEqual(request('POST', '/kernel-build', 'package=fixture')[0], 303)
            self.assertEqual(server.store.list()[0]['package'], 'linux')
            self.assertEqual(server.store.list()[0]['source']['kind'], 'git-latest')
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
