"""Server rendered catalog forms; the auth gateway supplies CSRF and roles."""
from html import escape
from urllib.parse import quote


def esc(value):
    return escape(str(value), quote=True)


def field(name, label, value='', *, area=False, readonly=False, ident=None):
    ident = ident or name
    attrs = " readonly" if readonly else ''
    if area:
        control = f"<textarea id='{ident}' name='{name}' rows='3' style='width:100%;box-sizing:border-box'{attrs}>{esc(value)}</textarea>"
    else:
        control = f"<input id='{ident}' name='{name}' value='{esc(value)}' style='width:100%;box-sizing:border-box'{attrs}>"
    return f"<div class='catalog-field'><label for='{ident}'>{esc(label)}</label>{control}</div>"


def hidden(name, value):
    return f"<input type='hidden' name='{name}' value='{esc(value)}'>"


def intro(state):
    return ("<link rel='stylesheet' href='/catalog-ui.css'><script src='/catalog-ui.js' defer></script>"+f"<p class='notice'>편집본 r{state['revision']} · 변경은 이후 개별 패키지 빌드의 입력으로 고정됩니다. "
            "기존 서명 패키지와 안정 채널에는 영향을 주지 않습니다. 그룹 변경은 ki2ctl과 설치기를 새로 빌드한 매체에서 적용됩니다.</p>"
            "<p><a href='/source-manifest'>릴리즈 전체 소스 명세</a> · <a href='/package-groups'>그룹 관리</a> · <a href='/package-groups/export'>전체 편집본 JSON</a> · "
            "<a href='/package-groups/export?kind=groups'>설치 그룹 JSON</a> · <a href='/package-groups/history'>변경 이력</a></p>")


def groups_page(store, query):
    state = store.current()
    term = query.get('q', '').strip().lower()
    rows = []
    for g in state['catalog']['groups']:
        if term and term not in (g['id'] + g['name_ko'] + ' '.join(sum(g['packages'].values(), []))).lower():
            continue
        profiles = [p['id'] for p in state['catalog']['profiles'] if g['id'] in p['groups']]
        counts = ' / '.join(str(len(g['packages'].get(k, []))) for k in ['mandatory', 'default', 'optional'])
        rows.append(f"<tr><td><a href='/package-groups/edit?id={quote(g['id'])}'>{esc(g['name_ko'])}</a><br><small>{esc(g['id'])}</small></td>"
                    f"<td>{counts}</td><td>{esc(', '.join(g['requires']) or '없음')}</td><td>{esc(', '.join(profiles) or '선택 그룹')}</td></tr>")
    return intro(state) + ("<div class='panel'><div class='catalog-heading'><div><h2>패키지 그룹</h2><p>설치 구성을 그룹으로 묶고 프로필에 연결합니다.</p></div><a class='button' href='/package-groups/edit'>새 그룹 만들기</a></div>"
            "<p>필수·기본 패키지는 그룹 선택 시 설치하며, 선택 패키지는 별도 선택 대상으로 보관합니다.</p>"
            f"<form class='catalog-search' method='get' action='/package-groups'>{field('q','그룹·패키지 검색',query.get('q',''))}<button>검색</button><a href='/package-groups'>초기화</a></form><p class='catalog-result-count' role='status'>{len(rows)}개 그룹 · 전체 {len(state['catalog']['groups'])}개</p>"
            "<div style='overflow:auto'><table><tr><th>그룹</th><th>필수 / 기본 / 선택</th><th>선행 그룹</th><th>연결 프로필</th></tr>" + (''.join(rows) or "<tr><td colspan='4'>검색 결과가 없습니다. 검색어를 바꾸거나 초기화해 주세요.</td></tr>") + '</table></div></div>')


def picker(name,label,value,options):
    options=sorted(options)
    return (f"<div class='catalog-picker' data-picker='{name}'><label for='{name}'>{esc(label)}</label>"
            f"<div class='catalog-picker-search'><input aria-label='{esc(label)} 검색' list='{name}-options' data-picker-input placeholder='이름 검색 후 추가'><button type='button' data-picker-add>추가</button></div>"
            f"<datalist id='{name}-options'>"+''.join(f"<option value='{esc(x)}'></option>" for x in options)+"</datalist><div data-picker-items class='catalog-chips' aria-live='polite'></div>"
            f"<details><summary>목록 직접 입력</summary><textarea id='{name}' name='{name}' rows='3'>{esc(value)}</textarea></details></div>")


