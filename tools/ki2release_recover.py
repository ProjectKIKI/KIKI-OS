#!/usr/bin/env python3
"""Reconstruct a lost version catalog from verified immutable candidate inputs.

Run with the release service stopped. Existing objects, snapshots, installers,
keys and history are retained. This command never downloads or builds packages.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.parse
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
from ki2release import Library,read,save,sha,validate_catalog


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,default=Path('/release-store'))
    args=parser.parse_args();root=args.store
    import fcntl
    with (root/'worker.lock').open('a+b') as lease:
        fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        recovery=root/('recovery-'+uuid.uuid4().hex);recovery.mkdir()
        if (root/'catalog.json').exists():shutil.copy2(root/'catalog.json',recovery/'catalog.original.json')
        objects={p.name:p for p in (root/'objects').iterdir() if re.fullmatch('[0-9a-f]{64}',p.name)}
        for expected,path in objects.items():
            if sha(path)!=expected:raise ValueError('보관 객체 SHA 불일치: '+expected)
        sys.path.insert(0,'/backend/tools')
        import ki2repo
        for path in (root/'snapshots').glob('*/manifest.json'):
            if path.parent.name.startswith('.'):continue
            snapshot=read(path)
            if (sha(path.parent/'repo/index.x86_64.json')!=snapshot['index_sha256']
                    or sha(path.parent/'repo/metadata.x86_64.json')!=snapshot['metadata_sha256']
                    or not ki2repo.verify_metadata_file(path.parent/'repo/metadata.x86_64.json',path.parent/'candidate.pub')):
                raise ValueError('기존 스냅샷 SHA·서명 불일치: '+path.parent.name)
        library=Library(recovery/'empty','/backend','/inputs/baseline','/sources','/native-packages')
        library.root=root
        persist=library.commit
        library.commit=lambda:None
        # Synchronization restores baseline, completed jobs, native pair, and
        # locked source inputs without replacing any existing snapshot.
        library.synchronize()
        for binary in list(library.catalog['binaries'].values()):
            source=binary.get('source',{});key=source.get('sha256','')
            if key in objects and key not in library.catalog['sources']:
                url=source.get('url','')
                library.catalog['sources'][key]={'sha256':key,'file':Path(urllib.parse.urlsplit(url).path).name,
                    'url':url,'size':objects[key].stat().st_size,'verified_at':'recovery SHA verified'}
        validate_catalog(library.catalog,root)
        referenced=set(library.catalog['binaries'])|set(library.catalog['sources'])
        if referenced!=set(objects):raise ValueError('복구 목록과 보관 객체의 연결이 일치하지 않습니다. 파일은 보존했습니다.')
        if set(library.catalog['binaries'])!={p.stem for p in (root/'manifests').glob('*.json')}:
            raise ValueError('복구한 바이너리와 기존 파일 명세의 연결이 다릅니다.')
        persist()
        report={'passed':True,'objects_sha_verified':len(objects),'binaries':len(library.catalog['binaries']),
                'sources':len(library.catalog['sources']),'snapshots':len(library.snapshots()),
                'original_catalog_backup':str(recovery/'catalog.original.json'),
                'existing_objects_removed':False,'existing_snapshots_replaced':False}
        save(recovery/'result.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
