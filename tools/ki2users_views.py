"""Korean account pages, served only by the authenticated gateway."""
from datetime import datetime, timezone
from html import escape

from ki2users import ROLES


def esc(value):
    return escape(str(value), quote=True)


def csrf(session):
    return "<input type='hidden' name='_csrf' value='"+esc(session['csrf'])+"'>"


CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#202b3c;font:14px system-ui,sans-serif}
a{color:#225bb5;text-decoration:none}a:hover{text-decoration:underline}header{background:#192434;color:#fff;padding:18px 28px;display:flex;gap:22px;align-items:center;flex-wrap:wrap}header strong{font-size:18px}header a{color:#dce6f7}header .identity{margin-left:auto}
nav{background:#fff;padding:14px 28px;border-bottom:1px solid #dce1e8;display:flex;gap:22px;flex-wrap:wrap}main{max-width:1250px;margin:32px auto;padding:0 28px}h1{font-size:28px;margin:10px 0}h2{font-size:18px;margin:0 0 18px}.muted,small{color:#637187;line-height:1.6}.lead{margin-bottom:26px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:22px}.card{background:white;border:1px solid #dce1e8;border-radius:10px;padding:24px;margin-bottom:22px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.button,button{display:inline-block;border:1px solid #bac6d6;background:#fff;color:#253c5a;padding:10px 16px;border-radius:6px;font:inherit;font-weight:650;cursor:pointer}.primary{background:#245fc0;color:white;border-color:#245fc0}.danger{color:#a02b35;border-color:#e1b7bc}button:disabled{cursor:not-allowed;opacity:.5}form{margin:0}label{display:block;font-weight:650;margin:16px 0 8px}input:not([type=hidden]):not([type=checkbox]),select{border:1px solid #b7c3d3;border-radius:5px;padding:11px;font:inherit;color:inherit;background:white;width:100%;max-width:520px}input:focus,select:focus,a:focus,button:focus{outline:3px solid #b8d3ff;outline-offset:2px}input[type=checkbox]{margin-right:8px}.check{font-weight:400;line-height:1.6}.actions{display:flex;gap:12px;margin-top:22px;flex-wrap:wrap}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{text-align:left;padding:16px 12px;border-bottom:1px solid #e7ebf0}th{color:#64718a;font-size:12px;background:#f8fafc}td small{display:block}.badge{display:inline-block;background:#e9f1ff;color:#214c91;border-radius:20px;padding:4px 10px;font-size:12px}.off{background:#f1f2f4;color:#6d7380}.warn{background:#fff7e5;color:#865e16;border:1px solid #eeddb6;padding:14px;border-radius:6px;line-height:1.7}.error{background:#fff0f1;color:#a32732;padding:14px;border:1px solid #ecc4c8;border-radius:6px;margin-bottom:20px}.secret{font:20px ui-monospace,monospace;background:#edf2f9;padding:18px;border:1px solid #cbd7e8;border-radius:6px;overflow-wrap:anywhere;user-select:all}dl{display:grid;grid-template-columns:100px 1fr;gap:14px}dt{color:#66748a}dd{margin:0}ul{padding-left:20px;line-height:1.9}.search{display:flex;gap:8px;align-items:end}.search label{margin-top:0;font-size:12px}.search input{max-width:260px!important}
@media(max-width:780px){header,nav{padding:16px 18px}main{padding:0 18px;margin-top:22px}.grid{grid-template-columns:1fr}.card{padding:18px}h1{font-size:24px}header .identity{margin-left:0}.search{width:100%}}
'''


def shell(session, title, content, error=''):
    from ki2ci_theme import document
    alert = "<div role='alert' class='error'>"+esc(error)+"</div>" if error else ''
    return document(session, '/account' if title == '내 계정' else '/users', title,
                    alert+content, head='<style>'+CSS+'</style>', heading=False).encode()


def options(role):
    return ''.join("<option value='"+key+"'"+(" selected" if key == role else '')+">"+label+"</option>" for key, label in ROLES.items())


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value else '기존 계정'


def users_page(session, users, events, query=''):
    active = sum(bool(u['enabled']) for u in users)
    rows = []
    for user in users:
        if query.casefold() not in user['name'].casefold():
            continue
        name = esc(user['name'])
        self_mark = ' · 내 계정' if user['name'] == session['name'] else ''
        status = "<span class='badge'>활성</span>" if user['enabled'] else "<span class='badge off'>비활성</span>"
        pw = '첫 로그인 변경 필요' if user['must_change'] else '설정 완료'
        rows.append("<tr><td><a href='/users/"+name+"'><strong>"+name+"</strong></a><small>"+self_mark+"</small></td><td>"+ROLES[user['role']]+"</td><td>"+status+"</td><td>"+pw+"</td><td>"+timestamp(user['created_at'])+"</td><td><a href='/users/"+name+"'>관리</a></td></tr>")
    events_labels = {'created': '사용자 추가', 'updated': '권한·상태 변경', 'password_reset': '임시 비밀번호 발급', 'sessions_revoked': '세션 종료', 'password_changed': '본인 비밀번호 변경'}
    history = ''.join('<tr><td>'+timestamp(at)+'</td><td>'+esc(actor)+'</td><td>'+esc(target)+'</td><td>'+events_labels.get(event, esc(event))+'</td></tr>' for at, actor, target, event in events)
    content = "<div class='lead'><small>설정 / 접근 관리</small><h1>사용자 관리</h1><p class='muted'>계정과 운영 권한을 관리합니다. 계정 변경 이력과 기존 빌드 자료는 유지됩니다.</p></div>"
    content += "<section class='card'><div class='toolbar'><div><h2>전체 사용자 "+str(len(users))+"명</h2><p class='muted'>활성 "+str(active)+"명 · 비활성 "+str(len(users)-active)+"명</p></div><a class='button primary' href='/users/new'>사용자 추가</a></div>"
    content += "<form method='get' action='/users' class='search'><div><label for='q'>아이디 검색</label><input id='q' name='q' value='"+esc(query)+"' maxlength='64' placeholder='아이디 입력'></div><button>검색</button><a href='/users'>초기화</a></form>"
    content += "<div class='table-wrap'><table><thead><tr><th>아이디</th><th>권한</th><th>계정 상태</th><th>비밀번호</th><th>등록 시각</th><th>작업</th></tr></thead><tbody>"+(''.join(rows) or "<tr><td colspan='6'>검색 결과가 없습니다.</td></tr>")+"</tbody></table></div></section>"
    content += "<div class='grid'><section class='card'><h2>최근 계정 변경 이력</h2><p class='muted'>최근 30건 · 비밀번호와 세션 토큰은 기록하지 않습니다.</p><div class='table-wrap'><table><thead><tr><th>시각</th><th>작업자</th><th>대상</th><th>작업</th></tr></thead><tbody>"+(history or "<tr><td colspan='4'>아직 변경 이력이 없습니다.</td></tr>")+"</tbody></table></div></section><aside class='card'><h2>권한 안내</h2><ul><li><strong>관리자</strong>: 사용자·권한 관리와 전체 운영</li><li><strong>운영자</strong>: 패키지·릴리즈·ISO 작업</li><li><strong>조회자</strong>: 상태·로그 조회와 산출물 다운로드</li></ul><p class='muted'>비활성화·권한 변경·비밀번호 초기화 시 해당 계정의 세션이 종료됩니다. 본인 권한 변경과 마지막 관리자 잠금은 차단됩니다.</p></aside></div>"
    return shell(session, '사용자 관리', content)


def user_page(session, user, error=''):
    if user is None:
        content = "<a href='/users'>← 사용자 목록</a><h1>사용자 추가</h1><p class='muted'>임시 비밀번호를 자동 발급합니다. 사용자는 첫 로그인 때 비밀번호를 변경해야 합니다.</p><div class='grid'><section class='card'><form method='post' action='/users/create'>"+csrf(session)+"<label for='username'>아이디</label><input id='username' name='username' required maxlength='64' pattern='[A-Za-z0-9_.\\-]{1,64}' autocomplete='off'><small>영문·숫자·점·밑줄·하이픈, 대소문자를 구분합니다.</small><label for='role'>권한</label><select id='role' name='role'>"+options('viewer')+"</select><div class='actions'><button class='primary'>사용자 생성 및 임시 비밀번호 발급</button><a class='button' href='/users'>취소</a></div></form></section><aside class='card'><h2>등록 안내</h2><p class='muted'>기본 권한은 조회자입니다. 임시 비밀번호는 생성 직후 한 번만 표시되며, 분실 시 관리자가 다시 발급할 수 있습니다.</p></aside></div>"
        return shell(session, '사용자 추가', content, error)
    name = esc(user['name'])
    own = user['name'] == session['name']
    base = "<form method='post' action='/users/"+name+"/manage'>"+csrf(session)+"<input type='hidden' name='revision' value='"+str(user['revision'])+"'>"
    content = "<a href='/users'>← 사용자 목록</a><h1>"+name+" 계정 관리</h1><p class='muted'>권한·활성 상태를 변경하고 접근을 회수합니다.</p><div class='grid'><section class='card'><h2>권한과 계정 상태</h2>"+base+"<input type='hidden' name='action' value='update'>"
    if own:
        content += "<p class='warn'>현재 로그인한 관리자입니다. 본인 권한·활성 상태는 변경할 수 없습니다.</p><input type='hidden' name='role' value='admin'><input type='hidden' name='enabled' value='1'><p>권한: 관리자 · 계정 상태: 활성</p></form>"
    else:
        content += "<label for='role'>권한</label><select id='role' name='role'>"+options(user['role'])+"</select><label class='check'><input type='checkbox' name='enabled' value='1'"+(' checked' if user['enabled'] else '')+">계정 활성화</label><p class='muted'>비활성 계정은 로그인할 수 없습니다. 기존 산출물과 작업 이력은 유지됩니다.</p><div class='actions'><button class='primary'>권한·상태 저장</button></div></form>"
    content += "</section><aside class='card'><h2>계정 정보</h2><dl><dt>아이디</dt><dd>"+name+"</dd><dt>등록</dt><dd>"+timestamp(user['created_at'])+"</dd><dt>비밀번호</dt><dd>"+('첫 로그인 변경 필요' if user['must_change'] else '설정 완료')+"</dd><dt>변경 번호</dt><dd>"+str(user['revision'])+"</dd></dl></aside></div><div class='grid'><section class='card'><h2>비밀번호 초기화</h2>"
    if own:
        content += "<p class='muted'>본인의 비밀번호는 현재 비밀번호를 확인한 뒤 변경합니다.</p><a class='button' href='/account'>내 계정으로 이동</a>"
    else:
        content += "<p class='muted'>임시 비밀번호를 발급하고 이 계정의 모든 세션을 종료합니다. 다음 로그인 시 새 비밀번호 설정이 필요합니다.</p>"+base+"<input type='hidden' name='action' value='reset'><label class='check'><input type='checkbox' name='confirm_action' value='yes' required>비밀번호 초기화와 세션 종료를 확인했습니다.</label><div class='actions'><button class='danger'>임시 비밀번호 재발급</button></div></form>"
    content += "</section><section class='card'><h2>접속 중인 세션 종료</h2><p class='muted'>이 계정의 모든 브라우저 세션을 종료합니다. 비밀번호는 유지됩니다.</p>"+base+"<input type='hidden' name='action' value='revoke'><label class='check'><input type='checkbox' name='confirm_action' value='yes' required>대상 계정의 모든 세션 종료를 확인했습니다.</label><div class='actions'><button class='danger'>모든 세션 종료</button></div></form></section></div>"
    return shell(session, name+' 계정 관리', content, error)


def temporary_page(session, name, password):
    content = "<h1>임시 비밀번호 발급 완료</h1><section class='card'><h2>"+esc(name)+"</h2><p class='warn'>이 화면에서 한 번만 표시됩니다. 사용자에게 안전하게 전달하세요. 첫 로그인 후 비밀번호 변경이 필요합니다.</p><p class='secret' aria-label='발급한 임시 비밀번호'>"+esc(password)+"</p><p class='muted'>비밀번호 원문은 저장하지 않습니다. 분실하면 계정 관리에서 새 임시 비밀번호를 발급하세요. 이 화면을 새로고침하지 마세요.</p><div class='actions'><a class='button primary' href='/users/"+esc(name)+"'>계정 관리로 이동</a><a class='button' href='/users'>사용자 목록</a></div></section>"
    return shell(session, '임시 비밀번호 발급 완료', content)


def account_page(session, error=''):
    required = "<p class='warn'>임시 비밀번호로 로그인했습니다. 운영 콘솔을 사용하려면 본인 비밀번호로 변경하세요.</p>" if session['must_change'] else ''
    content = "<h1>내 계정</h1><p class='muted'>"+esc(session['name'])+" · "+ROLES[session['role']]+"</p>"+required+"<div class='grid'><section class='card'><h2>비밀번호 변경</h2><form method='post' action='/account/password'>"+csrf(session)+"<label for='current'>현재 비밀번호</label><input id='current' name='current' type='password' autocomplete='current-password' required maxlength='1024'><label for='password'>새 비밀번호</label><input id='password' name='password' type='password' autocomplete='new-password' required minlength='15' maxlength='1024'><small>현재 비밀번호와 다른 15~1024자의 비밀번호를 사용하세요.</small><label for='confirm'>새 비밀번호 확인</label><input id='confirm' name='confirm' type='password' autocomplete='new-password' required minlength='15' maxlength='1024'><div class='actions'><button class='primary'>비밀번호 변경 후 다시 로그인</button></div></form></section><aside class='card'><h2>계정 보호</h2><p class='muted'>변경하면 본인의 모든 브라우저 세션이 종료됩니다. 다른 사용자의 접속과 실행 중인 빌드 작업은 유지됩니다.</p></aside></div>"
    return shell(session, '내 계정', content, error)