def group_edit(store, name, form=None, error=''):
    state = store.current()
    group = next((g for g in state['catalog']['groups'] if g['id'] == name), None)
    if name and group is None:
        raise ValueError('해당 그룹이 없습니다.')
    g = group or dict(id='', name_ko='', name_en='', description_ko='', requires=[], packages={}, services={}, selectable=True)
    if form:
        from ki2catalog import words
        g={**g,**{k:form.get(k,'') for k in ['id','name_ko','name_en','description_ko']},'requires':words(form.get('requires','')),
           'packages':{k:words(form.get(k,'')) for k in ['mandatory','default','optional']},
           'services':{**{k:words(form.get(k,'')) for k in ['enable','disable']},'default_target':form.get('default_target','')},'selectable':form.get('selectable')=='yes'}
    content = intro(state) + "<div class='panel'><div class='catalog-heading'><h2>" + ('그룹 편집' if group else '새 그룹 만들기') + "</h2><a href='/package-groups'>그룹 목록</a></div>"+(f"<p class='catalog-error' role='alert'>{esc(error)}</p>" if error else '')+"<form class='catalog-form' method='post' action='/package-groups/save'>"
    content += hidden('revision', state['revision']) + hidden('create', 'no' if group else 'yes')
    content += field('id', '그룹 ID', g['id'], readonly=bool(group))
    for name, label in [('name_ko', '그룹 이름'), ('name_en', '영문 이름'), ('description_ko', '그룹 설명')]:
        content += field(name, label, g.get(name, g['id']), area=name == 'description_ko')
    content += '<p>목록은 공백·쉼표·줄바꿈으로 구분합니다.</p>'
    content += picker('requires', '선행 그룹', ' '.join(g['requires']),[x['id'] for x in state['catalog']['groups'] if x['id']!=g['id']])
    for k, label in [('mandatory', '필수 패키지'), ('default', '기본 패키지'), ('optional', '선택 패키지')]:
        content += picker(k,label,'\n'.join(g['packages'].get(k,[])),store.known_packages())
    content += '<details class="catalog-advanced"><summary>서비스·부팅 설정 (고급)</summary><p>VM 도구 그룹은 기본 시작 대상을 상속하면 기존 GUI·콘솔 구성을 유지합니다.</p>'
    for k, label in [('enable', '활성화 서비스'), ('disable', '비활성화 서비스')]:
        content += field(k, label, ' '.join(g['services'].get(k, [])))
    content += "<p><label for='default_target'>기본 시작 대상</label><select id='default_target' name='default_target'>"
    content += ''.join(f"<option value='{v}'{' selected' if g['services'].get('default_target','') == v else ''}>{label}</option>" for v, label in [('', '상속'), ('multi-user.target','콘솔'), ('graphical.target','GUI')]) + '</select></p>'
    content += "<p><label for='selectable'>설치기 선택 목록</label><select id='selectable' name='selectable'>" + ''.join(f"<option value='{v}'{' selected' if g.get('selectable',True) == b else ''}>{label}</option>" for v,b,label in [('yes',True,'표시'),('no',False,'숨김')]) + '</select></p>'
    content += '</details>'
    content += picker('profiles','기본 포함할 프로필',form.get('profiles','') if form else ' '.join(p['id'] for p in state['catalog']['profiles'] if g['id'] in p['groups']),[p['id'] for p in state['catalog']['profiles']])
    content += '<p>프로필: ' + esc(', '.join(p['id'] for p in state['catalog']['profiles'])) + '</p>'
    content += field('reason', '변경 사유',form.get('reason','') if form else '') + "<div class='catalog-actions'><button class='secondary' name='action' value='preview'>저장 전 검토</button><button name='action' value='save'>그룹 저장</button></div></form>"
    if group:
        content += "<details><summary>그룹 삭제</summary><p>다른 그룹이나 프로필에서 참조하는 그룹은 삭제할 수 없습니다.</p><form method='post' action='/package-groups/save'>" + hidden('id',g['id']) + hidden('revision',state['revision']) + hidden('action','delete') + field('reason','삭제 사유',ident='delete_reason') + '<button>그룹 삭제</button></form></details>'
    return content + '</div>'


