"""Korean release workspace: membership, ISO history, comparison and lifecycle."""
from ki2cpu import PROFILES
from ki2release_views import esc
from ki2releases import STATES


def hidden(name,value):return f"<input type='hidden' name='{esc(name)}' value='{esc(value)}'>"
def option(value,label,selected=False):return f"<option value='{esc(value)}'{' selected' if selected else ''}>{esc(label)}</option>"
def package_version(record):return record['version']+'-'+record['release'] if record else '—'
def cpu_label(cpu):return PROFILES.get(cpu,{'label':cpu})['label']


def index(manager,render,q):
    search=q.get('q',[''])[0].lower();state=q.get('state',[''])[0];rows=[]
    for release in manager.list():
        if search and search not in (release['version']+' '+release['title']).lower():continue
        if state and state!=release['state']:continue
        jobs=manager.isos(release['version']);done=sum(j['status']=='succeeded' for j in jobs)
        targets='<br>'.join(esc(cpu_label(cpu)) for cpu in release['targets'])
        rows.append(f"<tr><td><a href='/releases/{esc(release['version'])}'><b>{esc(release['title'])}</b></a><br><code>{esc(release['version'])}</code></td><td>{STATES[release['state']]}</td><td>{targets}</td><td>완료 {done}개 / 전체 {len(jobs)}개</td><td>{esc(release['created_at'])}</td></tr>")
    states=option('','모든 상태')+''.join(option(k,v,state==k) for k,v in STATES.items())
    table_rows=''.join(rows) or '<tr><td colspan="5">조건에 맞는 릴리즈가 없습니다.</td></tr>'
    body=f"<section class='panel'><h2>릴리즈별 패키지·ISO</h2><p>릴리즈 안에서 CPU별 패키지 구성과 ISO를 함께 관리합니다. 고정한 입력은 유지하고 변경한 패키지는 새 릴리즈로 등록합니다.</p><p><a href='/releases/new'>새 릴리즈 등록</a> · <a href='/iso-build'>전체 ISO 이력</a></p><form method='get' action='/releases'><label for='release-search'>릴리즈 검색</label><input id='release-search' name='q' value='{esc(search)}'><label for='release-state'>상태</label><select id='release-state' name='state'>{states}</select><button>조회</button></form><table><tr><th>릴리즈·OS 버전</th><th>관리 상태</th><th>CPU 구성</th><th>ISO</th><th>등록 시각</th></tr>{table_rows}</table><p class='notice'>구성 잠금은 입력 관리 상태입니다. 실제 설치·GDM 로그인·Secure Boot 검증 여부는 각 ISO에서 따로 확인하세요.</p></section>"
    body+="<section class='panel'><h2>기존 보관 자료</h2><p>기존 OS 버전은 자동으로 이 목록에 표시됩니다. 릴리즈 이름이 없던 과거 ISO와 원본 패키지도 그대로 보존합니다.</p><a href='/versions'>전체 소스·바이너리 보관소</a> · <a href='/iso-build'>과거 ISO 포함 전체 이력</a></section>"
    return render('릴리즈 관리',body)


