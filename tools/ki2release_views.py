"""Korean release and CPU management pages; no build side effects."""
import html
import json
from ki2cpu import PROFILES


def esc(value):return html.escape(str(value),quote=True)


def os_version(job):
    return (job.get('result') or {}).get('release_version') or job['values'].get('release_version',job['values'].get('snapshot',''))


def version_targets(version):
    return version.get('targets') or {'x86_64':{'snapshot':version['snapshot'],'snapshot_manifest_sha256':version['snapshot_manifest_sha256']}}


def version_panel(lib):
    rows=[]
    for version in reversed(lib.release_versions()):
        jobs=[j for j in lib.jobs() if j['kind']=='iso' and os_version(j)==version['version']]
        for target,pin in version_targets(version).items():
            selected=[j for j in jobs if j['values'].get('cpu_profile','x86_64')==target]
            done=sum(j['status']=='succeeded' for j in selected)
            rows.append(f"<tr><td><a href='/iso-build?version={esc(version['version'])}'>{esc(version['version'])}</a><br>{esc(PROFILES[target]['label'])}</td><td>{esc(pin['snapshot'])}</td><td>{done}개 / 전체 {len(selected)}개</td></tr>")
    return "<section class='panel'><h2>OS 버전별 ISO</h2><p>OS 버전과 CPU 대상별로 패키지 스냅샷을 고정합니다. 같은 버전의 재생성은 별도 작업으로 보존합니다.</p><table><tr><th>OS 버전·CPU 대상</th><th>고정 패키지 스냅샷</th><th>완료 ISO</th></tr>"+(''.join(rows) or "<tr><td colspan='3'>새 OS 버전은 ISO 생성 화면에서 등록할 수 있습니다.</td></tr>")+"</table><p><a href='/iso-build'>버전별 ISO 생성·다운로드</a> · <a href='/cpu-profiles'>CPU 대상 관리</a></p></section>"


def cpu_page(lib,render):
    snapshots=lib.snapshots();rows=[]
    for target,profile in PROFILES.items():
        ready=[s['id'] for s in snapshots if any(p['id']==target and p['available'] for p in lib.cpu_targets(s['id']))]
        status=f'사용 가능한 스냅샷 {len(ready)}개' if ready else '대상 패키지·CPU 런타임 검증 대기'
        flags=' '.join(profile['cflags']) or '기존 패키지 명세 유지'
        rust=' '.join(profile['rustflags']) or '기존 패키지 명세 유지'
        rows.append(f"<tr><td><b>{esc(profile['label'])}</b><p>{esc(profile['description'])}</p></td><td>{esc(status)}<p>{esc(', '.join(ready))}</p></td><td><p>C/C++: <code>{esc(flags)}</code></p><p>Rust: <code>{esc(rust)}</code></p><p>Go 대상: <code>{esc(profile['goamd64'])}</code></p></td></tr>")
    body="<section class='panel'><h2>CPU별 대상과 준비 상태</h2><p class='notice'>v3·v4는 Intel 세대명이 아닌 x86-64 기능 등급입니다. CPU 대상과 운영 구성(GNOME/최소 서버)은 따로 관리합니다. 현재 기존 패키지는 ISA 등급 미분류이며, 검증된 v3·v4 패키지 구성이 확보되면 해당 대상의 ISO 선택이 활성화됩니다.</p><table><tr><th>CPU 대상</th><th>ISO 준비 상태</th><th>향후 빌드 명세</th></tr>"+''.join(rows)+"</table><p>위 컴파일 옵션은 향후 대상별 빌드 명세입니다. 이번 ISO 조립 과정에서 기존 바이너리를 재컴파일하지 않습니다. 대상별 캐시·패키지·VM CPU 검증이 필요하며, 호스트 CPU를 그대로 따르는 native 옵션은 배포 프로필로 사용하지 않습니다.</p><a href='/iso-build'>ISO 생성으로</a></section>"
    return render('CPU 대상 관리',body)


