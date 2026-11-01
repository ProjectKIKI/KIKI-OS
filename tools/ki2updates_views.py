"""Update review screens; discovery, compiling and promotion are distinct actions."""
import html
import json
import urllib.parse

LABELS={'proposed':'검토 중','preparing':'소스 확인 중','prepare-failed':'준비 실패','queued':'빌드 대기','building':'빌드 중','build-failed':'빌드 실패',
        'testing':'VM 검증 대기','validation-failed':'VM 검증 실패','validated':'검증 통과 · 승격 가능','stable':'안정 채널 배포'}
CHECKS={'signature_verified':'저장소 서명·인덱스','offline_apply_succeeded':'오프라인 적용·후처리 완료','package_inventory':'설치 패키지 해시','user_config_preserved':'사용자 설정 보존',
        'services_healthy':'서비스 상태','rebooted':'재부팅','gnome_session':'GNOME Wayland 로그인 화면','kernel_recovery':'복구 커널 부팅·기본 커널 복귀',
        'updated_kernel':'새 커널 실행','default_tls_trust':'기본 HTTPS 인증서 경로','acl_runtime':'ACL 실제 읽기·쓰기','security_scan_executed':'OpenSCAP 설정 검사 실행·정책 일치'}
SCAP_LABELS={'passwd_permissions':'passwd 소유권·권한','shadow_permissions':'shadow 소유권·권한','root_uid_unique':'UID 0 계정','ssh_root_login':'SSH root 직접 로그인 차단','ssh_empty_password':'SSH 빈 암호 인증 차단','hardlinks':'하드링크 보호','symlinks':'심볼릭 링크 보호','time_sync':'시간 동기화','firewall':'방화벽 기본 차단'}
SCAP_STATES={'pass':'통과','fail':'설정 불일치','error':'관측 오류','unknown':'미확인','notapplicable':'비해당','notchecked':'미검사'}
def esc(v):return html.escape(str(v),quote=True)
def link(row):return '/updates/'+row['id']
def form(action,label):return f"<form method='post' action='{esc(action)}'><input type='hidden' name='action' value='submit'><button>{esc(label)}</button></form>"