def metadata_edit(store, name):
    state = store.current()
    recipe = store.recipes().get(name)
    if recipe is None:
        raise ValueError('해당 패키지가 없습니다.')
    patch = state['metadata'].get(name, {})
    content = intro(state) + f"<div class='panel'><h2>{esc(name)} 메타정보 편집</h2><p>보존 레시피 {esc(recipe.version)}-{esc(recipe.release)} · 편집본 release {esc(patch.get('release','미지정'))} · 실제 빌드 release는 선택한 소스와 그룹 리비전에 따라 증가합니다. 버전·소스·의존성 변경은 <a href='/updates/new?package={quote(name)}'>업데이트 후보</a>에서 빌드·검증합니다.</p>"
    content += f"<p><a href='/assistant?package={quote(name)}'>AI 메타정보 제안·업데이트 계획</a></p>"
    if recipe.build.get('system')=='recorded-native':
        content += "<p class='notice'>이 패키지는 별도 native SDK 파이프라인에서 컴파일합니다. 보존된 바이너리를 소스 빌드로 처리하지 않습니다. 전체 소스 명세와 tools/gnome_native/README.ko.md의 빌드 순서를 확인하세요.</p><p><a class='button' href='/source-manifest'>Native 소스·빌드 명세</a> <a href='/packages'>패키지 목록</a></p>"
    else:
        content += f"<p><a class='button' href='/package-build?source=preserved&amp;package={quote(name)}'>이 패키지 빌드</a> <a href='/packages'>패키지 목록</a></p>"
    content += "<form class='catalog-form' method='post' action='/packages/metadata'>" + hidden('name',name) + hidden('revision',state['revision'])
    for k,label in [('summary','패키지 설명'),('license','라이선스 표현식'),('tier','패키지 분류')]:
        content += field(k,label,patch.get(k,getattr(recipe,k)))
    content += field('reason','변경 사유') + "<button name='action' value='save'>메타정보 저장</button></form>"
    if patch:
        content += "<form method='post' action='/packages/metadata'>" + hidden('name',name) + hidden('revision',state['revision']) + hidden('action','reset') + field('reason','원본 복원 사유',ident='reset_reason') + '<button>원본 메타정보로 복원</button></form>'
    return content + '</div>'


def select(name,label,options,value):
    return f"<div class='catalog-field'><label for='{name}'>{esc(label)}</label><select id='{name}' name='{name}'>"+''.join(f"<option value='{esc(k)}'{' selected' if k==value else ''}>{esc(v)}</option>" for k,v in options)+"</select></div>"


def package_new(store, form=None, error=''):
    state=store.current();f=form or {}
    body=intro(state)+"<div class='panel'><div class='catalog-heading'><div><h2>새 패키지 등록</h2></div><a href='/packages'>패키지 목록</a></div>"
    body+="<p>등록한 레시피는 편집본으로 보관됩니다. 시험 빌드·서명·저장소 배포는 별도 단계입니다.</p>"
    if error:body+=f"<p role='alert' class='catalog-error'>{esc(error)}</p>"
    body+="<p><a href='/assistant'>AI로 레시피·메타정보 초안 작성</a></p>"
    body+="<form class='catalog-form' method='post' action='/packages/register'>"+hidden('revision',state['revision'])
    body+=select('kind','등록 방식',[('source','HTTPS 소스 압축파일 빌드'),('documentation','문서 패키지')],f.get('kind','source'))
    body+="<div class='catalog-grid'>"+''.join(field(k,label,f.get(k,default)) for k,label,default in [('name','패키지 이름',''),('version','버전','1.0.0'),('summary','설명',''),('license','라이선스',''),('tier','분류','extra')])+select('arch','아키텍처',[('x86_64','x86_64'),('all','아키텍처 공통')],f.get('arch','x86_64'))+'</div>'
    body+="<fieldset data-registration-kind='source'><legend>소스와 빌드</legend>"+field('url','공식 소스 압축파일 URL',f.get('url',''))+field('sha256','소스 SHA-256',f.get('sha256',''))+select('system','빌드 템플릿',[(x,x) for x in ['gnu','cmake','meson']],f.get('system','gnu'))+'</fieldset>'
    body+="<fieldset data-registration-kind='documentation'><legend>문서 패키지</legend><p>내용을 /usr/share/doc/패키지이름/README.txt에 설치합니다.</p>"+field('content','문서 내용',f.get('content',''),area=True)+'</fieldset>'
    for kind,label in [('runtime','실행 의존 패키지'),('build','빌드 의존 패키지')]:body+=picker(kind+'_dependencies',label,f.get(kind+'_dependencies',''),store.known_packages())
    body+=field('reason','등록 사유',f.get('reason',''))+"<div class='catalog-actions'><button class='secondary' name='action' value='preview'>등록 전 검토</button><button name='action' value='save'>레시피 등록</button></div></form></div>"
    return body


