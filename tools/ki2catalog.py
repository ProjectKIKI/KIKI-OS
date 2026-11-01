"""Revisioned web authoring for future package builds and installer groups."""
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import ki2installcatalog
import ki2catalogrecipes

GROUP_FILE = Path('distro/sources/ki2ctl/usr/share/ki2/package-groups.json')
ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')


class Conflict(ValueError):
    pass


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + uuid.uuid4().hex)
    with temp.open('xb') as stream:
        stream.write(encoded(data)); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)


def words(value):
    return list(dict.fromkeys(re.split(r'[,\s]+', value.strip()))) if value.strip() else []


class Catalog:
    def __init__(self, root, source, build):
        self.root, self.source, self.build = Path(root), Path(source), build
        self.lock = threading.RLock()

    def current(self):
        path = self.root / 'current.json'
        if path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            data.setdefault('recipes',{});data.setdefault('recipe_payloads',{})
            return data
        seed = self.root / 'seed.json'
        path=seed if seed.exists() else self.source / GROUP_FILE
        return dict(schema='kiki-web-catalog-v1', revision=0,
                    catalog=ki2installcatalog.load(path) if path.exists() else dict(schema='ki2-package-groups-v1',groups=[],profiles=[]), metadata={}, recipes={}, recipe_payloads={}, history=[])

    def recipes(self, source=None, state=None):
        return ki2catalogrecipes.merge(self.build,source or self.source,state if state is not None else self.current())

    def known_packages(self, state=None):
        names = set(self.build.load_recipes(self.source / 'distro/recipes'))
        names.update((state if state is not None else self.current()).get('recipes',{}))
        seed = self.root / 'seed.json'
        for group in ki2installcatalog.load(seed if seed.exists() else self.source / GROUP_FILE)['groups']:
            for values in group['packages'].values():
                names.update(values)
        return names

    def validate(self, data):
        groups = data['catalog']['groups']
        ids = [g['id'] for g in groups]
        if len(set(ids)) != len(ids) or any(not ID.fullmatch(v) for v in ids):
            raise ValueError('그룹 ID는 중복 없는 영문 소문자·숫자·하이픈이어야 합니다.')
        ki2catalogrecipes.validate(self.build,self.source,data)
        known = self.known_packages(data)
        for g in groups:
            if any(n not in ids for n in g['requires']):
                raise ValueError(g['id'] + ': 존재하지 않는 선행 그룹입니다.')
            sections = list(g['packages'].values())
            packages = [n for values in sections for n in values]
            if len(packages) != len(set(packages)):
                raise ValueError(g['id'] + ': 필수·기본·선택 패키지가 중복됩니다.')
            unknown = set(packages) - known
            if unknown:
                raise ValueError('등록되지 않은 패키지: ' + ', '.join(sorted(unknown)))
            for values in (g['services'].get('enable', []), g['services'].get('disable', [])):
                if any(not re.fullmatch(r'[A-Za-z0-9_@.:-]+\.(service|socket|timer|target|path)', n) for n in values):
                    raise ValueError('서비스는 systemd 유닛 이름으로 입력하세요.')
            if set(g['services'].get('enable', [])) & set(g['services'].get('disable', [])):
                raise ValueError('같은 서비스를 활성화와 비활성화에 함께 지정할 수 없습니다.')
            ki2installcatalog.expand(data['catalog'], [g['id']])
        for p in data['catalog']['profiles']:
            if not p['groups'] or any(n not in ids for n in p['groups']):
                raise ValueError(p['id'] + ': 프로필에 연결된 그룹이 없습니다.')

    def save(self, revision, reason, mutate, actor='local', dry_run=False):
        with self.lock:
            data = self.current()
            if str(data['revision']) != str(revision):
                raise Conflict('다른 변경이 먼저 저장되었습니다. 화면을 새로고침하고 다시 검토하세요.')
            if not 4 <= len(reason.strip()) <= 500:
                raise ValueError('변경 사유를 4~500자로 입력하세요.')
            before = copy.deepcopy(data)
            detail = mutate(data)
            self.validate(data)
            if dry_run:return data
            data['revision'] += 1
            data['history'].append(dict(revision=data['revision'], at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        reason=reason.strip(), change=detail, actor=actor))
            # Each committed revision is retained; current is the atomic commit point.
            atomic(self.root / 'revisions' / (str(before['revision']) + '.json'), before)
            atomic(self.root / 'revisions' / (str(data['revision']) + '.json'), data)
            atomic(self.root / 'current.json', data)
            return data

    def group(self, form):
        name = form.get('id', '').strip()
        if not ID.fullmatch(name):
            raise ValueError('그룹 ID 형식을 확인하세요.')

        def mutate(data):
            groups = data['catalog']['groups']
            old = next((g for g in groups if g['id'] == name), None)
            action = form.get('action', 'save')
            if action == 'delete':
                if old is None:
                    raise ValueError('삭제할 그룹이 없습니다.')
                groups.remove(old)
                return '그룹 삭제: ' + name
            if form.get('create') == 'yes' and old:
                raise ValueError('이미 사용 중인 그룹 ID입니다.')
            if form.get('create') != 'yes' and old is None:
                raise ValueError('수정할 그룹이 없습니다.')
            item = dict(id=name)
            for field in ['name_ko', 'name_en', 'description_ko']:
                value = form.get(field, '').strip()
                if not value or len(value) > (2000 if field == 'description_ko' else 100):
                    raise ValueError('그룹 이름과 설명을 입력하세요. 이름은 100자, 설명은 2,000자까지입니다.')
                item[field] = value
            item['requires'] = words(form.get('requires', ''))
            item['packages'] = {k: words(form.get(k, '')) for k in ['mandatory', 'default', 'optional']}
            item['services'] = {k: words(form.get(k, '')) for k in ['enable', 'disable']}
            target = form.get('default_target', '')
            if target not in {'', 'multi-user.target', 'graphical.target'}:
                raise ValueError('기본 시작 대상을 확인하세요.')
            if target:
                item['services']['default_target'] = target
            item['selectable'] = form.get('selectable') == 'yes'
            if old:
                groups[groups.index(old)] = item
            else:
                groups.append(item)
            memberships = words(form.get('profiles', ''))
            if set(memberships) - {p['id'] for p in data['catalog']['profiles']}:
                raise ValueError('존재하지 않는 프로필입니다.')
            for p in data['catalog']['profiles']:
                if p['id'] in memberships and name not in p['groups']:
                    p['groups'].append(name)
                elif p['id'] not in memberships and name in p['groups']:
                    p['groups'].remove(name)
            return '그룹 저장: ' + name
        return self.save(form.get('revision'), form.get('reason', ''), mutate, form.get('_actor', 'local'),form.get('action')=='preview')

    def register(self, form):
        raw,payload=ki2catalogrecipes.from_form(form)
        def mutate(data):
            if raw['name'] in self.known_packages(data):raise ValueError('이미 등록된 패키지 이름입니다.')
            data.setdefault('recipes',{})[raw['name']]=raw
            if payload:data.setdefault('recipe_payloads',{})[raw['name']]=payload
            return '패키지 등록: '+raw['name']
        return self.save(form.get('revision'),form.get('reason',''),mutate,form.get('_actor','local'),form.get('action')=='preview')

    def metadata(self, form):
        recipes = self.recipes()
        name = form.get('name', '')
        if name not in recipes:
            raise ValueError('등록된 소스 패키지를 선택하세요.')
        recipe = recipes[name]

        def mutate(data):
            if form.get('action') == 'reset':
                data['metadata'].pop(name, None)
                return '메타정보 원본 복원: ' + name
            previous = data['metadata'].get(name, {})
            if not str(recipe.release).isdigit():
                raise ValueError('숫자 release를 사용하는 패키지만 웹에서 메타정보를 변경할 수 있습니다.')
            patch = {'base_version': recipe.version,
                     'release': str(max(int(recipe.release), int(previous.get('release', recipe.release))) + 1)}
            for field, limit in [('summary', 1000), ('license', 200), ('tier', 64)]:
                value = form.get(field, '').strip()
                if not value or len(value) > limit or any(ord(c) < 32 for c in value):
                    raise ValueError(field + ': 길이와 형식을 확인하세요.')
                patch[field] = value
            data['metadata'][name] = patch
            return '메타정보 저장: ' + name
        return self.save(form.get('revision'), form.get('reason', ''), mutate, form.get('_actor', 'local'))

    def restore(self, form):
        target = form.get('target', '')
        if not re.fullmatch(r'0|[1-9][0-9]{0,8}', target):
            raise ValueError('복원할 리비전을 확인하세요.')
        try:
            prior = json.loads((self.root / 'revisions' / (target + '.json')).read_text(encoding='utf-8'))
        except OSError as exc:
            raise ValueError('복원할 리비전이 없습니다.') from exc

        def mutate(data):
            metadata = copy.deepcopy(prior['metadata'])
            for name, patch in metadata.items():
                patch['release'] = str(max(int(patch['release']), int(data['metadata'].get(name, {}).get('release', '0'))) + 1)
            data.update(catalog=copy.deepcopy(prior['catalog']), metadata=metadata,
                        recipes=copy.deepcopy(prior.get('recipes',{})),recipe_payloads=copy.deepcopy(prior.get('recipe_payloads',{})))
            return '편집본 복원: r' + target
        return self.save(form.get('revision'), form.get('reason', ''), mutate, form.get('_actor', 'local'))

    @staticmethod
    def apply_metadata(raw, state):
        patch = state['metadata'].get(raw['name'])
        if patch:
            if str(raw['version']) != patch['base_version']:
                raise ValueError(raw['name'] + ': 원본 버전이 변경되었습니다. 메타정보를 다시 검토하세요.')
            raw.update({k: patch[k] for k in ['summary', 'license', 'tier']})
            raw['release'] = str(max(int(raw.get('release', '1')) + 1, int(patch['release'])))
        return raw

    def freeze(self, directory, state=None, engine=None):
        state = self.current() if state is None else state
        if state['revision']:
            atomic(Path(directory) / 'catalog.json', state)
            engine = Path(engine or self.build.__file__)
            frozen_engine = Path(directory) / 'build-engine.py'
            shutil.copy2(engine, frozen_engine)
            return dict(revision=state['revision'], sha256=hashlib.sha256(encoded(state)).hexdigest(),
                        engine_sha256=hashlib.sha256(frozen_engine.read_bytes()).hexdigest())
        return None

    def materialize(self, source, target, state):
        """Create isolated build inputs; never edit a Git export or preserved tree in place."""
        source, target = Path(source), Path(target)
        if source != target:
            def ignored(directory, names):
                skip = {'.git', '.venv', '__pycache__', 'node_modules'}
                if Path(directory) == source:
                    skip |= {'build', 'artifacts'}
                return set(names) & skip
            shutil.copytree(source, target, ignore=ignored, symlinks=True)
        recipes = self.recipes(source,state)
        shutil.rmtree(target / 'distro/recipes')
        raw = []
        for r in recipes.values():
            item = {k: copy.deepcopy(getattr(r, k)) for k in ['name', 'version', 'release', 'summary', 'license', 'tier', 'source', 'dependencies', 'build']}
            item['architectures'] = list(r.architectures)
            item = self.apply_metadata(item, state)
            if r.name in {'ki2ctl', 'kiki-installer-tui', 'kiki-installer-gtk'}:
                item['release'] = str(max(int(item['release']), int(r.release) + state['revision']))
            raw.append(item)
        atomic(target / 'distro/recipes/catalog.json', {'recipes': raw})
        for name,files in state.get('recipe_payloads',{}).items():
            if name not in state.get('recipes',{}):raise ValueError('등록 패키지 본문 불일치')
            for relative,content in files.items():
                if relative!='usr/share/doc/'+name+'/README.txt':raise ValueError('지원하지 않는 등록 패키지 파일 경로')
                path=target/'distro/sources/web'/name/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('w',encoding='utf-8',newline='\n') as stream:stream.write(content)
        atomic(target / GROUP_FILE, state['catalog'])
        for path, content in ki2installcatalog.generated(state['catalog']).items():
            out = target / path.relative_to(ki2installcatalog.ROOT)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding='utf-8')
        return target