def index(manager,render,q):
    checks=manager.checks();notifications=[n for n in checks['notifications'] if not n['read']];config=manager.config();stable=manager.stable()
    body=f"<section class='panel'><h2>업데이트 관리</h2><p>새 버전 확인 → 고정된 후보 빌드 → 기존 설치 VM 업그레이드 → 재부팅·GUI 확인 → 안정 채널 승격</p><p>새 알림 <b>{len(notifications)}</b>개 · 마지막 확인 {esc(checks.get('checked_at') or '아직 확인하지 않음')} · 주기 {int(config.get('interval_seconds',21600))//3600}시간</p><p>안정 채널: {esc(stable.get('version','아직 승격하지 않음'))}</p>"
    body+=form('/updates/check','지금 새 버전 확인')+form('/updates/acknowledge','알림 모두 읽음')+"<a href='/updates/new'>업데이트 후보 직접 준비</a></section>"
    security_result=manager.security.result();unread=sum(not n['read'] for n in security_result.get('notifications',[]))
    body+=f"<section class='panel'><h2>CVE·설정 보안 검사</h2><p>CVE 알림 {unread}개 · 마지막 조회 {esc(security_result.get('checked_at','아직 조회하지 않음'))}</p><a href='/updates/security'>취약점·검사 범위 확인</a><p>패키지 취약점과 VM 보안 설정을 함께 확인합니다. 매핑 누락·조회 실패를 정상으로 처리하지 않습니다.</p></section>"
    for n in notifications[-10:]:body+=f"<p class='notice'>{esc(n['name'])} {esc(n['version'])} 새 버전 발견 · 자동 배포하지 않았습니다.</p>"
    term=q.get('q',[''])[0].lower();state=q.get('status',[''])[0]
    body+=f"<section class='panel'><h2>원본 버전 확인 결과</h2><form method='get' action='/updates'><label>패키지 검색 <input name='q' value='{esc(term)}'></label><label>상태 <select name='status'>"
    for value,label in [('', '전체'),('available','새 버전 있음'),('error','확인 실패'),('manual','직접 확인 필요')]:
        body+=f"<option value='{value}'{' selected' if state==value else ''}>{label}</option>"
    body+="</select></label><button>조회</button></form><table><tr><th>패키지</th><th>현재 → 발견한 버전</th><th>확인 결과</th><th>다음 작업</th></tr>"
    count=0
    for row in checks['rows']:
        if term and term not in row['name'].lower() or state and row['status']!=state:continue
        latest=row.get('latest') or {};labels={'available':'새 버전 있음','current':'추적 중인 안정 계열에서 새 버전 없음','manual':'직접 확인 필요','error':'확인 실패'}
        href='/updates/new?'+urllib.parse.urlencode({'package':row['name'],'version':latest.get('version',''),'url':latest.get('url',''),'base':checks.get('base','')})
        action=f"<a href='{esc(href)}'>후보 검토</a>" if latest else ''
        release=latest.get('release_url') or latest.get('url')
        if release:action+=f" · <a href='{esc(release)}' rel='noreferrer'>원본 배포</a>"
        body+=f"<tr><td>{esc(row['name'])}</td><td>{esc(row['current'])} → {esc(latest.get('version','—'))}</td><td>{labels[row['status']]}<br><small>{esc(row.get('message',''))}</small></td><td>{action}</td></tr>";count+=1
    if not count:body+="<tr><td colspan='4'>조건에 맞는 확인 결과가 없습니다.</td></tr>"
    body+="</table><p>공급자가 없는 항목과 통신 실패를 최신 버전으로 판정하지 않습니다. 확인 결과는 빌드 승인이나 원저자 서명 검증을 의미하지 않습니다.</p></section><section class='panel'><h2>업데이트 후보와 배포 이력</h2><table><tr><th>업데이트</th><th>변경</th><th>상태</th></tr>"
    for row in manager.list():body+=f"<tr><td><a href='{link(row)}'>{esc(row['package'])}</a><br><small>{esc(row['created_at'])}</small></td><td>{esc(row['from'])} → {esc(row['version'])}-{esc(row['release'])}<br>{len(row['rebuild'])}개 빌드 · 영향 {len(row['affected'])}개</td><td>{esc(LABELS[row['status']])}</td></tr>"
    return render('업데이트 관리',body+'</table></section>')

def new(manager,render,q):
    snapshots=sorted(manager.lib.snapshots(),key=lambda r:r['created_at'],reverse=True)
    base=q.get('base',[manager.config().get('baseline','')])[0] or (snapshots[0]['id'] if snapshots else '')
    _,packages=manager.baseline(base) if base else ({},{})
    wanted=q.get('package',[''])[0];version=q.get('version',[''])[0];url=q.get('url',[''])[0]
    body="<section class='panel'><h2>업데이트 후보 준비</h2><p>입력은 기준 스냅샷과 함께 고정합니다. 버전이 같으면 release가 증가합니다. 새 소스는 내려받아 SHA-256을 고정한 뒤 기존 빌드 대기열에 제출합니다.</p>"
    body+="<form method='get' action='/updates/new'><label>기준 스냅샷 <select name='base'>"+''.join(f"<option value='{esc(s['id'])}'{' selected' if base==s['id'] else ''}>{esc(s['id'])}</option>" for s in snapshots)+"</select></label><button>기준 변경</button></form>"
    body+=f"<p><a href='/assistant?package={urllib.parse.quote(wanted)}'>AI 업데이트 계획 검토</a></p>"
    options=[]
    for name,p in sorted(packages.items()):
        try:manager.recipe_for(name,p);reason=''
        except ValueError as error:reason=' · 레시피 검토 필요'
        options.append(f"<option value='{esc(name)}'{' selected' if name==wanted else ''}{' disabled' if reason else ''}>{esc(name)} · {esc(p['version'])}-{esc(p['release'])}{reason}</option>")
    body+=f"<form class='fields' method='post' action='/updates/create'><input type='hidden' name='base' value='{esc(base)}'><label>변경 패키지<select name='package'>{''.join(options)}</select></label><label>함께 갱신할 패키지<input name='additional' placeholder='예: ki2ctl, base-files'></label><label>대상 원본 버전<input name='version' value='{esc(version)}' placeholder='비워두면 현재 버전 재빌드'></label><label class='wide'>원본 소스 HTTPS 주소<input name='url' value='{esc(url)}' placeholder='같은 버전 재빌드는 비워도 됩니다'></label><label class='wide'>예상 SHA-256<input name='sha256' pattern='[a-f0-9]{{64}}' placeholder='선택 · 입력하면 일치하지 않는 소스는 거부합니다'></label><label>호환성 판단<select name='compatibility'><option value='rebuild'>의존 패키지 함께 재빌드</option><option value='compatible'>호환성 유지 · 변경 패키지만 빌드</option></select></label><label class='wide'>변경 내용·호환성 판단 근거<textarea name='notes' required minlength='8' maxlength='4000' rows='4'></textarea></label><button>변경·영향 범위 검토</button></form><p>임시 staging 복사본만 남은 레시피는 실제 원본 빌드 방식 검토 전까지 제출할 수 없습니다. 새 버전의 호환성은 별도 검토해야 합니다.</p></section>"
    return render('업데이트 후보 준비',body)

