"""Korean Git source controls; the existing authentication layer protects forms."""
from html import escape


def source_summary(source):
    if source and source.get('kind') == 'git-latest':
        return '<p>빌드 소스: Git 최신 · HTTPS 확인 후 커밋 고정 대기</p>'
    if not source or source.get('kind') != 'git':
        return '<p>빌드 소스: 기존 후보 작업본 · Git 커밋 미지정</p>'
    return ('<p>빌드 소스: Git · <code>' + escape(source['branch']) + '</code></p>'
            '<p>커밋: <code>' + escape(source['commit']) + '</code></p>'
            '<p>소스 아카이브 SHA-256: <code>' + escape(source['archive_sha256']) + '</code></p>')


def git_page(state):
    if not state.get('enabled'):
        return ('<div class="panel"><h2>Git 연동 설정 필요</h2>'
                '<p>서버 실행 설정에 KIKI_GIT_URL·KIKI_GIT_BRANCH를 지정하세요. '
                '원격 주소와 인증 정보는 서버 관리자가 설정합니다.</p></div>')
    labels = {'running': '동기화 중', 'ready': '동기화 완료', 'failed': '동기화 실패', 'not_synced': '첫 동기화 대기'}
    current = state.get('current')
    content = ('<div class="panel"><h2>Git 저장소</h2><table>'
               '<tr><th>원격 주소</th><td>' + escape(state['remote']) + '</td></tr>'
               '<tr><th>브랜치</th><td><code>' + escape(state['branch']) + '</code></td></tr>'
               '<tr><th>상태</th><td role="status">' + labels[state['status']] + '</td></tr>'
               '<tr><th>마지막 확인</th><td>' + escape(state.get('checked_at', '확인 전')) + '</td></tr></table>'
               '<p>저장소에서 읽기 전용으로 가져옵니다. 커밋·푸시는 수행하지 않습니다. '
               '동기화 후 빌드할 커밋을 확인하세요.</p>')
    if state.get('error'):
        content += '<p role="alert" class="bad">' + escape(state['error']) + '</p>'
    content += ('<form method="post" action="/git/sync"><input type="hidden" name="action" value="sync">'
                '<button' + (' disabled' if state.get('busy') else '') + '>최신 소스 가져오기</button></form>')
    if state.get('busy'):
        content += '<p><a href="/git">진행 상태 새로고침</a></p>'
    content += '</div>'
    if current:
        content += ('<div class="panel"><h2>마지막으로 가져온 커밋</h2>' + source_summary(dict(current, kind='git', branch=state['branch']))
                    + '<p>' + escape(current['subject']) + '</p>'
                    '<p>각 빌드는 이 커밋을 작업별 경로에 복원합니다. 이후 동기화는 실행 중인 빌드에 영향을 주지 않습니다.</p>')
        for pipeline, label in [('smoke', '이 커밋 기본 검사'), ('security', '이 커밋 보안 검사')]:
            content += ('<form method="post" action="/jobs" class="bar">'
                        '<input type="hidden" name="pipeline" value="' + pipeline + '">'
                        '<input type="hidden" name="source" value="git">'
                        '<input type="hidden" name="commit" value="' + current['commit'] + '">'
                        '<button>' + label + '</button></form>')
        content += '<p><a class="button" href="/package-build?source=git&amp;commit=' + current['commit'] + '">이 커밋의 패키지 빌드</a></p>'
        content += '<p><a class="button" href="/kernel-build?source=git&amp;commit=' + current['commit'] + '">이 커밋의 커널 빌드</a></p></div>'
    rows = ''.join('<tr><td><code>' + escape(r['commit']) + '</code></td><td>' + escape(r['subject'])
                   + '</td><td>' + escape(r['synced_at']) + '</td></tr>' for r in state.get('history', [])[:30])
    content += ('<div class="panel"><h2>동기화 이력</h2><table><tr><th>커밋</th><th>변경 내용</th><th>가져온 시각</th></tr>'
                + (rows or '<tr><td colspan="3">아직 가져온 소스가 없습니다.</td></tr>') + '</table></div>'
                '<div class="panel"><h2>패키지·ISO 반영</h2><p>소스 가져오기 → 검사·패키지 빌드 → '
                'SHA·의존성·런타임 검증 → 새 릴리즈 등록 → 버전별 ISO 생성 순서로 진행합니다. '
                '기존 후보 패키지·ISO와 고정된 LLVM·Mesa 빌드는 기존 입력을 유지합니다.</p></div>')
    return content