def new(manager,render,q):
    lib=manager.lib;snaps=sorted(lib.snapshots(),key=lambda s:s.get('created_at',''),reverse=True)
    base=q.get('base',[''])[0];origin=q.get('from',[''])[0]
    if origin:
        previous=manager.get(origin);cpu=q.get('cpu',[next(iter(previous['targets']))])[0]
        if cpu not in previous['targets']:raise ValueError('기준 릴리즈의 CPU 구성을 확인하세요.')
        if not base:base=previous['targets'][cpu]['snapshot']
    selected=next((s for s in snaps if s['id']==base),None) if base else next(iter(snaps),None)
    if base and not selected:raise ValueError('기준 스냅샷을 확인하세요.')
    base=selected['id'] if selected else ''
    choices=''.join(option(s['id'],s['id'],s['id']==base) for s in snaps)
    body=f"<section class='panel'><h2>새 릴리즈 구성</h2><p>기준 패키지 구성에서 버전을 교체하거나 패키지를 추가·제외할 수 있습니다. 등록 작업이 SHA·의존성·CPU 대상·후보 서명을 확인한 뒤 별도 구성으로 고정합니다.</p><form method='get' action='/releases/new'><label for='release-base'>기준 스냅샷</label><select id='release-base' name='base'>{choices}</select><button>구성 불러오기</button></form></section>"
    if not selected:return render('새 릴리즈 등록',body)
    available=[p['id'] for p in lib.cpu_targets(base) if p['available']]
    cpu=available[0] if available else 'x86_64'
    targets=''.join(f"<option value='{esc(k)}'{'' if k in available else ' disabled'}{' selected' if k==cpu else ''}>{esc(v['label'])}</option>" for k,v in PROFILES.items())
    suggested=q.get('version',[''])[0]
    body+=f"<section class='panel'><form method='post' action='/releases/register' data-release-packages data-ready='{int(bool(available))}'>{hidden('base',base)}{hidden('changes','{}')}<div class='fields wide'><label>릴리즈·OS 버전<input name='release_version' required maxlength='64' pattern='[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}' placeholder='2026.10.26-r1' value='{esc(suggested)}'></label><label>표시 제목<input name='title' maxlength='120' placeholder='운영 데스크톱 후보'></label><label>CPU 대상<select name='cpu_profile'>{targets}</select></label><label>기본 운영 구성<select name='profile'><option value='gnome50'>GNOME 50 운영 데스크톱</option><option value='minimal-systemd'>최소 systemd 서버</option></select></label><label class='wide'>릴리즈 메모<textarea name='notes' maxlength='8000' rows='3'></textarea></label></div><p class='notice wide'>동일 릴리즈·CPU의 기존 패키지 구성은 덮어쓸 수 없습니다. 새 CPU 대상은 해당 대상으로 검증된 스냅샷을 기준으로 등록하세요. 원본 설치기와 기존 패키지 파일은 수정하지 않습니다.</p><h2 class='wide'>패키지 버전 선택</h2><label class='wide'>패키지 이름 찾기<input type='search' data-release-package-search></label><p class='wide' data-release-change-count>선택 도구를 준비하는 중…</p><button disabled data-release-register>SHA 검사 후 릴리즈 등록</button><div class='wide' style='max-height:540px;overflow:auto'><table><tr><th>패키지</th><th>선택할 버전</th><th>기준 SHA</th></tr>"
    grouped={}
    for record in lib.catalog['binaries'].values():grouped.setdefault(record['name'],[]).append(record)
    for name,records in sorted(grouped.items()):
        original=selected['packages'].get(name,'');variants=[]
        for r in sorted(records,key=lambda r:(r['version'],r['release'],r['sha256']),reverse=True):
            if r['arch']=='noarch' or r.get('cpu_profile','x86_64')==cpu or r['sha256']==original:
                suffix=' · 기준' if r['sha256']==original else ''
                if r['arch']!='noarch' and r.get('cpu_profile','x86_64')!=cpu:suffix+=' · CPU 불일치'
                variants.append(option(r['sha256'],package_version(r)+' · '+r['sha256'][:12]+suffix,r['sha256']==original))
        if not original and not variants:continue
        options=option('','구성에서 제외' if original else '구성에 포함하지 않음',not original)+''.join(variants)
        body+=f"<tr data-release-package-row><td><label for='pkg-{esc(name)}'>{esc(name)}</label></td><td><select id='pkg-{esc(name)}' data-package-name='{esc(name)}' data-original='{esc(original)}' disabled>{options}</select></td><td><code>{esc(original[:12] or '미포함')}</code></td></tr>"
    body+="</table></div><noscript><p>패키지 선택을 전송하려면 브라우저 JavaScript를 활성화하세요.</p></noscript></form></section>"
    return render('새 릴리즈 등록',body)