def detail(manager,render,key):
    row=manager.get(key);url=link(row)
    body=f"<section class='panel'><a href='/updates'>← 업데이트 관리</a><h2>{esc(row['package'])} 업데이트</h2><p><b>{esc(row['from'])} → {esc(row['version'])}-{esc(row['release'])}</b> · {esc(LABELS[row['status']])}</p><p>{esc(row['notes'])}</p><p>기준 {esc(row['base'])} · 빌드 {len(row['rebuild'])}개 · {'재부팅 적용 필요' if row['requires_reboot'] else '재부팅 포함 검증 필요'}</p>"
    if row.get('error'):body+=f"<p class='notice'>{esc(row['error'])}</p>"
    body+="<details><summary>영향받는 의존 패키지</summary><p>"+esc(', '.join(row['affected']) or '없음')+"</p></details><p>빌드 대상: "+esc(', '.join(row['rebuild']))+'</p>'
    if row['status'] in {'proposed','prepare-failed','build-failed'}:body+=form(url+'/build','이 입력으로 소스 확인·후보 빌드')
    if row.get('build_job'):body+=f"<p><a href='/jobs/{esc(row['build_job'])}'>기존 빌드 대기열의 작업·로그</a></p>"
    if row.get('snapshot'):
        body+=f"<p>후보 스냅샷 <code>{esc(row['snapshot'])}</code><br><a href='/ki2/versions/updates-testing/{esc(row['snapshot'])}/sources.html'>후보 소스 출처</a></p>"
        body+=form(url+'/validate','전용 VM 업그레이드 검증 요청') if row['status'] in {'testing','validation-failed'} else ''
        if row.get('validation_nonce'):
            state='서명된 검증 보고서 확인 완료' if row.get('validation') else '서명된 검증 보고서 대기'
            body+=f"<p>VM 검증 요청 {esc(row['validation_requested_at'])} · {state}</p><a href='{url}/manifest'>검증 입력 명세</a>"
            if not row.get('validation'):body+=form(url+'/accept-validation','도착한 VM 검증 결과 확인')
        if row.get('validation'):
            body+="<h3>서명된 VM 검증 결과</h3><ul>"+''.join('<li>'+esc(CHECKS.get(k,k))+' · 통과</li>' for k,v in row['validation']['checks'].items() if v is True)+'</ul>'
            body+=f"<p>검증 보고서 SHA-256 <code>{esc(row['validation']['sha256'])}</code></p>"
        if row.get('snapshot'):body+=f"<p><a href='/updates/security?base={esc(row['snapshot'])}'>이 후보의 CVE·SBOM 확인</a></p>"
        if row.get('security_policy'):
            body+=f"<p>OpenSCAP 정책 <code>{esc(row['security_policy']['sha256'])}</code> · 설정 불일치는 경고로 보존하며 검사 실행 실패는 검증 통과를 차단합니다.</p>"
        security_report=row.get('validation',{}).get('security',{})
        for phase,label in [('before','업데이트 전'),('after','업데이트 후')]:
            if phase in security_report:
                scan=security_report[phase];body+=f"<h3>{label} OpenSCAP</h3><p>{esc(scan.get('engine'))} · "+' · '.join(esc(SCAP_STATES.get(k,k))+' '+str(v) for k,v in scan.get('summary',{}).items())+'</p><ul>'
                for rule in scan.get('rules',[]):body+='<li>'+esc(SCAP_LABELS.get(rule['id'].removeprefix('xccdf_org.kiki_rule_'),rule['id']))+' · '+esc(SCAP_STATES.get(rule['result'],rule['result']))+'</li>'
                body+='</ul>'
        if security_report:body+=f"<p><a href='{url}/security-report'>서명으로 검증한 설정 검사 JSON</a></p>"
        if row['status']=='validated':body+=form(url+'/promote','검증한 후보를 안정 채널로 배포')
        if row['status']=='stable':body+="<p class='good'>안정 업데이트 채널에 승격했습니다. <a href='/ki2/stable/sources.html'>저장소 목록</a></p>"
    body+="<p>승격은 기준·후보 전체 구성 해시, 별도 검증 키의 서명, 재부팅·서비스·설정 보존·GNOME Wayland 로그인 화면·커널 복구 검사에 연결됩니다. 사용자 로그인과 앱 조작은 별도 확인 대상입니다. 검증 버튼만 눌러 통과 상태를 만들 수 없습니다.</p></section>"
    return render('업데이트 후보 검토',body)


