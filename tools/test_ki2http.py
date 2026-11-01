import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import ki2http
import ki2repo


class HttpRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'repo').mkdir()
        (self.root / 'packages/x86_64').mkdir(parents=True)
        self.package = self.root / 'packages/x86_64/demo-1-1.x86_64.ki2'
        self.package.write_bytes(b'signed package payload')
        index = json.dumps({'packages': [{'name':'demo','version':'1','release':'1','file': self.package.name, 'size': self.package.stat().st_size,
                                         'sha256': ki2http.sha(self.package)}]}).encode()
        (self.root / 'repo/index.x86_64.json').write_bytes(index)
        self.private = self.root / 'never-serve.pem'
        self.public = self.root / 'desktop-installer.ed25519.pub'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'Ed25519', '-out', str(self.private)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(self.private), '-pubout', '-out', str(self.public)], check=True, capture_output=True)
        metadata = {'index': {'sha256': hashlib.sha256(index).hexdigest(), 'package_count': 1}}
        self.metadata = self.root / 'repo/metadata.x86_64.json'
        self.metadata.write_text(json.dumps(ki2repo.sign_metadata_ed25519(metadata, self.private)))
        self.client = Path(__file__).resolve().parents[1] / 'distro/sources/ki2ctl/usr/bin/ki2ctl'

    def inventory(self):
        return ki2http.inventory(self.root, self.public, self.client)

    def start(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ki2http.handler(self.inventory()))
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        def cleanup():
            self.server.shutdown()
            self.server.server_close()
            worker.join()
        self.addCleanup(cleanup)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def test_download_head_and_no_directory_private_or_traversal_access(self):
        self.start()
        with urllib.request.urlopen(self.url + '/packages/x86_64/' + self.package.name) as response:
            self.assertEqual(response.read(), self.package.read_bytes())
        with urllib.request.urlopen(urllib.request.Request(self.url + '/repo/index.x86_64.json', method='HEAD')) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'')
        for path in ['/', '/repo/', '/never-serve.pem', '/repo/../never-serve.pem', '/%2e%2e/never-serve.pem', '/repo/index.x86_64.json?anything']:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(self.url + '/repo/index.x86_64.json', data=b'overwrite', method='PUT'))
        self.assertEqual(error.exception.code, 501)

    def test_tampered_signed_metadata_rejected(self):
        data = json.loads(self.metadata.read_bytes())
        data['index']['package_count'] = 2
        self.metadata.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Ed25519'):
            self.inventory()

    def test_tampered_index_and_payload_rejected(self):
        self.package.write_bytes(b'bad payload')
        with self.assertRaisesRegex(ValueError, 'package hash/size'):
            self.inventory()
        (self.root / 'repo/index.x86_64.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'index hash'):
            self.inventory()

    def test_changed_file_after_start_returns_503(self):
        self.start()
        self.package.write_bytes(b'changed')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.url + '/packages/x86_64/' + self.package.name)
        self.assertEqual(error.exception.code, 503)

    def test_symlink_rejected(self):
        self.package.unlink()
        self.package.symlink_to(self.private)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.inventory()


if __name__ == '__main__':
    unittest.main()
