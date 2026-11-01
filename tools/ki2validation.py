"""현재 후보와 서명된 검증 증적을 다시 대조하는 읽기 전용 통합 화면."""
import json
from html import escape
from ki2buildops import sha


def inventory(lib):
    rows=[]
    for proposal in lib.updates.list():
        gates=dict(build='미완료',signature='미검증',vm='미검증',reboot='미검증',gui='미검증',scap='미검증')
        error=''
        if proposal.get('snapshot'):gates['build']='후보 생성됨'
        if proposal.get('validation'):
            try:
                manifest=lib.root/'snapshots'/proposal['snapshot']/'manifest.json'
                if sha(manifest)!=proposal['candidate_manifest_sha256']:raise ValueError('현재 후보 명세 해시가 검증 입력과 다릅니다.')
                current,report,digest=lib.updates.validate_report(proposal['id'])
                if digest!=proposal['validation']['sha256']:raise ValueError('검증 보고서가 승인 후 변경되었습니다.')
                if current.get('candidate_manifest_sha256')!=proposal.get('candidate_manifest_sha256'):raise ValueError('후보 입력 변경')
                checks=report['checks']
                gates.update(signature='통과',vm='통과',reboot='통과' if checks.get('rebooted') is True else '미검증',
                             gui='통과' if checks.get('gnome_session') is True else '미검증')
                gates['scap']='통과' if checks.get('security_scan_executed') is True and proposal.get('security_policy') else '정책·검사 미확인'
            except (ValueError,OSError,KeyError) as exc:error=str(exc)
        rows.append(dict(kind='업데이트',id=proposal['id'],package=proposal['package'],
                         snapshot=proposal.get('snapshot',''),plan_sha256=proposal.get('plan_sha256','미기록'),
                         manifest_sha256=proposal.get('candidate_manifest_sha256','미기록'),gates=gates,error=error,
                         all_checks_verified=all(value in {'통과','후보 생성됨'} for value in gates.values()),
                         href='/updates/'+proposal['id']))
    for job in lib.jobs():
        if job.get('kind')!='iso':continue
        result=job.get('result') or {}
        cloud_path=lib.root/'jobs'/job['id']/'cloud-deploy.json'
        cloud=json.loads(cloud_path.read_text()) if cloud_path.is_file() else {}
        rows.append(dict(kind='ISO',id=job['id'],snapshot=result.get('snapshot',job.get('values',{}).get('snapshot','')),
                         iso_sha256=result.get('sha256','미기록'),
                         manifest_sha256=result.get('snapshot_manifest_sha256','미기록'),
                         gates=dict(build='생성 완료' if job['status']=='succeeded' else job['status'],
                                    vm='설치 보고 상태: '+str(cloud.get('status','미등록'))+' · 원본 증적 확인 필요',gui='사용자 세션 증적 미연결'),
                         all_checks_verified=False,error='',href='/iso-build/jobs/'+job['id']))
    return dict(schema='kiki-validation-overview-v1',rows=rows,automatic_promotion=False)


def page(lib,render):
    data=inventory(lib)
    body='<div class="panel"><h2>릴리즈 검증 결과 통합</h2><p>후보·계획 해시와 현재 서명 증적을 다시 대조합니다. 미검증·누락·변경된 결과를 통과로 표시하지 않습니다. 이 화면은 자동 승격하지 않습니다.</p><p>업데이트 VM 검증과 ISO 새 설치 검증은 별개입니다. GUI 항목은 기존 검증 계약의 로그인 화면 검사이며, 로그인한 사용자 세션 인증은 아닙니다.</p></div>'
    for row in data['rows']:
        e=lambda value:escape(str(value),quote=True)
        body+='<section class="panel"><h3>'+e(row['kind'])+' · <a href="'+e(row['href'])+'">'+e(row['id'])+'</a></h3>'
        body+='<p>스냅샷 '+e(row['snapshot'])+'</p><dl>'
        for key,label in [('plan_sha256','빌드 계획 SHA'),('manifest_sha256','후보 명세 SHA'),('iso_sha256','ISO SHA')]:
            if key in row:body+='<dt>'+label+'</dt><dd><code>'+e(row[key])+'</code></dd>'
        body+='</dl><table><tr><th>검사</th><th>현재 결과</th></tr>'
        labels=dict(build='패키지·ISO 생성',signature='증적 서명·후보 일치',vm='VM 적용',reboot='재부팅',gui='GUI 로그인 화면',scap='OpenSCAP 설정 검사')
        body+=''.join('<tr><td>'+labels.get(key,key)+'</td><td>'+e(value)+'</td></tr>' for key,value in row['gates'].items())+'</table>'
        if row['error']:body+='<p role="alert">'+e(row['error'])+'</p>'
        body+='<p>'+('표시한 필수 검사 통과 · 승격은 기존 승인 절차에서 수행' if row['all_checks_verified'] else '검증 미완료 · 상세 기록 확인 필요')+'</p></section>'
    if not data['rows']:body+='<p>등록된 후보와 ISO가 없습니다.</p>'
    return render('릴리즈 검증 결과',body)
