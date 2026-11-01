"""Public, explicit source provenance; never infer an origin from package names."""
import html
import ipaddress
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit


def public_url(value):
    if not isinstance(value, str):return ''
    try:
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:return ''
        if url.hostname.lower() in {'localhost','localhost.localdomain'} or url.hostname.endswith(('.local','.internal')):return ''
        try:
            if not ipaddress.ip_address(url.hostname).is_global:return ''
        except ValueError:pass
        if any(c in value for c in '\r\n\x00'):return ''
        return value
    except ValueError:return ''


def source_origin(record):
    source=record.get('source') or {}
    if not isinstance(source,dict):source={}
    # Some native builds preserve the original archive inside their build options.
    if isinstance(source.get('source'),dict) and public_url(source['source'].get('url')):source=source['source']
    git=(record.get('provenance') or {}).get('git') or {}
    url=public_url(source.get('url'))
    digest=source.get('sha256','')
    commit=git.get('commit','')
    paths=[]
    for value in [source.get('path','')]+[v for key in ['paths','inputs'] for v in (source.get(key,[]) if isinstance(source.get(key),list) else [])]:
        path=str(value or '').replace('\\','/')
        if path and not path.startswith('/') and '..' not in PurePosixPath(path).parts and not re.match(r'^[A-Za-z]:',path) and path not in paths:paths.append(path)
    result={'kind':'bootstrap' if source.get('type')=='bootstrap' else 'upstream' if url else 'local' if source.get('type')=='local' else 'unknown',
            'url':url,'host':urlsplit(url).hostname if url else '',
            'sha256':digest if re.fullmatch('[a-f0-9]{64}',str(digest)) else '',
            'local_path':paths[0] if paths else '', 'local_paths':paths,'git_url':public_url(git.get('remote')),
            'commit':commit if re.fullmatch('[a-f0-9]{40}',str(commit)) else ''}
    if result['kind']=='unknown' and result['commit']:result['kind']='git'
    audit=record.get('origin_audit')
    if isinstance(audit,dict):
        result['audit']={k:audit[k] for k in ['checked_at','method','source_verified','note','parent_sha256'] if k in audit}
    return result


def load_audit(path):
    """Load operator-reviewed historical evidence, always keyed by package bytes."""
    if not path:return {}
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema')!='ki2-origin-audit-v1':raise ValueError('unsupported source audit schema')
    records=data.get('packages',{})
    if not isinstance(records,dict):raise ValueError('invalid source audit packages')
    for digest,record in records.items():
        if not re.fullmatch('[a-f0-9]{64}',digest) or record.get('sha256')!=digest:
            raise ValueError('source audit package hash mismatch')
        if not re.fullmatch('[a-f0-9]{64}',record.get('recipe_digest','')):
            raise ValueError('source audit recipe hash missing')
        if not all(record.get(k) is not None for k in ['name','version','release','source','origin_audit']):
            raise ValueError('incomplete source audit record')
    return records


def audited_record(package,record,audits):
    audited=audits.get(package['sha256'],{})
    if any(str(audited.get(k,''))!=str(package.get(k,'')) for k in ['name','version','release']):return record
    if audited.get('sha256')!=package['sha256']:return record
    return dict(record,source=audited['source'],origin_audit=audited['origin_audit'])


def links(origin, archive=''):
    esc=html.escape;items=[]
    if origin['url']:items.append('<a href="'+esc(origin['url'],quote=True)+'" rel="noreferrer">'+('원 프로젝트 · ' if origin['kind']=='bootstrap' else '원본 소스 · ')+esc(origin['host'])+'</a>')
    if archive:items.append('<a href="'+esc(archive,quote=True)+'">SHA-256 확인된 보관본</a>')
    for path in origin.get('local_paths',[origin['local_path']]):
        if path:items.append('<span>빌드 입력 경로 <code>'+esc(path)+'</code></span>')
    git_label='빌드 레시피 Git 저장소' if origin['kind']=='upstream' else '빌드 입력 Git 저장소'
    if origin['git_url']:items.append('<a href="'+esc(origin['git_url'],quote=True)+'" rel="noreferrer">'+git_label+'</a>')
    if origin['commit']:items.append('<span>'+('레시피 커밋' if origin['kind']=='upstream' else '빌드 커밋')+' <code>'+esc(origin['commit'])+'</code></span>')
    if origin['kind']=='local' and not origin['commit']:items.append('<span class="muted">로컬 빌드 입력 · 커밋 미기록</span>')
    if origin['kind']=='unknown':items.append('<span class="muted">출처 확인 필요</span>')
    audit=origin.get('audit',{})
    if audit:
        items.append('<span class="muted">패키지·레시피 해시 대조 완료'+(' · 원본 파일 SHA-256 확인' if audit.get('source_verified') else '')+'</span>')
        if audit.get('note'):items.append('<span>'+esc(audit['note'])+'</span>')
        if audit.get('parent_sha256'):items.append('<details><summary>이전 패키지 SHA-256</summary><code>'+esc(audit['parent_sha256'])+'</code></details>')
    if origin['sha256']:items.append('<details><summary>소스 SHA-256</summary><code>'+origin['sha256']+'</code></details>')
    return '<br>'.join(items)


