"""A unified, read-only view of immutable artifacts and completed CI output."""
from html import escape
from urllib.parse import quote,urlencode
import json
import re


def inventory(lib):
    items=[]
    for kind,key in [('package','binaries'),('source','sources')]:
        for digest,record in lib.catalog.get(key,{}).items():
            if not re.fullmatch('[a-f0-9]{64}',digest):continue
            items.append(dict(kind=kind,name=record.get('name',record.get('file','')),file=record.get('file',''),sha256=digest,
                version=str(record.get('version',''))+'-'+str(record.get('release','')),bytes=record.get('size',0),
                validation=record.get('validation','소스 SHA 고정' if kind=='source' else '미검증'),
                url='/library/files/'+('binary' if kind=='package' else 'source')+'/'+digest,
                manifest_url='/library/files/manifest/'+digest if kind=='package' else '',job=record.get('provenance',{}).get('job_id','')))
    imported={row['job'] for row in items if row['job']}
    seen=set()
    for root in {lib.backend,lib.legacy_backend}:
        for metadata in sorted((root/'build/ki2ci/jobs').glob('*/metadata.json'),reverse=True)[:200]:
            try:
                job=json.loads(metadata.read_text());identifier=job['id']
                if identifier in seen or identifier in imported or job.get('status')!='succeeded' or not re.fullmatch(r'\d{8}-\d{6}-\d{4}',identifier):continue
                seen.add(identifier)
                for file in sorted((metadata.parent/'packages/x86_64').glob('*.ki2')):
                    if file.is_symlink() or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.ki2',file.name):continue
                    items.append(dict(kind='package',name=job.get('package',''),file=file.name,sha256='',version='',bytes=file.stat().st_size,
                        validation='빌드 완료 · 보관소 동기화 전',url='/jobs/'+identifier+'/artifacts/'+file.name,manifest_url='',job=identifier))
            except (OSError,ValueError,KeyError):continue
    for job in lib.jobs():
        if job.get('kind')!='iso':continue
        result=job.get('result') or {}
        if job.get('status')!='succeeded' or not result.get('file'):continue
        identifier=job['id'];cloud_file=lib.root/'jobs'/identifier/'cloud-deploy.json'
        cloud=json.loads(cloud_file.read_text()) if cloud_file.exists() else {}
        validation='설치 검증 통과' if result.get('fresh_install_tested') and cloud.get('status')=='passed' else '설치 검증 점검 필요' if cloud.get('status') in ['failed','needs-review'] else 'ISO 빌드 완료 · 설치 검증 대기'
        items.append(dict(kind='iso',name=result['file'],file=result['file'],sha256=result.get('sha256',''),version=job.get('values',{}).get('release_version',''),bytes=result.get('bytes',0),validation=validation,
            url='/iso-build/jobs/'+identifier+'/file',manifest_url='/iso-build/jobs/'+identifier+'/report',job=identifier,
            report_url='/iso-build/jobs/'+identifier+'/cloud-report' if cloud else '',job_url='/iso-build/jobs/'+identifier))
    return dict(schema='kiki-artifact-index-v1',items=items,counts={kind:sum(i['kind']==kind for i in items) for kind in ['package','iso','source']})


def page(lib,render,query):
    e=lambda v:escape(str(v),quote=True)
    query={k:v[0] if isinstance(v,list) else v for k,v in query.items()}
    data=inventory(lib);term=query.get('q','').strip().lower();kind=query.get('kind','all')
    rows=[i for i in data['items'] if (kind=='all' or i['kind']==kind) and (not term or term in (' '.join(str(i.get(k,'')) for k in ['name','file','version','job','sha256'])).lower())]
    body="<link rel='stylesheet' href='/catalog-ui.css'><div class='panel'><div class='catalog-heading'><div><h2>산출물 목록</h2><p>패키지·소스 보관소와 작업별 ISO·완료 패키지를 함께 조회합니다.</p></div><a href='/versions'>버전 스냅샷</a></div>"
    body+='<p>'+ ' · '.join(label+' '+str(data['counts'][key])+'개' for key,label in [('package','패키지 파일'),('iso','ISO'),('source','소스 압축파일')])+'</p>'
    body+="<form class='catalog-search' method='get' action='/artifacts'><div class='catalog-field'><label for='artifact-query'>이름·버전·작업·SHA 검색</label>"+f"<input id='artifact-query' name='q' value='{e(query.get('q',''))}'></div><div class='catalog-field'><label for='artifact-kind'>종류</label><select id='artifact-kind' name='kind'>"+''.join(f"<option value='{v}'{' selected' if kind==v else ''}>{label}</option>" for v,label in [('all','전체'),('package','패키지'),('iso','ISO'),('source','소스')])+"</select></div><button>검색</button><a href='/artifacts'>초기화</a></form>"
    try:current=int(query.get('page','1'))
    except ValueError:current=1
    total=max(1,(len(rows)+49)//50);current=max(1,min(current,total))
    pagination="<div class='catalog-pagination' role='navigation' aria-label='산출물 페이지'>"
    for number,label in [(current-1,'이전'),(current+1,'다음')]:
        if 1<=number<=total:pagination+=f"<a href='/artifacts?{e(urlencode(dict(q=query.get('q',''),kind=kind,page=number)))}'>{label}</a> "
    pagination+=f"<span>{current} / {total} 페이지 · 페이지당 50개</span></div>"
    body+=f"<p role='status'>{len(rows)}개 검색 결과 · 빌드 완료와 설치 검증 결과를 구분합니다.</p>"+pagination+"<table><tr><th>산출물</th><th>종류·버전</th><th>크기</th><th>검증 상태</th><th>작업</th></tr>"
    labels={'package':'패키지','source':'소스','iso':'ISO'}
    for i in rows[(current-1)*50:current*50]:
        links=f"<a href='{e(i['url'])}'>다운로드</a>"
        if i.get('manifest_url'):links+=f" · <a href='{e(i['manifest_url'])}'>명세</a>"
        if i.get('report_url'):links+=f" · <a href='{e(i['report_url'])}'>VM 보고서</a>"
        job_url=i.get('job_url') or ('/jobs/'+i['job'] if i['job'] else '')
        body+=f"<tr><td><b>{e(i['file'])}</b><br><small>{e(i['sha256'] or '보관소 동기화 후 SHA 표시')}</small><br>{links}</td><td>{labels[i['kind']]}<br>{e(i['version'])}</td><td>{i['bytes']/1024**2:,.1f} MiB</td><td>{e(i['validation'])}</td><td>"+(f"<a href='{e(job_url)}'>{e(i['job'])}</a>" if job_url else '보관소 등록')+'</td></tr>'
    if not rows:body+="<tr><td colspan='5'>검색 결과가 없습니다.</td></tr>"
    return render('빌드 산출물',body+'</table>'+pagination+'</div>')