def security(manager,render,q):
    base=q.get('base',[manager.config().get('baseline','')])[0];data=manager.security.result(base)
    term=q.get('q',[''])[0].lower();state=q.get('status',[''])[0]
    labels={'unmapped':'매핑 필요','error':'조회 실패 · 이전 결과 참고','potential':'영향 가능 · 검토 필요','no-known-match':'지원 데이터에서 일치 없음'}
    coverage=' · '.join(labels.get(k,k)+' '+str(v)+'개' for k,v in data.get('coverage',{}).items())
    body=f"<section class='panel'><a href='/updates'>← 업데이트 관리</a><h2>CVE·설정 보안 검사</h2><p>기준 <code>{esc(base)}</code> · 조회 {esc(data.get('checked_at','아직 조회하지 않음'))}</p><p>확인 결과는 원본 프로젝트·버전 기준입니다. 빌드 옵션·백포트는 별도 검토하며 일치 없음은 안전성 보증이 아닙니다.</p><p>검사 범위 {esc(coverage or '아직 확인하지 않음')}</p>"
    for action,label in [('check','지금 CVE 확인'),('acknowledge','CVE 알림 모두 읽음')]:
        body+=f"<form method='post' action='/updates/security/{action}'><input type='hidden' name='base' value='{esc(base)}'><button>{label}</button></form>"
    body+=f"<p><a href='/updates/security/sbom?base={esc(base)}'>CycloneDX SBOM 다운로드</a></p>"
    if data.get('kev_error'):body+=f"<p class='notice'>실제 악용 여부(KEV) 조회 실패: {esc(data['kev_error'])} · KEV 미표시를 미악용으로 판단하지 마세요.</p>"
    notices=[n for n in data.get('notifications',[]) if not n['read']]
    body+=f"<p>읽지 않은 CVE 알림 {len(notices)}개</p>"
    if notices:
        body+="<details><summary>최근 CVE 알림 보기</summary><ul>"
        for n in notices[-10:]:body+=f"<li>{esc(n['name'])} · {esc(n['id'])}{' · KEV 실제 악용 보고' if n.get('kev') else ''}</li>"
        body+='</ul></details>'
    body+=f"</section><section class='panel'><h2>패키지 취약점</h2><form method='get' action='/updates/security'><input type='hidden' name='base' value='{esc(base)}'><label>패키지·CVE 검색<input name='q' value='{esc(term)}'></label><label>상태<select name='status'><option value=''>전체</option>"
    for key,label in labels.items():body+=f"<option value='{key}'{' selected' if state==key else ''}>{label}</option>"
    body+="</select></label><button>조회</button></form><table><tr><th>패키지·원본 버전</th><th>판정·출처</th><th>취약점·수정 정보</th></tr>"
    count=0
    for row in data.get('rows',[]):
        if state and row['status']!=state:continue
        if term and term not in (row['name']+' '+json.dumps(row.get('findings',[]))).lower():continue
        found=[]
        findings=row.get('findings',[])
        if term and term not in row['name'].lower():findings=[f for f in findings if term in json.dumps(f).lower()]
        page=max(1,min(10000,int(q.get('finding_page',['1'])[0]))) if term else 1
        limit=25 if term else 5;start=(page-1)*limit
        if findings:found.append(f"<p>일치 {len(findings)}개 · {start+1}–{min(start+limit,len(findings))} 표시</p>")
        for f in findings[start:start+limit]:
            url='https://nvd.nist.gov/vuln/detail/'+f['id'] if f['id'].startswith('CVE-') else 'https://osv.dev/vulnerability/'+urllib.parse.quote(f['id'],safe='')
            fixed=', '.join(f.get('fixed',[])) or '데이터에 수정 경계 없음'
            severity=' · '.join(str(s.get('type','CVSS'))+' '+str(s.get('base_score') if s.get('base_score') is not None else s.get('score','')) for s in f.get('severity',[]) if s.get('score') or s.get('base_score') is not None) or '데이터에 심각도 정보 없음'
            found.append(f"<details><summary><a href='{esc(url)}' rel='noreferrer'>{esc(f['id'])}</a> · {esc(f['provider'])}{' · KEV' if f.get('kev') else ''}</summary><p>{esc(f.get('summary',''))}</p><p>수정 경계(원본 데이터): {esc(fixed)}</p><p>{esc(f.get('reason',''))}</p><p>심각도: {esc(severity)}</p>"+''.join(f"<a href='{esc(u)}' rel='noreferrer'>공식 참고 {i+1}</a> " for i,u in enumerate(f.get('references',[])[:5]))+'</details>')
        if start+limit<len(findings):
            href='/updates/security?'+urllib.parse.urlencode({'base':base,'q':term or row['name'],'finding_page':page+1 if term else 1})
            found.append(f"<p><a href='{esc(href)}'>{'다음 25개 보기' if term else '이 패키지의 전체 조회 결과'}</a></p>")
        origin='/versions?'+urllib.parse.urlencode({'q':row['name']})
        prepare='/updates/new?'+urllib.parse.urlencode({'base':base,'package':row['name']})
        body+=f"<tr><td>{esc(row['name'])}<br>{esc(row['version'])}-{esc(row['release'])}<br><a href='{esc(origin)}'>출처·보관 소스</a><br><a href='{esc(prepare)}'>수정 후보 준비</a></td><td>{esc(labels.get(row['status'],row['status']))}<br><small>{esc(row.get('message',''))}</small></td><td>{''.join(found) or '—'}</td></tr>";count+=1
    if not count:body+="<tr><td colspan='3'>조회 결과가 없거나 조건에 맞는 항목이 없습니다.</td></tr>"
    policy=manager.config().get('security',{}).get('scap')
    body+="</table></section><section class='panel'><h2>OpenSCAP 설정 검사</h2><p>전용 VM의 업데이트 전·후 설정을 검사하고 서명된 VM 보고서에 결과를 연결합니다. 자동 설정 수정은 실행하지 않습니다.</p>"
    body+=f"<p>정책: {esc(policy.get('profile'))} · SHA-256 <code>{esc(policy.get('sha256'))}</code></p>" if policy else '<p>검사 정책을 아직 배포하지 않았습니다.</p>'
    body+="<p>passwd·shadow 권한, UID 0, SSH root 컨텍스트, 실행 중 sysctl, 시간 동기화, nftables 기본 차단 정책을 검사합니다. 규칙 실패·관측 오류·미검사를 각각 보존합니다.</p></section>"
    return render('CVE·설정 보안 검사',body)