def page(channel, rows):
    esc=html.escape
    entries=[]
    for row in rows:
        origin=row['origin']
        label={'upstream':'외부 원본','git':'Git 빌드','local':'자체 소스·설정','bootstrap':'보존된 외부 파일 포함','unknown':'확인 필요'}[origin['kind']]
        entries.append('<tr data-origin="'+origin['kind']+'"><td><strong>'+esc(row['name'])+'</strong><br><span class="muted">'+esc(row['version']+'-'+str(row['release']))+'</span></td><td><span class="tag">'+label+'</span><br>'+links(origin,row.get('archive_url',''))+'</td></tr>')
    audited=sum(bool(r['origin'].get('audit')) for r in rows)
    unknown=sum(r['origin']['kind']=='unknown' for r in rows)
    summary=f'전체 {len(rows)}개 · 해시 대조 {audited}개 · 출처 확인 필요 {unknown}개'
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KIKI 패키지 출처 · '''+esc(channel)+'''</title><style>
body{margin:0;background:#f6f7f9;color:#182230;font:16px/1.6 system-ui,sans-serif}main{max-width:1080px;margin:auto;padding:32px 20px}a{color:#245caa}h1{margin:12px 0}header p,.muted{color:#58677a}section{background:white;border:1px solid #dce2e9;border-radius:12px;padding:20px}input,select{font:inherit;padding:10px;border:1px solid #aebaca;border-radius:6px;max-width:100%;box-sizing:border-box}input{width:360px}label{display:inline-block;margin:0 16px 16px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:16px 12px;border-bottom:1px solid #e3e7ed}th:first-child{width:30%}code{font-size:.85em;overflow-wrap:anywhere}.tag{font-size:13px;background:#edf1f7;padding:3px 8px;border-radius:4px}summary{cursor:pointer}td a{display:inline-block;margin:3px 0}tr[hidden]{display:none}@media(max-width:640px){main{padding:16px 10px}section{padding:12px}th,td{padding:12px 6px}input{width:100%}label{display:block;margin-right:0}}
</style><main><header><a href="/ki2/">← 패키지 저장소</a><h1>패키지 출처</h1><p>'''+esc(channel)+''' · 빌드 기록에 연결된 원본 주소와 소스 파일입니다. 기록이 없는 출처는 추정하지 않습니다.</p><p>'''+summary+'''</p></header><section><label>패키지·출처 검색<br><input id="source-search" type="search" placeholder="예: gtk, GNOME, github.com" autocomplete="off"></label><label>출처 종류<br><select id="source-kind"><option value="">전체</option><option value="upstream">외부 원본</option><option value="local">자체 소스·설정</option><option value="bootstrap">보존된 외부 파일 포함</option><option value="git">Git 빌드</option><option value="unknown">출처 확인 필요</option></select></label><p id="source-count" role="status">'''+str(len(rows))+'''개 패키지</p><table><thead><tr><th>패키지 · 빌드 버전</th><th>어디에서 가져왔나요?</th></tr></thead><tbody>'''+''.join(entries)+'''</tbody></table></section><p>해시 대조는 보존된 빌드 기록과 파일의 일치 여부를 확인합니다. 원저자 서명 검증이나 모든 포함 라이브러리의 개별 소스 감사와는 별개입니다. 새 버전 확인·알림과 후보 빌드는 <a href="/updates">업데이트 관리</a>에서 확인할 수 있습니다.</p></main><script src="/ki2/sources.js" defer></script></html>'''


SCRIPT='''const search=document.getElementById('source-search'),kind=document.getElementById('source-kind');function filter(){let count=0;const term=search.value.toLocaleLowerCase();for(const row of document.querySelectorAll('tbody tr')){row.hidden=!(row.textContent.toLocaleLowerCase().includes(term)&&(!kind.value||row.dataset.origin===kind.value));if(!row.hidden)count++;}document.getElementById('source-count').textContent=count+'개 패키지';}search.addEventListener('input',filter);kind.addEventListener('change',filter);'''
