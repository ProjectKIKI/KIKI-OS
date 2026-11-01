"""카탈로그 근거를 고정한 AI 제안과 실행하지 않는 라이브 패치 시험 계획."""
import json
import hashlib
from html import escape as esc
from pathlib import Path
from urllib.parse import quote


def context(store, name, target=''):
    recipes = store.recipes()
    if name not in recipes:
        raise ValueError('카탈로그 패키지를 선택하세요.')
    if len(target) > 100 or any(ord(c) < 32 for c in target):
        raise ValueError('대상 버전을 확인하세요.')
    recipe = recipes[name]
    affected = {name}
    while True:
        added = {n for n, r in recipes.items()
                 if any(d in affected for deps in r.dependencies.values() for d in deps)}
        if added <= affected:
            break
        affected |= added
    state = store.current()
    return dict(package=name, current_version=recipe.version, target_version=target or '미확인',
                revision=state['revision'], summary=recipe.summary, license=recipe.license,
                tier=recipe.tier, source=recipe.source, dependencies=recipe.dependencies,
                build_system=recipe.build.get('system'),
                affected=sorted(affected - {name}),
                metadata=state.get('metadata', {}).get(name, {}),
                required_checks=['소스 해시·서명 확인', '의존 패키지 빌드', 'VM 적용·재부팅',
                                 '서비스·GUI 검사', 'CVE·OpenSCAP 검사'],
                compatibility='미확인: 버전 문자열만으로 ABI 호환성을 판단하지 않음')


def suggestions(answer):
    value = json.loads(answer)
    if not isinstance(value, dict) or set(value) != {'summary', 'license', 'tier', 'evidence'}:
        raise ValueError('AI 메타정보 응답 형식이 올바르지 않습니다. 저장하지 않았습니다.')
    for key, limit in [('summary', 1000), ('license', 200), ('tier', 64), ('evidence', 3000)]:
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > limit or any(ord(c) < 32 for c in value[key]):
            raise ValueError('AI 필드 길이·형식 오류: ' + key)
    return value


def result_html(report):
    data = report.get('planning')
    if not data:
        return ''
    body = '<div class="panel planning-review"><style>.planning-review input{width:100%;box-sizing:border-box}.planning-review table{table-layout:fixed;width:100%}.planning-review td{overflow-wrap:anywhere}</style><details><summary>고정한 입력과 영향 범위</summary><pre>' + esc(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></details>'
    if report['task'] == 'metadata':
        try:
            values = suggestions(report['answer'])
        except (ValueError, TypeError) as exc:
            return body + '<p role="alert">' + esc(str(exc)) + '</p></div>'
        body += '<p>제안의 근거를 검토하고 필드를 수정한 뒤 저장하세요. 라이선스는 원문 확인이 필요합니다.</p><form method="post" action="/packages/metadata" class="catalog-form">'
        for key, value in [('name', data['package']), ('revision', data['revision']), ('action', 'save')]:
            body += f'<input type="hidden" name="{key}" value="{esc(str(value), quote=True)}">'
        body += '<table><tr><th>항목</th><th>현재 값</th><th>제안·수정 값</th></tr>'
        for key, label in [('summary', '설명'), ('license', '라이선스'), ('tier', '분류')]:
            old = data['metadata'].get(key, data[key])
            body += f'<tr><td>{label}</td><td>{esc(str(old))}</td><td><input name="{key}" value="{esc(values[key], quote=True)}" required></td></tr>'
        body += '</table><p>근거: ' + esc(values['evidence']) + '</p><label>변경 사유<input name="reason" required></label><button>검토한 메타정보 저장</button></form>'
    else:
        body += f'<p><a href="/updates/new?package={quote(data["package"])}">업데이트 후보 화면에서 검토</a></p><p>AI 계획은 빌드 승인이나 호환성 검증 결과가 아닙니다.</p>'
    return body + '</div>'


def forms(package=''):
    package = esc(package, quote=True)
    return ('<div class="panel"><h2>AI 메타정보 · 업데이트 계획</h2><p>카탈로그와 현재 편집본을 고정하여 제안합니다. 자동 저장·배포하지 않습니다.</p>'
            + ''.join(f'<form class="catalog-form" method="post" action="/assistant/{task}"><h3>{label}</h3><label>패키지 이름<input name="package" value="{package}" required maxlength="100"></label>'
                       + ('<label>검토할 대상 버전<input name="target" maxlength="100"></label>' if task == 'plan' else '')
                       + '<button>AI 제안 요청</button></form>' for task, label in [('metadata', '메타정보 입력 제안'), ('plan', '업데이트 계획')])
            + '<p><a href="/kernel-livepatch">커널 라이브 패치 지원 검사·시험 계획</a></p></div>')


def kernel_probe(config):
    raw = Path(config).read_bytes()
    settings = dict(line.split('=', 1) for line in raw.decode().splitlines() if line.startswith('CONFIG_') and '=' in line)
    required = ['CONFIG_MODULES', 'CONFIG_LIVEPATCH', 'CONFIG_FUNCTION_TRACER',
                'CONFIG_DYNAMIC_FTRACE_WITH_REGS', 'CONFIG_HAVE_RELIABLE_STACKTRACE']
    missing = [key for key in required if settings.get(key) != 'y']
    return dict(scope='저장된 설정의 정적 검사',
                config_sha256=hashlib.sha256(raw).hexdigest(), required=required, missing=missing,
                configuration_ready=not missing, runtime_verified=False, module_loaded=False,
                signing_enabled=settings.get('CONFIG_MODULE_SIG') == 'y',
                debug_info_available=settings.get('CONFIG_DEBUG_INFO_NONE') != 'y',
                test_plan=['실행 커널과 소스·설정·컴파일러·심볼 일치 확인',
                           '별도 시험 VM에서 샘플 패치 모듈 빌드', '서명·대상 커널 불일치 거부 검사',
                           '패치 전환 완료·기능·부하 검사', '제거 가능 여부·재부팅 복구 검사'],
                status='시험 준비 가능 · 실행 커널 확인 필요' if not missing else '기반 커널 재빌드 필요')


def kernel_page(config):
    data = kernel_probe(config)
    return '<div class="panel"><h2>커널 라이브 패치 시험 준비</h2><p>저장된 설정만 검사합니다. 실행 커널의 지원을 인증하거나 모듈을 로드하지 않습니다.</p><pre>' + esc(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre><p>운영 적용 전 전용 VM 검증이 필요합니다.</p></div>'