def detail(manager,render,name,q):
    release=manager.get(name);lib=manager.lib
    cpu=q.get('cpu',[next(iter(release['targets']))])[0]
    snapshot,packages=manager.packages(name,cpu);tab=q.get('tab',['summary'])[0]
    if tab not in {'summary','packages','isos','compare','settings'}:raise ValueError('릴리즈 화면을 확인하세요.')
    url='/releases/'+name;iso_jobs=manager.isos(name,cpu);done=sum(j['status']=='succeeded' for j in iso_jobs)
    body=f"<section class='panel'><h2>{esc(release['title'])}</h2><p><b>{esc(name)}</b> · <span class='tag'>{STATES[release['state']]}</span> · 패키지 {len(packages)}개 · 완료 ISO {done}개</p><p style='white-space:pre-wrap'>{esc(release['notes'] or '릴리즈 메모가 없습니다.')}</p><p>CPU 구성: "+' · '.join(f"<a href='{url}?cpu={esc(k)}&tab={esc(tab)}'>{esc(cpu_label(k))}</a>" for k in release['targets'])+f"</p><p>고정 스냅샷: <code>{esc(snapshot['id'])}</code></p><p><a href='{url}/manifest'>릴리즈 패키지·ISO 명세 다운로드</a> · <a href='/releases/new?from={esc(name)}&cpu={esc(cpu)}'>이 구성을 기준으로 다음 릴리즈 등록</a> · <a href='/releases'>릴리즈 목록</a></p><div class='tabs'>"+''.join(f"<a{' aria-current=page' if k==tab else ''} href='{url}?cpu={esc(cpu)}&tab={k}'>{label}</a>" for k,label in [('summary','요약'),('packages','패키지'),('isos','ISO'),('compare','변경 비교'),('settings','설정')])+"</div></section>"
    if tab=='summary':
        sources=sum(r.get('source',{}).get('sha256') in lib.catalog['sources'] for r in packages.values())
        body+=f"<section class='panel'><h2>릴리즈 구성과 검증 범위</h2><table><tr><th>CPU 대상</th><td>{esc(cpu_label(cpu))}</td></tr><tr><th>패키지</th><td>{len(packages)}개 · 소스 확보 {sources}개 / 미확보 {len(packages)-sources}개</td></tr><tr><th>스냅샷 SHA-256</th><td><code>{esc(release['targets'][cpu]['snapshot_manifest_sha256'])}</code></td></tr><tr><th>패키지 검증 범위</th><td>{esc(snapshot['validation_scope'])}</td></tr><tr><th>ISO</th><td>완료 {done}개 / 전체 {len(iso_jobs)}개</td></tr></table><p class='notice'>릴리즈에 포함된 패키지는 스냅샷에 고정되어 있습니다. 구성 잠금·보관 상태는 실제 설치·로그인 검증이나 공식 배포 승인을 의미하지 않습니다.</p></section>"
    elif tab=='packages':
        search=q.get('q',[''])[0].lower();rows=[]
        for package,r in sorted(packages.items()):
            if search and search not in (package+' '+package_version(r)).lower():continue
            key=r.get('source',{}).get('sha256','')
            source=f"<a href='/library/files/source/{key}'>소스 다운로드</a>" if key in lib.catalog['sources'] else '소스 미확보'
            rows.append(f"<tr><td><b>{esc(package)}</b><br>{esc(package_version(r))}<br>{esc(r['arch'])}</td><td>{esc(r['validation'])}<details><summary>SHA·의존성</summary><code>{esc(r['sha256'])}</code><p>{esc(', '.join(r['dependencies'].get('runtime',[])))}</p><p>소스 SHA: <code>{esc(key or '미등록')}</code></p></details></td><td>{source}</td><td><a href='/library/files/binary/{r['sha256']}'>KI2 다운로드</a> · <a href='/library/files/manifest/{r['sha256']}'>파일 명세</a></td></tr>")
        table_rows=''.join(rows) or '<tr><td colspan="4">검색 결과가 없습니다.</td></tr>'
        body+=f"<section class='panel'><h2>이 릴리즈에 포함된 패키지</h2><form method='get' action='{url}'>{hidden('cpu',cpu)}{hidden('tab','packages')}<label for='package-search'>패키지·버전 검색</label><input id='package-search' name='q' value='{esc(search)}'><button>검색</button></form><table><tr><th>패키지·버전</th><th>검증·의존성</th><th>소스</th><th>바이너리</th></tr>{table_rows}</table></section>"
    elif tab=='isos':
        body+="<section class='panel'><h2>이 릴리즈의 ISO 생성</h2>"
        if release['state']=='archived':body+="<p>보관한 릴리즈입니다. 설정에서 보관 해제하면 새 ISO를 생성할 수 있습니다. 기존 다운로드는 유지합니다.</p>"
        elif release['state']=='legacy':body+=f"<p>기존 보관 릴리즈입니다. <a href='{url}?cpu={esc(cpu)}&tab=settings'>관리 등록</a> 후 이 화면에서 ISO를 생성하세요.</p>"
        else:
            profiles=''.join(option(k,v,release['default_profile']==k) for k,v in [('gnome50','GNOME 50 운영 데스크톱'),('minimal-systemd','최소 systemd 서버')])
            body+=f"<p>아래 작업은 이 릴리즈·CPU의 고정 패키지 구성으로 생성합니다.</p><form method='post' action='/iso-build'>{hidden('release_version',name)}{hidden('cpu_profile',cpu)}{hidden('snapshot',snapshot['id'])}<label for='release-iso-profile'>운영 구성</label><select id='release-iso-profile' name='profile'>{profiles}</select><button>이 릴리즈의 ISO 생성</button></form>"
        rows=[];labels={'pending':'대기','running':'실행 중','succeeded':'완료','failed':'실패','interrupted':'중단됨'}
        for j in iso_jobs:
            result=j.get('result') or {};link='/iso-build/jobs/'+j['id']
            downloads=(f"<a href='{link}/file'>ISO 다운로드</a> · <a href='{link}/sha256'>SHA-256</a> · <a href='{link}/report'>검증 명세</a><br><code>{esc(result['file'])}</code>" if j['status']=='succeeded' else '완료 후 다운로드 가능')
            validation=(f"설치 {'검증 완료' if result.get('fresh_install_tested') else '미검증'} · GDM {'검증 완료' if result.get('gdm_login_tested') else '미검증'} · Secure Boot {'서명됨' if result.get('secure_boot_signed') else '미서명'}" if result else '')
            rows.append(f"<tr><td><a href='{link}'>{esc(j['id'][:12])}</a><br>{'GNOME 50' if j['values']['profile']=='gnome50' else '최소 systemd'}</td><td>{labels.get(j['status'],esc(j['status']))}<br>{esc(j['phase'])}</td><td>{esc(validation)}</td><td>{downloads}</td></tr>")
        body+="</section><section class='panel'><h2>연결된 ISO와 검증 결과</h2><table><tr><th>작업·운영 구성</th><th>상태</th><th>실제 검증 범위</th><th>다운로드</th></tr>"+(''.join(rows) or '<tr><td colspan="4">아직 생성한 ISO가 없습니다.</td></tr>')+"</table></section>"
    elif tab=='compare':
        others=[r for r in manager.list() if r['version']!=name and cpu in r['targets']];other=q.get('compare',[''])[0]
        choices=option('','비교 기준 선택')+''.join(option(r['version'],r['title']+' · '+r['version'],r['version']==other) for r in others)
        body+=f"<section class='panel'><h2>패키지 구성 변경 비교</h2><p>기준 릴리즈에서 현재 릴리즈로 바뀐 패키지를 SHA 기준으로 비교합니다. 버전 표시가 같아도 내용이 다르면 교체로 표시합니다.</p><form method='get' action='{url}'>{hidden('cpu',cpu)}{hidden('tab','compare')}<label for='compare-release'>기준 릴리즈</label><select id='compare-release' name='compare'>{choices}</select><button>비교</button></form>"
        if other:
            rows=[]
            for row in manager.compare(name,other,cpu):
                old=row['before'];new_record=row['after']
                rows.append(f"<tr><td>{esc(row['package'])}</td><td>{row['kind']}</td><td>{esc(package_version(old))}<br><code>{esc(old['sha256'][:12] if old else '')}</code></td><td>{esc(package_version(new_record))}<br><code>{esc(new_record['sha256'][:12] if new_record else '')}</code></td></tr>")
            body+="<table><tr><th>패키지</th><th>변경</th><th>기준 릴리즈</th><th>현재 릴리즈</th></tr>"+(''.join(rows) or '<tr><td colspan="4">패키지 SHA가 모두 같습니다.</td></tr>')+"</table>"
        body+='</section>'
    else:
        if release['state']=='legacy':
            body+=f"<section class='panel'><h2>기존 릴리즈 관리 등록</h2><p>현재 패키지 구성을 다시 검증해 관리 등록합니다. 기존 ISO와 패키지 파일은 그대로 유지합니다.</p><form method='post' action='/releases/register'>{hidden('release_version',name)}{hidden('base',snapshot['id'])}{hidden('cpu_profile',cpu)}{hidden('profile',release['default_profile'])}{hidden('changes','{}')}{hidden('title',name)}<button>이 릴리즈 관리 등록</button></form></section>"
            return render('릴리즈 '+name,body)
        fields=hidden('revision',release['revision'])
        body+=f"<section class='panel'><h2>제목·릴리즈 메모</h2><form class='fields' method='post' action='{url}/manage'>{fields}{hidden('action','edit')}<label>표시 제목<input name='title' maxlength='120' value='{esc(release['title'])}'></label><label class='wide'>릴리즈 메모<textarea name='notes' maxlength='8000' rows='4'>{esc(release['notes'])}</textarea></label><button>메모 저장</button></form></section><section class='panel'><h2>구성 잠금과 보관</h2><p>구성을 잠그면 새 CPU 구성을 추가할 수 없습니다. 잠금을 해제해도 이미 고정한 패키지는 바뀌지 않습니다. 보관은 새 작업만 중지하며 기존 패키지·ISO·다운로드를 유지합니다.</p>"
        actions=([('restore','보관 해제')] if release['state']=='archived' else [('unlock','구성 잠금 해제'),('archive','릴리즈 보관')] if release['state']=='locked' else [('lock','구성 잠금'),('archive','릴리즈 보관')])
        for action,label in actions:body+=f"<form method='post' action='{url}/manage'>{fields}{hidden('action',action)}<button>{label}</button></form>"
        body+='</section><section class="panel"><h2>관리 이력</h2><table><tr><th>시각</th><th>변경</th><th>상태</th></tr>'
        labels={'edit':'제목·메모 수정','lock':'구성 잠금','unlock':'구성 잠금 해제','archive':'릴리즈 보관','restore':'보관 해제'}
        for event in reversed(release['history']):body+=f"<tr><td>{esc(event['at'])}</td><td>{esc(labels.get(event['action'],event['action']))}</td><td>{esc(STATES.get(event.get('to',''),event.get('snapshot','')))}</td></tr>"
        body+='</table></section>'
    return render('릴리즈 '+name,body)
