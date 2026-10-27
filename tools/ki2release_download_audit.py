#!/usr/bin/env python3
"""Exercise real release downloads through a temporary authenticated gateway.

Uses an ephemeral test account and never opens the production authentication DB.
Run inside the release worker after a successful ISO job.
"""
import hashlib
import http.client
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ki2ci_auth as auth


def main():
    backend = http.client.HTTPConnection('127.0.0.1', 8094, timeout=30)
    backend.request('GET', '/api/releases', headers={'Host': 'localhost:18090'})
    response = backend.getresponse()
    assert response.status == 200
    catalog = json.loads(response.read()); backend.close()
    completed = [j for j in catalog['jobs'] if j['kind'] == 'iso' and j['status'] == 'succeeded']
    if not completed:
        raise RuntimeError('A completed ISO job is required')
    iso = completed[0]
    paths = []
    for name in ['llvm', 'mesa']:
        binary = max((r for r in catalog['binaries'] if r['name'] == name), key=lambda r: int(r['release']))
        source = next(r for r in catalog['sources'] if r['sha256'] == binary['source']['sha256'])
        paths.extend([('/library/files/binary/'+binary['sha256'], binary['sha256']),
                      ('/library/files/source/'+source['sha256'], source['sha256'])])
    paths.append(('/iso-build/jobs/'+iso['id']+'/file', iso['result']['sha256']))
    with tempfile.TemporaryDirectory(prefix='release-auth-audit-') as state:
        store = auth.AuthStore(state); store.bootstrap()
        password = secrets.token_urlsafe(32)
        assert store.setup((store.root/'setup-code').read_text().strip(), 'qa', password)
        server = auth.AuthHTTPServer(('127.0.0.1', 0), auth.make_handler(store,
            'http://127.0.0.1:8091', ['http://localhost:18090'], False, 'http://127.0.0.1:8094'))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        cookie = ''
        def request(method, path, data=None, stream=False):
            nonlocal cookie
            headers = {'Host': 'localhost:18090', 'Cookie': cookie}
            if data is not None:
                headers.update({'Origin': 'http://localhost:18090', 'Content-Type': 'application/x-www-form-urlencoded'})
                data = urlencode(data).encode()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=60)
            connection.request(method, path, body=data, headers=headers)
            result = connection.getresponse()
            if result.getheader('Set-Cookie'):
                cookie = result.getheader('Set-Cookie').split(';')[0]
            if stream:
                digest = hashlib.sha256(); count = 0
                for chunk in iter(lambda: result.read(1024*1024), b''):
                    digest.update(chunk); count += len(chunk)
                value = {'status': result.status, 'bytes': count, 'sha256': digest.hexdigest()}
            else:
                value = (result.status, result.read())
            connection.close(); return value
        try:
            for path, _ in paths:
                assert request('GET', path)[0] == 303
            status, body = request('GET', '/login'); assert status == 200
            csrf = re.search(rb'name=[\'"]_csrf[\'"] value=[\'"]([^\'"]+)', body)[1].decode()
            assert request('POST', '/login', {'_csrf': csrf, 'username': 'qa', 'password': password})[0] == 303
            results = []
            for path, expected in paths:
                value = request('GET', path, stream=True)
                assert value['status'] == 200 and value['sha256'] == expected, value
                results.append(dict(path=path, **value))
            store.revoke(cookie.split('=', 1)[1])
            assert request('GET', paths[0][0])[0] == 303
            report = {'passed': True, 'downloads': results, 'anonymous_blocked': True,
                      'revoked_session_blocked': True, 'production_credentials_used': False}
            Path('/release-store/download-audit.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(report, indent=2))
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
