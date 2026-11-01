"""Terminal Lab presentation for authenticated builder pages; worker markup stays intact."""
from html import escape, unescape
from html.parser import HTMLParser
import re

from ki2users import ROLES

NAV = (
    ('빌드 콘솔', (('/', '운영 현황', 'overview'), ('/jobs', '빌드 작업', 'jobs'),
                  ('/package-build', '개별 패키지 빌드', 'package'), ('/kernel-build', '커널 빌드', 'cpu'), ('/packages', '패키지', 'package'),
                  ('/package-groups', '패키지 그룹 관리', 'package'), ('/profiles', '구성 프로필', 'file'), ('/artifacts', '산출물', 'file'),
                  ('/security', '검증 현황', 'shield'),('/assistant','Local LLM 보조','cpu'),('/operations','운영·복구','settings'))),
    ('시스템 관리', (('/git', 'Git 소스 동기화', 'branch'), ('/deploy', '서버 구성', 'server'), ('/releases', '릴리즈 관리', 'tag'),
                   ('/versions', '소스·바이너리 버전', 'branch'), ('/updates', '업데이트 관리', 'package'), ('/iso-build', '버전별 ISO', 'disc'),
                   ('/cpu-profiles', 'CPU 대상 관리', 'cpu'))),
    ('계정', (('/users', '사용자 관리', 'user'), ('/account', '내 계정', 'settings'))),
)

ICONS = {
    'overview': '<path d="M3 13h4v8H3zM10 9h4v12h-4zM17 3h4v18h-4z"/>',
    'jobs': '<path d="M9 5h12M9 12h12M9 19h12"/><circle cx="3" cy="5" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="19" r="1"/>',
    'package': '<path d="m12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8M7.5 5.5l9 5"/>',
    'file': '<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h8"/>',
    'shield': '<path d="m12 3 8 3v6c0 4-5 8-8 9-3-1-8-5-8-9V6zM8 12l3 3 5-6"/>',
    'server': '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M15 6.5h3M15 17.5h3"/>',
    'tag': '<path d="M3 3h9l9 9-9 9-9-9z"/><circle cx="8" cy="8" r="1"/>',
    'branch': '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M6 12h6c4 0 6-1 6-3"/>',
    'disc': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/>',
    'cpu': '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v5M15 1v5M9 18v5M15 18v5M1 9h5M1 15h5M18 9h5M18 15h5M9 9h6v6H9z"/>',
    'user': '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2z"/>',
    'settings': '<path d="m9 3 6 0 1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z"/><circle cx="12" cy="12" r="3"/>',
    'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
}


def icon(name):
    return '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+ICONS[name]+'</svg>'


def brand():
    # Immutable flat symbol from Terminal Lab's site-brand/terminal-lab-logo.jsx.
    return ('<svg class="tl-symbol" aria-hidden="true" viewBox="0 0 64 64">'
            '<rect width="64" height="64" rx="12" fill="#192072"/>'
            '<path d="M20 22L32 32L20 42M36 44H48" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def current_nav(route):
    if route.startswith('/library/'):
        return '/versions'
    return next((path for _, entries in NAV for path, _, _ in entries
                 if path != '/' and (route == path or route.startswith(path+'/'))), '/')


def chrome(session, route, title):
    selected = current_nav(route)
    items = []
    for group, entries in NAV:
        links = []
        for path, label, glyph in entries:
            if path == '/users' and (session.get('role') != 'admin' or session.get('must_change')):
                continue
            active = ' aria-current="page"' if path == selected else ''
            links.append('<a href="'+path+'"'+active+'>'+icon(glyph)+'<span>'+label+'</span></a>')
        items.append('<div class="tl-nav-group"><p>'+group+'</p>'+''.join(links)+'</div>')
    rail = ''.join('<a href="'+path+'" aria-label="'+label+'" title="'+label+'"'+(' aria-current="page"' if selected == path else '')+'>'+icon(glyph)+'</a>'
                   for path, label, glyph in [('/', '운영 현황', 'overview'), ('/jobs', '빌드 작업', 'jobs'),
                      ('/package-build', '개별 패키지 빌드', 'package'), ('/releases', '릴리즈 관리', 'tag'),
                      ('/iso-build', '버전별 ISO', 'disc'), ('/account', '내 계정', 'user')])
    return ('<a class="tl-skip" href="#build-content">본문으로 건너뛰기</a>'
            '<aside class="tl-rail" aria-label="빠른 이동"><a href="/" class="tl-rail-brand" aria-label="KIKI OS 홈">'+brand()+'</a>'+rail+'</aside>'
            '<aside class="tl-sidebar" id="build-navigation"><a class="tl-wordmark" href="/" aria-label="KIKI OS 빌드 콘솔"><strong><span>KIKI</span> OS</strong><small>TERMINAL LAB</small></a>'
            '<nav class="tl-navigation" aria-label="빌드 콘솔 메뉴">'+''.join(items)+'</nav></aside>'
            '<header class="tl-topbar"><button type="button" class="tl-menu-toggle" aria-label="메뉴 열기" aria-expanded="false" aria-controls="build-navigation">'+icon('menu')+'</button>'
            '<div class="tl-breadcrumb"><span>빌드 콘솔</span><span aria-hidden="true">/</span><strong>'+escape(title)+'</strong></div>'
            '<div class="tl-account"><a href="/account">'+escape(ROLES[session['role']])+' · '+escape(session['name'])+'</a>'
            '<form method="post" action="/logout"><input type="hidden" name="_csrf" value="'+escape(session['csrf'], quote=True)+'"><button class="tl-secondary">로그아웃</button></form></div></header>')


def document(session, route, title, content, head='', heading=True, description='', actions=''):
    heading_html = ('<div class="tl-page-heading"><div><h1>'+escape(title)+'</h1>'+('<p>'+description+'</p>' if description else '')+'</div>'
                    +('<div class="tl-heading-actions">'+actions+'</div>' if actions else '')+'</div>') if heading else ''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(title)+' · KIKI OS</title>'+head+'<link rel="stylesheet" href="/build-theme.css"><script src="/auth/session.js" defer></script><script src="/build-theme.js" defer></script>'
            '</head><body class="tl-app" data-build-section="'+current_nav(route).strip('/')+'" data-build-route="'+escape(route, quote=True)+'">'+chrome(session, route, title)
            +'<main id="build-content" class="tl-content">'+heading_html+content+'</main><footer class="tl-footer">KIKI OS · TERMINAL LAB</footer></body></html>')


VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class WorkerPage(HTMLParser):
    """Retain worker controls, IDs, scripts, logs and forms, replacing only its shell."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.head, self.content, self.stack = [], [], []
        self.region, self.skip = '', False

    def append(self, value):
        if self.region == 'head' and not self.skip:
            self.head.append(value)
        elif self.region == 'body' and not self.skip:
            self.content.append(value)

    def handle_starttag(self, tag, attrs):
        if tag in {'head', 'body'}:
            self.region = tag
            return
        if not self.region:
            return
        root = not self.stack
        if root and ((self.region == 'head' and tag == 'title') or (self.region == 'body' and tag in {'header', 'nav'})):
            self.skip = True
        if not (root and tag == 'main'):
            self.append(self.get_starttag_text())
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag in {'head', 'body'}:
            self.region = ''
            return
        if not self.region:
            return
        if not (len(self.stack) == 1 and tag == 'main'):
            self.append('</'+tag+'>')
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        if not self.stack:
            self.skip = False

    def handle_data(self, value): self.append(value)
    def handle_entityref(self, value): self.append('&'+value+';')
    def handle_charref(self, value): self.append('&#'+value+';')
    def handle_comment(self, value): self.append('<!--'+value+'-->')


def decorate(text, session, route):
    parser = WorkerPage(); parser.feed(text); parser.close()
    title_match = re.search(r'<header\b[^>]*>\s*<h1\b[^>]*>(.*?)</h1>', text, re.S | re.I)
    if not title_match:
        title_match = re.search(r'<title\b[^>]*>(.*?)</title>', text, re.S | re.I)
    title = unescape(re.sub('<[^>]*>', '', title_match[1])).removesuffix(' · KIKI OS') if title_match else '빌드 콘솔'
    content = ''.join(parser.content)
    description, actions = '', ''
    if route == '/releases':
        intro = re.match(r"(\s*<section class='panel'><h2>.*?</h2>)<p>(.*?)</p><p>(.*?)</p>", content, re.S)
        if intro:
            description, actions = intro[2], intro[3].replace(' · ', ' ')
            actions = actions.replace("href='/releases/new'", "class='tl-primary-link' href='/releases/new'").replace("href='/iso-build'", "class='tl-secondary-link' href='/iso-build'")
            content = intro[1]+content[intro.end():]
            content = content.replace("id='release-search'", "id='release-search' placeholder='릴리즈 검색'", 1)
        content = re.sub(r'<td>(후보|구성 잠금|보관됨|기존 보관 · 관리 미등록)</td>',
                         lambda m: '<td><span class="tl-state'+(' tl-state-candidate' if m[1] == '후보' else '')+'">'+m[1]+'</span></td>', content)
    return document(session, route, title, content, ''.join(parser.head), description=description, actions=actions)


def public_page(title, content):
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(title)+' · KIKI OS</title><link rel="stylesheet" href="/build-theme.css"></head>'
            '<body class="tl-public"><header class="tl-public-header">'+brand()+'<strong>TERMINAL LAB</strong><span>/ KIKI OS</span></header>'
            '<main class="tl-login"><div class="tl-login-brand"><div class="tl-wordmark"><strong><span>KIKI</span> OS</strong><small>TERMINAL LAB</small></div>'
            '<p>패키지 · OS 빌드 운영 콘솔</p></div><section class="tl-login-panel">'+content+'</section></main>'
            '<footer class="tl-public-footer">KIKI OS · TERMINAL LAB</footer></body></html>').encode()
