#!/usr/bin/env python3
"""Validate one complete release source manifest against immutable package IDs."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from html import escape
import ki2build
from ki2origins import public_url

DEFAULT = 'distro/manifests/kiki-build-1.0.0/sources.json'


def sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):result.update(block)
    return result.hexdigest()


def local(root, relative):
    part=PurePosixPath(relative)
    if not relative or '\\' in relative or ':' in relative or part.is_absolute() or any(p in {'.','..',''} for p in relative.split('/')):
        raise ValueError('unsafe source manifest path')
    path=(root/relative).resolve(strict=True)
    if not path.is_relative_to(root):raise ValueError('source manifest path escapes repository')
    return path


def hash_value(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise ValueError('invalid SHA-256')
    return value


def validate(root, manifest, *, object_roots=()):
    root=Path(root).resolve(strict=True)
    if manifest.get('schema')!='kiki-source-manifest-v1':raise ValueError('unsupported source manifest')
    packages=manifest['packages'];selection=manifest['snapshot_packages']
    if not packages or set(packages)!=set(selection):raise ValueError('incomplete release source coverage')
    recipes=ki2build.load_recipes(root/'distro/recipes')
    counts=dict(packages=len(packages),upstream=0,local=0,bootstrap=0,recorded_recipes=0,verified_archives=0,verified_local_archives=0)
    checked=set()
    for name,row in packages.items():
        if row.get('name')!=name or row.get('sha256')!=selection[name]:raise ValueError('release package identity mismatch: '+name)
        hash_value(row['sha256']);hash_value(row['recipe_digest'])
        if name not in recipes:raise ValueError('release package absent from unified catalog: '+name)
        for dependency in row['dependencies'].get('runtime',[]):
            if dependency not in packages:raise ValueError('release runtime dependency missing: '+dependency)
        source=row['source'];kind=source['type']
        if kind not in {'url','local','bootstrap'}:raise ValueError('unclassified source: '+name)
        if source.get('url') and not public_url(source['url']):raise ValueError('invalid source URL: '+name)
        if source.get('sha256'):hash_value(source['sha256'])
        counts[{'url':'upstream','local':'local','bootstrap':'bootstrap'}[kind]]+=1
        if kind=='url':
            if not public_url(source['url']):raise ValueError('invalid upstream URL: '+name)
            digest=hash_value(source['sha256'])
            if object_roots and digest not in checked:
                objects=[Path(p)/digest for p in object_roots]
                path=next((p for p in objects if p.is_file() and not p.is_symlink()),None)
                if path is None or sha(path)!=digest:raise ValueError('missing or changed source archive: '+name)
                checked.add(digest)
        else:
            paths=source.get('paths',[])
            if kind=='local' and not paths:raise ValueError('missing local source paths: '+name)
            for relative in paths:local(root,relative)
            if kind=='bootstrap' and not row.get('provenance_note'):raise ValueError('bootstrap provenance limitations must be explicit: '+name)
            if kind=='local' and source.get('sha256') and object_roots:
                digest=source['sha256'];objects=[Path(p)/digest for p in object_roots]
                path=next((p for p in objects if p.is_file() and not p.is_symlink()),None)
                if path is None or sha(path)!=digest:raise ValueError('missing or changed local source archive: '+name)
                counts['verified_local_archives']+=1
        record=row.get('recorded_recipe')
        if record:
            path=local(root,record['path'])
            if sha(path)!=hash_value(record['sha256']):raise ValueError('recorded recipe archive changed: '+name)
            raw=json.loads(path.read_text(encoding='utf-8'))['recipes']
            if len(raw)!=1:raise ValueError('ambiguous recorded recipe: '+name)
            recipe=ki2build.normalize_recipe(raw[0],path)
            if (recipe.name,recipe.version,recipe.release,recipe.digest)!=(name,str(row['version']),str(row['release']),row['recipe_digest']):
                raise ValueError('recorded build recipe does not match package: '+name)
            counts['recorded_recipes']+=1
        else:
            # A new source commit records current inputs separately. Do not
            # fabricate a historical recipe that was never preserved.
            record=row.get('current_recipe',{})
            local(root,record.get('path',''))
            if record.get('digest')!=recipes[name].digest:raise ValueError('current recipe changed: '+name)
    for path,digest in manifest.get('build_inputs',{}).items():
        if sha(local(root,path))!=hash_value(digest):raise ValueError('native pipeline input changed: '+path)
    counts['verified_archives']=len(checked)
    return counts


def page(manifest, query=''):
    esc=lambda value:escape(str(value),quote=True)
    rows=[]
    for name,row in sorted(manifest['packages'].items()):
        if query.casefold() not in (name+' '+row['version']+' '+json.dumps(row['source'],ensure_ascii=False)).casefold():continue
        source=row['source'];kind={'url':'업스트림 소스','local':'자체 소스·설정','bootstrap':'보존 런타임 포함'}[source['type']]
        location=("<a rel='noreferrer' href='"+esc(source['url'])+"'>원본 소스</a>" if source.get('url') else '')
        location+=''.join('<br><code>'+esc(p)+'</code>' for p in source.get('paths',[]))
        if source.get('sha256'):location+='<br><code>'+esc(source['sha256'])+'</code>'
        if row.get('provenance_note'):location+='<p>'+esc(row['provenance_note'])+'</p>'
        rows.append('<tr><td>'+esc(name)+'<br>'+esc(row['version'])+'-'+esc(row['release'])+'</td><td>'+kind+'<br>'+location+'</td><td><code>'+esc(row['sha256'])+'</code></td></tr>')
    style="""<style>.source-manifest table{width:100%;table-layout:fixed}.source-manifest th:first-child{width:18%}.source-manifest th:nth-child(2){width:56%}.source-manifest code{white-space:normal;overflow-wrap:anywhere;word-break:break-all}.source-manifest input{max-width:100%;box-sizing:border-box}@media(max-width:640px){.source-manifest thead{display:none}.source-manifest tr,.source-manifest td{display:block;width:auto!important}.source-manifest tr{border-bottom:1px solid #dce2e9;padding:10px 0}.source-manifest td{border:0;padding:7px 12px}.source-manifest td:first-child{font-weight:700}.source-manifest td:last-child:before{content:'패키지 SHA-256';display:block;color:#58677a;font-size:12px}}</style>"""
    return (style+"<section class='panel source-manifest'><h2>릴리즈 전체 소스 명세</h2><p>"+str(len(manifest['packages']))+"개 패키지 · 스냅샷 "+esc(manifest['snapshot'])+
            "</p><p>빌드 입력·원본 소스 SHA·패키지 SHA를 연결합니다. 보존 런타임과 개별 라이브러리 재빌드는 구분합니다. Native SDK 빌드는 저장소의 tools/gnome_native/README.ko.md를 따릅니다.</p>"
            "<p><a href='/api/source-manifest'>통합 명세 JSON 다운로드</a></p><form action='/source-manifest' method='get'><label for='source-query'>패키지·버전·출처 검색</label><input id='source-query' name='q' value='"+esc(query)+"'><button>검색</button> <a href='/source-manifest'>초기화</a></form><p role='status'>"+str(len(rows))+"개 검색 결과</p><table><thead><tr><th>패키지</th><th>소스 출처·입력</th><th>패키지 SHA-256</th></tr></thead><tbody>"+(''.join(rows) or "<tr><td colspan='3'>검색 결과가 없습니다.</td></tr>")+"</tbody></table></section>")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--manifest',type=Path)
    p.add_argument('--objects',type=Path,action='append',default=[])
    args=p.parse_args();path=args.manifest or args.repo_root/DEFAULT
    report=validate(args.repo_root,json.loads(path.read_text(encoding='utf-8')),object_roots=args.objects)
    print(json.dumps(dict(schema='kiki-source-validation-v1',status='passed',manifest_sha256=sha(path),**report),indent=2))


if __name__=='__main__':main()