def iso_page(lib,render,q):
    snapshots=sorted(lib.snapshots(),key=lambda s:s.get('created_at',''),reverse=True)
    options=[]
    for snap in snapshots:
        available=[p['id'] for p in lib.cpu_targets(snap['id']) if p['available']]
        options.append(f"<option value='{esc(snap['id'])}' data-cpu-targets='{esc(json.dumps(available))}'>{esc(snap['id'])} · {esc(snap['validation_scope'])}</option>")
    initial=[p['id'] for p in lib.cpu_targets(snapshots[0]['id']) if p['available']] if snapshots else []
    cpu_options=''.join(f"<option value='{esc(target)}'{'' if target in initial else ' disabled'}>{esc(p['label'])}{'' if target in initial else ' · 준비 중'}</option>" for target,p in PROFILES.items())
    body=f"<section class='panel'><h2>OS 버전별 설치 ISO 생성</h2><p class='notice'>원본 설치기를 그대로 재사용합니다. 입력 패키지 SHA·저장소 서명·의존성·BIOS/UEFI 구조를 검사하고 작업별 ISO를 보존합니다. 실제 설치·로그인 검증은 별도입니다.</p><form method='post' action='/iso-build' data-iso-build><label for='release_version'>OS 버전</label><input id='release_version' name='release_version' required maxlength='64' pattern='[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}' placeholder='2026.10.25-r1'><label for='snapshot'>고정 패키지 스냅샷</label><select id='snapshot' name='snapshot' required>{''.join(options)}</select><label for='profile'>운영 구성</label><select id='profile' name='profile'><option value='gnome50'>GNOME 50 운영 데스크톱</option><option value='minimal-systemd'>최소 systemd 서버</option></select><label for='vm_group'>가상머신 통합</label><select id='vm_group' name='vm_group'><option value=''>선택 안 함 · 일반 하드웨어</option><option value='vm-kvm'>KVM / OpenStack · virtio</option><option value='vm-hyperv'>Hyper-V</option></select><label for='cpu_profile'>CPU 대상</label><select id='cpu_profile' name='cpu_profile'>{cpu_options}</select><button{' disabled' if not snapshots else ''}>이 버전의 설치 ISO 생성</button><p class='muted'>같은 OS 버전·CPU 대상에는 같은 패키지 스냅샷만 사용할 수 있습니다. OS 버전은 커널 버전과 별개입니다. 새 패키지 구성은 새 OS 버전으로 등록하세요. <a href='/cpu-profiles'>CPU별 준비 상태</a></p></form></section>"
    wanted=q.get('version',[''])[0];cpu=q.get('cpu',[''])[0];status=q.get('status',[''])[0]
    jobs=[j for j in lib.jobs() if j['kind']=='iso']
    versions=sorted({os_version(j) for j in jobs})
    version_options="<option value=''>모든 OS 버전</option>"+''.join(f"<option value='{esc(v)}'{' selected' if wanted==v else ''}>{esc(v)}</option>" for v in versions)
    cpu_filter="<option value=''>모든 CPU 대상</option>"+''.join(f"<option value='{esc(k)}'{' selected' if cpu==k else ''}>{esc(p['label'])}</option>" for k,p in PROFILES.items())
    labels={'pending':'대기','running':'실행 중','succeeded':'완료','failed':'실패','interrupted':'중단됨'}
    status_options="<option value=''>모든 상태</option>"+''.join(f"<option value='{k}'{' selected' if status==k else ''}>{v}</option>" for k,v in labels.items())
    body+=f"<section class='panel'><h2>버전별 ISO 이력과 다운로드</h2><form method='get' action='/iso-build'><label for='filter-version'>OS 버전</label><select id='filter-version' name='version'>{version_options}</select><label for='filter-cpu'>CPU 대상</label><select id='filter-cpu' name='cpu'>{cpu_filter}</select><label for='filter-status'>상태</label><select id='filter-status' name='status'>{status_options}</select><button>조회</button><a href='/iso-build'>필터 초기화</a></form><table><tr><th>OS 버전·패키지 구성</th><th>CPU·운영 구성</th><th>상태</th><th>산출물</th></tr>"
    rows=[]
    for job in jobs:
        values=job['values'];target=values.get('cpu_profile','x86_64')
        if wanted and os_version(job)!=wanted or cpu and target!=cpu or status and job['status']!=status:continue
        link='/iso-build/jobs/'+job['id'];result=job.get('result') or {};downloads=f"<a href='{link}'>작업·검증 상세</a>"
        if job['status']=='succeeded':downloads+=f"<br><a href='{link}/file'>ISO 다운로드</a> · <a href='{link}/sha256'>SHA-256</a><br><code>{esc(result.get('file',''))}</code>"
        rows.append(f"<tr><td><b>{esc(os_version(job))}</b><br><small>{esc(values['snapshot'])}</small></td><td>{esc(PROFILES.get(target,{'label':target})['label'])}<br>{'GNOME 50 데스크톱' if values['profile']=='gnome50' else '최소 systemd 서버'}</td><td>{esc(labels.get(job['status'],job['status']))}<br>{esc(job['phase'])}</td><td>{downloads}</td></tr>")
    body+=(''.join(rows) or "<tr><td colspan='4'>조건에 맞는 ISO 작업이 없습니다.</td></tr>")+"</table></section>"
    return render('버전별 ISO 생성·관리',body)
