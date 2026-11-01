"""Validated web recipe templates. Registration never builds or publishes."""
import copy
import re
from pathlib import Path
from urllib.parse import urlsplit

NAME = re.compile(r'[a-z0-9][a-z0-9+_.-]{0,95}')
SYSTEMS = ('gnu', 'cmake', 'meson')


def from_form(form):
    name = form.get('name', '').strip()
    if not NAME.fullmatch(name): raise ValueError('패키지 이름은 영문 소문자·숫자와 +_.-로 입력하세요.')
    version = form.get('version', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.~-]{0,63}', version): raise ValueError('패키지 버전 형식을 확인하세요.')
    raw = dict(name=name, version=version, release='1')
    for key, limit in [('summary', 1000), ('license', 200), ('tier', 64)]:
        value = form.get(key, '').strip()
        if not value or len(value)>limit or any(ord(c)<32 for c in value): raise ValueError(key+': 길이와 형식을 확인하세요.')
        raw[key] = value
    arch = form.get('arch', 'x86_64')
    if arch not in ['x86_64', 'all']: raise ValueError('지원하는 아키텍처를 선택하세요.')
    raw['architectures'] = [arch]
    raw['dependencies'] = {k:list(dict.fromkeys(re.split(r'[,\s]+',form.get(k+'_dependencies','').strip()))) if form.get(k+'_dependencies','').strip() else [] for k in ['build','runtime']}
    if any(not NAME.fullmatch(v) for xs in raw['dependencies'].values() for v in xs): raise ValueError('의존 패키지 이름 형식을 확인하세요.')
    payload = {}
    if form.get('kind','source') not in ['source','documentation']:raise ValueError('지원하는 등록 방식을 선택하세요.')
    if form.get('kind','source') == 'documentation':
        content = form.get('content','').strip()
        if not content or len(content.encode('utf-8'))>16384 or '\x00' in content: raise ValueError('문서 내용은 1~16KiB로 입력하세요.')
        raw.update(source={'type':'local','path':'distro/sources/web/'+name},build={'system':'copy','skip_sysroot':True})
        payload['usr/share/doc/'+name+'/README.txt'] = content+'\n'
    else:
        url = form.get('url','').strip(); parsed = urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or len(url)>2048:
            raise ValueError('인증 정보가 없는 HTTPS 소스 압축파일 주소를 입력하세요.')
        try:port=parsed.port
        except ValueError:raise ValueError('소스 URL 포트를 확인하세요.') from None
        if port not in [None,443] or parsed.query:raise ValueError('인증·쿼리가 없는 공식 HTTPS 압축파일 주소를 입력하세요.')
        import ipaddress
        if parsed.hostname.lower() in ['localhost','localhost.localdomain'] or parsed.hostname.lower().endswith(('.local','.internal')):
            raise ValueError('공식 공개 소스 주소를 입력하세요.')
        try:
            if not ipaddress.ip_address(parsed.hostname).is_global: raise ValueError('공식 공개 소스 주소를 입력하세요.')
        except ValueError as error:
            if str(error)=='공식 공개 소스 주소를 입력하세요.': raise
        digest = form.get('sha256','').strip().lower()
        if not re.fullmatch(r'[a-f0-9]{64}',digest) or len(set(digest))==1: raise ValueError('검증한 소스 SHA-256 64자리를 입력하세요.')
        system = form.get('system','gnu')
        if system not in SYSTEMS: raise ValueError('지원하는 빌드 템플릿을 선택하세요.')
        if arch=='all': raise ValueError('소스 컴파일 패키지는 x86_64를 선택하세요.')
        raw.update(source={'type':'url','url':url,'sha256':digest},build={'system':system})
    return raw,payload


def merge(build, source, state):
    recipes=build.load_recipes(Path(source)/'distro/recipes')
    for name,raw in state.get('recipes',{}).items():
        if name in recipes: raise ValueError(name+': 원본 소스에도 같은 레시피가 있습니다. 웹 편집본을 검토하세요.')
        recipes[name]=build.normalize_recipe(copy.deepcopy(raw),Path(source)/'distro/recipes/web-catalog.json')
    return recipes


def validate(build, source, state):
    recipes=merge(build,source,state)
    authored=state.get('recipes',{})
    for name in authored:
        recipe=recipes[name]
        if recipe.name!=name: raise ValueError('등록 패키지 이름 불일치')
        unknown={n for xs in recipe.dependencies.values() for n in xs}-set(recipes)
        if unknown: raise ValueError('등록되지 않은 의존 패키지: '+', '.join(sorted(unknown)))
    active=set();done=set()
    def visit(name):
        if name in active: raise ValueError('새 패키지 의존성이 순환합니다: '+name)
        if name in done or name not in authored:return
        active.add(name)
        for xs in recipes[name].dependencies.values():
            for dep in xs:visit(dep)
        active.remove(name);done.add(name)
    for name in authored:visit(name)
    return recipes
