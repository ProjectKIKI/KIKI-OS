#!/usr/bin/env python3
"""Publish signed KI2 snapshots atomically and serve a read-only repository."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import html
import json
import os
from pathlib import Path
import re
import shutil
import threading
import uuid
from http.server import ThreadingHTTPServer

import ki2http
import ki2origins


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', value) is not None


def save(path, value):
    pending = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(pending, path)


class Repository:
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.root = Path(config['store'])
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.root / 'versions').mkdir(exist_ok=True)
        self.records = json.loads((self.root / 'state.json').read_text()) if (self.root / 'state.json').exists() else {}
        self.allowed, self.checked, self.source_checks = {}, {}, {}
        self.lease = (self.root / 'publisher.lock').open('a+b')
        try:
            fcntl.flock(self.lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise

    def publish(self, source, channel):
        name = channel.get('version', source.name)
        if not valid_id(name) or not valid_id(channel['name']):
            raise ValueError('invalid repository version/channel')
        public = source / channel.get('key_file', 'candidate.pub')
        if ki2http.sha(public) != channel['key_sha256']:
            raise ValueError('untrusted signing key: ' + name)
        metadata = source / 'repo/metadata.x86_64.json'
        index = source / 'repo/index.x86_64.json'
        identity = [ki2http.sha(metadata), ki2http.sha(index), ki2http.sha(public)]
        key = channel['name'] + '/' + name
        old = self.records.get(key)
        if old:
            if old['identity'] != identity:
                raise ValueError('immutable published version changed: ' + key)
            return old
        stage = self.root / 'versions' / ('.pending-' + uuid.uuid4().hex)
        stage.mkdir()
        try:
            (stage / 'repo').mkdir()
            (stage / 'packages/x86_64').mkdir(parents=True)
            shutil.copyfile(metadata, stage / 'repo' / metadata.name)
            shutil.copyfile(index, stage / 'repo' / index.name)
            shutil.copyfile(public, stage / 'desktop-installer.ed25519.pub')
            rows = json.loads(index.read_bytes())['packages']
            packages = source / channel.get('packages', 'packages')
            for row in rows:
                filename = row['file']
                if filename != Path(filename).name or '\\' in filename or not filename.endswith('.ki2'):
                    raise ValueError('unsafe package filename')
                original = packages / filename
                if original.is_symlink() or not original.resolve(strict=True).is_relative_to(packages.resolve(strict=True)):
                    raise ValueError('package escaped source')
                target = stage / 'packages/x86_64' / filename
                # Snapshot objects are immutable. Same-filesystem links avoid copying hundreds of MiB.
                try:
                    os.link(original, target)
                except OSError:
                    shutil.copyfile(original, target)
            ki2http.inventory(stage, stage / 'desktop-installer.ed25519.pub', self.client)
            destination = self.root / 'versions' / (channel['name'] + '--' + name)
            if destination.exists():
                # Recover an interrupted state.json commit without replacing the published tree.
                if ki2http.sha(destination / 'repo/metadata.x86_64.json') != identity[0]:
                    raise ValueError('existing version differs')
                ki2http.inventory(destination, destination / 'desktop-installer.ed25519.pub', self.client)
            else:
                stage.rename(destination)
            record = {'id': name, 'channel': channel['name'], 'identity': identity,
                      'packages': len(rows), 'created_at': json.loads(metadata.read_bytes())['created_at'],
                      'published_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'release_ready': False}
            self.records[key] = record
            save(self.root / 'state.json', self.records)
            return record
        finally:
            # stage is always a locally generated child of this publisher's versions directory.
            if stage.exists():
                shutil.rmtree(stage)

    def scan(self):
        errors = []
        self.channel_selections={}
        for channel in self.config['channels']:
            selected=None
            if channel.get('selection_file'):
                path=Path(channel['selection_file'])
                if not path.exists():continue
                selected=json.loads(path.read_text()).get('version','')
                if not valid_id(selected):raise ValueError('invalid selected repository version')
                self.channel_selections[channel['name']]=selected
            sources = sorted(Path(channel['sources']).glob(channel.get('pattern', '*')))
            for source in sources:
                if selected and source.name!=selected:continue
                if source.name.startswith('.') or not source.is_dir():
                    continue
                if not (source / 'repo/metadata.x86_64.json').is_file():
                    continue
                try:
                    self.publish(source, channel)
                except Exception as error:
                    errors.append({'channel': channel['name'], 'version': source.name, 'error': str(error)})
        self.rebuild_routes(errors)
        save(self.root / 'last-scan.json', {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'errors': errors,
                                          'published_versions': len(self.records)})
        return errors

    def rebuild_routes(self, errors):
        provenance=self.config.get('provenance',{})
        try:
            self.provenance_catalog=json.loads(Path(provenance['catalog']).read_text()) if provenance.get('catalog') else {}
        except (OSError,ValueError):
            self.provenance_catalog={}
            errors.append({'error':'source provenance catalog unavailable'})
        try:
            self.origin_audits=ki2origins.load_audit(provenance.get('audit_file'))
        except (OSError,ValueError,TypeError,AttributeError):
            self.origin_audits={}
            errors.append({'error':'source provenance audit unavailable'})
        self.audited_sources={r['source']['sha256']:r['source'] for r in self.origin_audits.values()
                              if isinstance(r.get('source'),dict) and r['source'].get('type')=='url' and r['source'].get('sha256')}
        allowed, versions, per_channel = {}, [], {}
        for key, row in sorted(self.records.items()):
            root = self.root / 'versions' / (row['channel'] + '--' + row['id'])
            if key not in self.checked:
                self.checked[key] = ki2http.inventory(root, root / 'desktop-installer.ed25519.pub', self.client)
            files = self.checked[key]
            files=dict(files)
            files.update(self.source_routes(row,files,allowed))
            prefix = '/ki2/versions/' + row['channel'] + '/' + row['id']
            allowed.update({prefix + path: entry for path, entry in files.items()})
            public = {k: v for k, v in row.items() if k != 'identity'}
            public.update(url=prefix, key_sha256=row['identity'][2])
            versions.append(public)
            per_channel.setdefault(row['channel'], []).append((row, files))
        channels = []
        for channel, candidates in sorted(per_channel.items()):
            candidates.sort(key=lambda pair: (pair[0]['created_at'], pair[0]['id']))
            selected=self.channel_selections.get(channel)
            if selected:candidates.sort(key=lambda pair:pair[0]['id']==selected)
            # Retain older package filenames so clients can finish an earlier plan after promotion.
            merged, fingerprints, accepted = {}, {}, []
            for row, files in candidates:
                index = json.loads(files['/repo/index.x86_64.json'][0].read_bytes())
                hashes = {'/packages/x86_64/' + p['file']: p['sha256'] for p in index['packages']}
                conflicts = [p for p, digest in hashes.items() if p in fingerprints and fingerprints[p] != digest]
                if conflicts:
                    errors.append({'channel': channel, 'version': row['id'], 'error': 'same package filename has different bytes; channel promotion refused'})
                    continue
                fingerprints.update(hashes)
                merged.update(files)
                accepted.append(row)
            if accepted:
                allowed.update({'/ki2/' + channel + path: entry for path, entry in merged.items()})
                channels.append({'name': channel, 'version': accepted[-1]['id'], 'url': '/ki2/' + channel,
                                 'key_sha256': accepted[-1]['identity'][2], 'packages': accepted[-1]['packages']})
        catalog = {'schema': 'ki2-public-repositories-v1', 'channels': channels, 'versions': versions}
        save(self.root / 'repositories.json', catalog)
        links = ''.join('<li><b>' + html.escape(c['name']) + '</b> · ' + str(c['packages']) + ' packages · ' + html.escape(c['version']) + ' · <a href="'+html.escape(c['url']+'/sources.html')+'">패키지 출처 보기</a> · <a href="'+html.escape(c['url']+'/repo/index.x86_64.json')+'">패키지 인덱스</a></li>' for c in channels)
        (self.root / 'index.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>KIKI 패키지 저장소</title><h1>KIKI 패키지 저장소</h1><p>빌드 후보 · Ed25519 서명 검증 필요 · 공식 릴리스 아님</p><ul>' + links + '</ul><a href="/ki2/repositories.json">버전 목록과 공개키 SHA-256</a></html>', encoding='utf-8')
        for route, file in [('/ki2/', 'index.html'), ('/ki2/repositories.json', 'repositories.json')]:
            path = self.root / file
            st = path.stat()
            allowed[route] = (path, (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns))
        # Readers see a complete generation; a failed publication preserves previous versions.
        self.allowed = allowed

    def source_routes(self,version,files,allowed):
        config=self.config.get('provenance',{})
        binaries=self.provenance_catalog.get('binaries',{})
        rows=[]
        for package in json.loads(files['/repo/index.x86_64.json'][0].read_bytes())['packages']:
            digest=package['sha256']
            record=config.get('overrides',{}).get(digest,binaries.get(digest,{}))
            if any(str(record.get(k,''))!=str(package.get(k,'')) for k in ['name','version','release']):record={}
            record=ki2origins.audited_record(package,record,self.origin_audits)
            origin=ki2origins.source_origin(record)
            archive=self.source_archive(origin,allowed)
            rows.append({k:package[k] for k in ['name','version','release','sha256']})
            rows[-1].update(origin=origin,archive_url=archive)
        rows.sort(key=lambda row:row['name'].casefold())
        folder=self.root/'origin-pages'/(version['channel']+'--'+version['id'])
        folder.mkdir(parents=True,exist_ok=True)
        result={}
        payload={'schema':'ki2-source-origins-v1','channel':version['channel'],'version':version['id'],'packages':rows}
        for route,name,data in [('/sources.html','sources.html',ki2origins.page(version['channel'],rows)),
                                ('/sources.json','sources.json',json.dumps(payload,ensure_ascii=False,indent=2)+'\n')]:
            path=folder/name
            self.write_public_file(path,data)
            result[route]=self.file_entry(path)
        script=self.root/'sources.js'
        self.write_public_file(script,ki2origins.SCRIPT)
        allowed['/ki2/sources.js']=self.file_entry(script)
        return result

    @staticmethod
    def write_public_file(path,data):
        if path.exists() and path.read_text(encoding='utf-8')==data:return
        pending=path.with_name('.'+path.name+'-'+uuid.uuid4().hex)
        pending.write_text(data,encoding='utf-8');os.replace(pending,path)

    @staticmethod
    def file_entry(path):
        st=path.stat()
        return path,(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)

    def source_archive(self,origin,allowed):
        if origin['kind'] not in {'upstream','local'}:return ''
        if origin['kind']=='upstream' and not origin['url']:return ''
        digest=origin['sha256']
        record=self.provenance_catalog.get('sources',{}).get(digest)
        config=self.config.get('provenance',{})
        objects=config.get('objects')
        if not record and digest in self.audited_sources:
            record=self.audited_sources[digest]
            objects=config.get('audit_objects')
        if not record or not objects:return ''
        filename=re.sub('[^A-Za-z0-9._+~-]','_',Path(self.audited_sources.get(digest,record).get('file','')).name)
        if not filename.endswith(('.tar.xz','.tar.gz','.tar.bz2','.tar.zst','.tar','.tgz','.zip','.pem')):return ''
        path=Path(objects)/digest
        if path.is_symlink() or not path.is_file():return ''
        entry=self.file_entry(path)
        if self.source_checks.get(digest)!=entry[1]:
            if ki2http.sha(path)!=digest:return ''
            self.source_checks[digest]=entry[1]
        route='/ki2/sources/'+digest+'/'+filename
        allowed[route]=entry
        return route

    def get(self, route):
        match=re.fullmatch(r'/ki2/build-iso/([a-f0-9]{32})/([a-f0-9]{64})\.part',route)
        jobs=self.config.get('cloud_iso_jobs')
        if match and jobs:
            folder=Path(jobs)/match[1]/'cloud-artifact';index=folder/'index.json';path=folder/(match[2]+'.part')
            try:
                if folder.parent.is_symlink() or folder.is_symlink() or index.is_symlink() or path.is_symlink() or not folder.resolve().is_relative_to(Path(jobs).resolve()):return None
                metadata=json.loads(index.read_text())
                part=next((p for p in metadata['parts'] if p['sha256']==match[2]),None)
                if not part or not 0<part['bytes']<=256*1024**2:return None
                entry=self.file_entry(path)
                if entry[1][2]!=part['bytes']:return None
                if self.source_checks.get(str(path))!=entry[1]:
                    if ki2http.sha(path)!=match[2]:return None
                    self.source_checks[str(path)]=entry[1]
                return entry
            except (OSError,ValueError,KeyError,TypeError):return None
        return self.allowed.get(route)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8097)
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(args.config.read_text())
    repository = Repository(config, args.client)
    repository.scan()
    stop = threading.Event()
    def refresh():
        while not stop.wait(config.get('interval_seconds', 15)):
            try:
                errors = repository.scan()
                if errors:
                    print(json.dumps({'publication_errors': errors}), flush=True)
            except Exception as error:
                print(json.dumps({'publication_error': str(error)}), flush=True)
    worker = threading.Thread(target=refresh, daemon=True)
    worker.start()
    handler = ki2http.handler(repository)
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        try:
            server.serve_forever()
        finally:
            stop.set()


if __name__ == '__main__':
    main()