def preview_page(form, state, route):
    import ki2installcatalog
    body=intro(state)+"<div class='panel'><h2>저장 전 검토</h2><p>아직 저장하지 않았습니다. 아래 구성과 변경 사유를 확인하세요.</p>"
    if route=='/package-groups/save':
        result=ki2installcatalog.expand(state['catalog'],[form['id']])
        enabled=set();disabled=set();targets=[]
        for g in state['catalog']['groups']:
            if g['id'] in result['groups']:
                enabled.update(g['services'].get('enable',[]));disabled.update(g['services'].get('disable',[]))
                if g['services'].get('default_target'):targets.append(g['id']+': '+g['services']['default_target'])
        body+=f"<p>그룹: {esc(', '.join(result['groups']))}</p><p>직접 포함 패키지 {len(result['packages'])}개: {esc(', '.join(result['packages']))}</p><p>최종 시작 대상: {esc(result['default_target'])}</p>"
        if enabled&disabled:body+=f"<p class='catalog-error'>서비스 정책 충돌 · 현재 비활성화 우선: {esc(', '.join(sorted(enabled&disabled)))}</p>"
        if len(set(t.split(': ',1)[1] for t in targets))>1:body+=f"<p class='catalog-error'>시작 대상 지정이 여러 개입니다. 선행 그룹 이후 선택 그룹이 적용됩니다: {esc(', '.join(targets))}</p>"
    else:
        raw=state['recipes'][form['name']];body+='<dl>'+''.join(f'<dt>{esc(k)}</dt><dd>{esc(raw[k])}</dd>' for k in ['name','version','summary','license','source','dependencies','build'])+'</dl>'
    body+=f"<p>사유: {esc(form.get('reason',''))}</p><form method='post' action='{route}'>"+''.join(hidden(k,v) for k,v in form.items() if k not in ['action','_actor','_csrf','next'])+"<button name='action' value='save'>검토한 구성 저장</button></form><p>입력값을 변경하려면 브라우저에서 뒤로 이동하세요.</p></div>"
    return body


def history_page(store):
    state = store.current()
    content = intro(state) + "<div class='panel'><h2>변경 이력</h2><table><tr><th>리비전</th><th>시각</th><th>작성자</th><th>변경</th><th>사유</th></tr>" + ''.join(f"<tr><td><a href='/package-groups/export?revision={r['revision']}'>r{r['revision']}</a></td><td>{esc(r['at'])}</td><td>{esc(r.get('actor','local'))}</td><td>{esc(r['change'])}</td><td>{esc(r['reason'])}</td></tr>" for r in reversed(state['history'][-100:])) + '</table></div>'
    return content + "<div class='panel'><h2>이전 편집본 복원</h2><p>전체 그룹·프로필 연결·메타정보를 선택한 리비전으로 되돌립니다. 현재 이력과 이미 요청한 빌드는 보존하며, 새 리비전으로 기록합니다. 초기 구성은 r0입니다.</p><form method='post' action='/package-groups/restore'>" + hidden('revision',state['revision']) + field('target','복원할 리비전') + field('reason','복원 사유') + '<button>편집본 복원</button></form></div>'
