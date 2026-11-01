#!/usr/bin/env python3
"""Serve a verified, immutable KI2 candidate over read-only loopback HTTP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path, public_key: Path, client: Path):
    root = root.resolve(strict=True)
    allowed = {}

    def add(relative):
        path = root / relative
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('repository symlink or escaped path')
        if not path.is_file():
            raise ValueError('repository entry is not a regular file')
        st = path.stat()
        allowed['/' + relative] = (path, (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns))
        return path

    metadata_path = add('repo/metadata.x86_64.json')
    metadata = json.loads(metadata_path.read_bytes())
    verifier = runpy.run_path(str(client))['verify_metadata_ed25519']
    if not verifier(metadata, public_key):
        raise ValueError('Ed25519 metadata verification failed')
    index_path = add('repo/index.x86_64.json')
    if sha(index_path) != metadata['index']['sha256']:
        raise ValueError('signed index hash mismatch')
    rows = json.loads(index_path.read_bytes())['packages']
    if len(rows) != metadata['index']['package_count'] or not rows:
        raise ValueError('package count mismatch')
    for row in rows:
        name = row['file']
        if not isinstance(name, str) or name != Path(name).name or not name.endswith('.ki2') or '\\' in name:
            raise ValueError('invalid package filename')
        relative = 'packages/x86_64/' + name
        if '/' + relative in allowed:
            raise ValueError('duplicate package filename')
        path = add(relative)
        if path.stat().st_size != row['size'] or sha(path) != row['sha256']:
            raise ValueError('package hash/size mismatch: ' + name)
    # Only the public verification key is offered; arbitrary files are never served.
    key_path = add('desktop-installer.ed25519.pub')
    if key_path.read_bytes() != public_key.read_bytes():
        raise ValueError('public verification key mismatch')
    return allowed


def handler(allowed):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'KI2HTTP/1'
        sys_version = ''

        def do_HEAD(self):
            self.respond(False)

        def do_GET(self):
            self.respond(True)

        def respond(self, body):
            entry = allowed.get(self.path)
            if entry is None:
                self.send_error(404)
                return
            path, expected = entry
            try:
                fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(fd, 'rb') as stream:
                    st = os.fstat(stream.fileno())
                    actual = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
                    if not stat.S_ISREG(st.st_mode) or actual != expected:
                        self.send_error(503, 'Repository changed; restart after verification')
                        return
                    self.send_response(200)
                    content = {'.json': 'application/json', '.html': 'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8'}
                    self.send_header('Content-Type', content.get(path.suffix, 'application/octet-stream'))
                    self.send_header('Content-Length', str(st.st_size))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    if body:
                        shutil.copyfileobj(stream, self.wfile, 1024 * 1024)
            except (OSError, ValueError):
                self.close_connection = True

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--client', type=Path, default=Path(__file__).resolve().parents[1] / 'distro/sources/ki2ctl/usr/bin/ki2ctl')
    parser.add_argument('--port', type=int, default=8096)
    args = parser.parse_args()
    allowed = inventory(args.root, args.public_key, args.client)
    print(json.dumps({'listen': '127.0.0.1', 'port': args.port, 'files': len(allowed), 'packages': len(allowed) - 3}), flush=True)
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler(allowed)) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
