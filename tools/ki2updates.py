"""Pinned maintenance updates, shared CI builds and signed VM validation gates."""
import copy
import datetime as dt
import html
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

import ki2origins
import ki2upstream
from ki2security import Security
from ki2updatebuild import digest, read_plan

CRITICAL={'linux','linux-headers','glibc','systemd','libsystemd','shadow','linux-pam','gdm','mutter','gnome-shell','gtk','ki2ctl'}
ACTIVE={'preparing','queued','building'}


class Updates:
    def __init__(self,lib,core):
        self.lib,self.c=lib,core;self.root=lib.root/'updates'
        for name in ['proposals','plans','evidence','downloads']:(self.root/name).mkdir(parents=True,exist_ok=True)
        self.recipe_file=Path(__file__).with_name('update-recipes.json')
        self.security=Security(self)

    def config(self):
        p=self.root/'config.json'
        return self.c.read(p) if p.exists() else {'enabled':False,'interval_seconds':21600}

    def recipes(self):
        if not self.recipe_file.exists():return {}
        stat=self.recipe_file.stat();key=(str(self.recipe_file),stat.st_size,stat.st_mtime_ns)
        if getattr(self,'_recipes_key',None)!=key:self._recipes_key=key;self._recipes=self.c.read(self.recipe_file)
        return self._recipes
    def list(self):return sorted([self.c.read(p) for p in (self.root/'proposals').glob('*.json')],key=lambda r:r['created_at'],reverse=True)
    def get(self,key):
        if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('올바르지 않은 업데이트 ID')
        return self.c.read(self.root/'proposals'/(key+'.json'))
    def save(self,row):self.c.save(self.root/'proposals'/(row['id']+'.json'),row)
    def checks(self):
        p=self.root/'checks.json'
        return self.c.read(p) if p.exists() else {'rows':[],'notifications':[],'checked_at':None}
    def stable(self):
        p=self.root/'stable.json'
        return self.c.read(p) if p.exists() else {}

    def baseline(self,name):
        if not self.c.valid_id(name):raise ValueError('기준 스냅샷을 선택하세요.')
        path=self.lib.root/'snapshots'/name/'manifest.json';snap=self.c.read(path)
        if self.c.sha(path.parent/'repo/index.x86_64.json')!=snap['index_sha256']:raise ValueError('기준 인덱스 변경')
        if self.c.sha(path.parent/'repo/metadata.x86_64.json')!=snap['metadata_sha256']:raise ValueError('기준 서명 메타데이터 변경')
        if not self.lib.repo.verify_metadata_file(path.parent/'repo/metadata.x86_64.json',path.parent/'candidate.pub'):raise ValueError('기준 서명 오류')
        return snap,{n:self.lib.catalog['binaries'][h] for n,h in snap['packages'].items()}

    def source_rows(self,base):
        _,packages=self.baseline(base)
        try:audits=ki2origins.load_audit(Path(__file__).with_name('source-origins.json'))
        except OSError:audits={}
        rows=[]
        for n,p in packages.items():
            origin=ki2origins.source_origin(ki2origins.audited_record(p,p,audits))
            if origin['kind']=='upstream':rows.append(dict(name=n,version=p['version'],url=origin['url']))
            else:rows.append(dict(name=n,version=p['version'],url=''))
        return rows

    def check(self,job):
        base=job['values'].get('base') or self.config().get('baseline')
        self.lib.update(job,phase='원본 배포처의 안정 버전 확인 · 레시피 변경 없음')
        rows=ki2upstream.check_all(self.source_rows(base),self.c.public_https)
        previous=self.checks()
        available={r['name']+'@'+r['latest']['version'] for r in rows if r['status']=='available'}
        uncertain={r['name'] for r in rows if r['status']=='error'}
        notices=[r for r in previous.get('notifications',[]) if r['key'] in available or r['name'] in uncertain]
        known={r['key'] for r in notices}
        for row in rows:
            if row['status']=='available':
                key=row['name']+'@'+row['latest']['version']
                if key not in known:notices.append({'key':key,'name':row['name'],'version':row['latest']['version'],'at':self.c.now(),'read':False})
        result={'base':base,'checked_at':self.c.now(),'rows':rows,'notifications':notices[-2000:]}
        self.c.save(self.root/'checks.json',result)
        return {'available':sum(r['status']=='available' for r in rows),'errors':sum(r['status']=='error' for r in rows),'checked':len(rows)}

    def acknowledge(self):
        with self.lib.lock:
            checks=self.checks()
            for notice in checks['notifications']:notice['read']=True
            self.c.save(self.root/'checks.json',checks)

    @staticmethod
    def affected(packages,name):
        result={name}
        while True:
            added={n for n,p in packages.items() if any(d in result for group in ['runtime','build'] for d in p.get('dependencies',{}).get(group,[]))}
            if added<=result:return sorted(result-{name})
            result|=added

    def recipe_for(self,name,package):
        saved=self.recipes().get(name)
        if not saved:raise ValueError(name+': 검토된 소스 빌드 레시피가 없습니다.')
        raw=copy.deepcopy(saved['recipe']);recipe=self.lib.build.normalize_recipe(raw,Path('reviewed-update.json'))
        if recipe.digest!=package.get('recipe_digest'):
            previous=package.get('provenance',{});key=previous.get('update_id','')
            if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError(name+': 기준 패키지와 보존 레시피의 지문이 다릅니다.')
            plan=read_plan(self.root/'plans'/(key+'.json'),previous.get('update_plan'))
            raw=copy.deepcopy(next(r for r in plan['recipes'] if r['name']==name));recipe=self.lib.build.normalize_recipe(raw,Path('frozen-update.json'))
            if recipe.digest!=package.get('recipe_digest'):raise ValueError(name+': 이전 업데이트 레시피 지문 불일치')
        if recipe.source.get('type')=='local' and (Path(recipe.source['path']).is_absolute() or '..' in Path(recipe.source['path']).parts):
            raise ValueError(name+': 임시 staging 레시피입니다. 실제 소스 빌드 레시피 검토가 필요합니다.')
        if recipe.build.get('system')=='kernel':raise ValueError(name+': 새 initramfs를 함께 생성·검증하는 커널 업데이트 경로가 필요합니다. 현재는 커널·ISO 빌드 화면을 사용하세요.')
        if recipe.build.get('system') in {'stage2-stub','host-files','prebuilt'}:raise ValueError(name+': 업데이트에 사용할 수 없는 빌드 방식입니다.')
        return raw

    def create(self,data):
        with self.lib.lock:
            base=data.get('base','');snap,packages=self.baseline(base);name=data.get('package','')
            if name not in packages:raise ValueError('기준 구성의 패키지를 선택하세요.')
            old=packages[name];raw=self.recipe_for(name,old)
            version=data.get('version','').strip() or old['version']
            ki2upstream.version_key(version)
            def next_release(n,v):
                prior=[int(p['release']) for p in self.lib.catalog['binaries'].values() if p['name']==n and p['version']==v]
                prior.extend(int(r['release']) for candidate in self.list() for r in candidate['recipes'] if r['name']==n and r['version']==v)
                return str(max(prior,default=0)+1)
            release=next_release(name,version)
            if self.lib.repo.latest_sort_key(dict(version=version,release=release))<=self.lib.repo.latest_sort_key(old):raise ValueError('업데이트 버전은 기준 버전보다 높아야 합니다.')
            notes=data.get('notes','').strip()
            if not 8<=len(notes)<=4000:raise ValueError('변경 내용과 호환성 판단을 8~4,000자로 적어 주세요.')
            mode=data.get('compatibility','rebuild')
            if mode not in {'compatible','rebuild'}:raise ValueError('호환성 정책을 선택하세요.')
            source=dict(raw['source']);source_url=data.get('url','').strip() or source.get('url','')
            expected=data.get('sha256','').strip()
            if source.get('type')=='url':
                if version!=old['version'] and not data.get('url','').strip():raise ValueError('원본 버전 변경에는 새 소스 주소가 필요합니다.')
                if not ki2origins.public_url(source_url):raise ValueError('인증 정보 없는 공개 HTTPS 원본 주소가 필요합니다.')
                self.c.public_https(source_url)
                if source_url==source.get('url') and version==old['version']:expected=expected or source['sha256']
                if expected and not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('SHA-256 형식을 확인하세요.')
                source={'type':'url','url':source_url,'sha256':expected}
            elif source_url:raise ValueError('자체 소스 패키지는 저장소 입력을 사용합니다.')
            raw.update(version=version,release=release,source=source)
            affected=self.affected(packages,name)
            additional=[v for v in re.split(r'[,\s]+',data.get('additional','').strip()) if v]
            if len(additional)>64 or any(n not in packages for n in additional):raise ValueError('함께 갱신할 패키지 이름을 확인하세요.')
            rebuild=list(dict.fromkeys([name]+additional+(affected if mode=='rebuild' else [])))
            recipes=[raw]
            for dep in rebuild[1:]:
                other=self.recipe_for(dep,packages[dep]);other['release']=next_release(dep,other['version']);recipes.append(other)
            catalog_path = self.lib.legacy_backend / 'build/ki2ci/catalog/current.json'
            state = self.c.read(catalog_path) if catalog_path.exists() else None
            for recipe in recipes:
                if state:
                    patch = state.get('metadata', {}).get(recipe['name'])
                    if patch:
                        if patch['base_version'] != str(packages[recipe['name']]['version']):
                            raise ValueError(recipe['name'] + ': 편집본과 기준 버전이 다릅니다. 메타정보를 다시 검토하세요.')
                        recipe.update({k: patch[k] for k in ['summary','license','tier']})
                for prerequisite in self.config().get('build_prerequisites',{}).get(recipe['name'],[]):
                    if prerequisite not in recipe['dependencies']['build']:recipe['dependencies']['build'].append(prerequisite)
                self.lib.build.normalize_recipe(recipe,Path('reviewed-update.json')) if recipe['source'].get('sha256') else None
            row={'id':uuid.uuid4().hex,'created_at':self.c.now(),'status':'proposed','base':base,
                 'base_manifest_sha256':self.c.sha(self.lib.root/'snapshots'/base/'manifest.json'),
                 'package':name,'from':old['version']+'-'+old['release'],'version':version,'release':release,'notes':notes,
                 'compatibility':mode,'affected':affected,'rebuild':rebuild,'recipes':recipes,
                 'requires_reboot':bool(set(rebuild)&CRITICAL),'history':[],'stable_before':self.stable().get('version')}
            if state:
                row['web_catalog'] = {'revision':state['revision']}
                if any(r['name']=='ki2ctl' for r in recipes):row['web_catalog']['catalog']=state['catalog']
            self.save(row);return row

    def prepare(self,job):
        row=self.get(job['values']['proposal'])
        if row['status'] not in {'proposed','prepare-failed','build-failed'}:raise ValueError('이미 제출했거나 준비 중인 업데이트입니다.')
        row['status']='preparing';row.pop('error',None);self.save(row)
        try:
            _,packages=self.baseline(row['base'])
            if self.c.sha(self.lib.root/'snapshots'/row['base']/'manifest.json')!=row['base_manifest_sha256']:raise ValueError('기준 스냅샷 변경')
            frozen=self.root/'plans'/(row['id']+'.json')
            if frozen.exists():
                plan=read_plan(frozen,row.get('plan_sha256'))
                if plan['base_manifest_sha256']!=row['base_manifest_sha256']:raise ValueError('기존 빌드 입력의 기준이 다릅니다.')
                return self.enqueue(row,plan)
            tools=[]
            available=set(packages)|{r['name'] for r in row['recipes']}
            for raw in row['recipes']:
                for name in raw.get('dependencies',{}).get('build',[]):
                    if name in available:continue
                    if name not in {'pkgconf','linux-headers'}:raise ValueError('기준에 없는 빌드 의존성의 소스 검토 필요: '+name)
                    candidate=next(r for r in self.lib.build.read_toml(self.lib.backend/'distro/recipes/core.toml')['recipe'] if r['name']==name)
                    if name=='linux-headers' and str(candidate['version'])!=packages.get('linux',{}).get('version'):raise ValueError('빌드 헤더와 기준 커널 버전 불일치')
                    self.lib.build.normalize_recipe(candidate,Path('frozen-build-tool.toml'))
                    if candidate['source'].get('type')!='url' or not candidate['source'].get('sha256'):raise ValueError('빌드 도구 소스를 고정할 수 없습니다.')
                    tools.append(candidate);available.add(name)
            for raw in row['recipes']+tools:
                if raw['source'].get('type')!='url':continue
                for number,source in enumerate([raw['source']]+raw['source'].get('extra',[])):
                    self.lib.update(job,phase=raw['name']+' 원본 다운로드·SHA-256 고정')
                    self.freeze_source(source,row['id']+'-'+raw['name']+'-'+str(number))
            local_archives=[]
            for raw in row['recipes']:
                if raw['source'].get('type')!='local':continue
                def modes(member):
                    if '__pycache__' in Path(member.name).parts or member.name.endswith('.pyc'):return None
                    if member.isdir():member.mode=0o755
                    elif member.isfile():member.mode=0o755 if '/usr/bin/' in member.name or '/usr/libexec/' in member.name else 0o644
                    return member
                inputs=list(dict.fromkeys([raw['source']['path']]+raw['source'].get('inputs',[])+raw.get('build',{}).get('inputs',[])))
                for index,relative in enumerate(inputs):
                    if Path(relative).is_absolute() or '..' in Path(relative).parts or any(c in relative for c in '*?['):raise ValueError('고정할 수 없는 로컬 소스 입력: '+relative)
                    override=Path(__file__).parent/'update-local-sources'/raw['name'] if index==0 else Path(__file__).parent/'update-local-extra'/raw['name']/relative
                    source=override if override.exists() else self.lib.backend/relative
                    if not source.exists():raise ValueError('로컬 소스 입력 누락: '+relative)
                    archive=self.root/'downloads'/(row['id']+'-'+raw['name']+'-'+str(index)+'.tar.gz')
                    with tarfile.open(archive,'w:gz',dereference=False) as tar:
                        group_data=row.get('web_catalog',{}).get('catalog') if raw['name']=='ki2ctl' and index==0 else None
                        group_name=relative+'/usr/share/ki2/package-groups.json'
                        def managed_modes(member):
                            if group_data and member.name==group_name:return None
                            return modes(member)
                        tar.add(source,arcname=relative,filter=managed_modes)
                        if group_data:
                            content=(json.dumps(group_data,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
                            member=tarfile.TarInfo(group_name);member.size=len(content);member.mode=0o644
                            tar.addfile(member,io.BytesIO(content))
                    h=self.c.sha(archive);self.lib.blob(archive,h)
                    local_archives.append({'name':raw['name'] if index==0 else raw['name']+':input:'+str(index),'path':relative,'sha256':h})
            plan={'schema':'ki2-update-build-v1','id':row['id'],'base':row['base'],'base_manifest_sha256':row['base_manifest_sha256'],
                  'packages':packages,'recipes':row['recipes'],'tool_recipes':tools,'notes':row['notes'],'compatibility':row['compatibility'],'affected':row['affected'],'local_archives':local_archives}
            if row.get('web_catalog'):plan['web_catalog']=row['web_catalog']
            plan['sha256']=digest(plan);path=self.root/'plans'/(row['id']+'.json')
            if path.exists() and self.c.read(path)!=plan:raise ValueError('기존 빌드 입력을 덮어쓸 수 없습니다.')
            self.c.save(path,plan);self.lib.commit()
            row['plan_sha256']=plan['sha256'];self.save(row)
            return self.enqueue(row,plan)
        except Exception as error:
            row.update(status='prepare-failed',error=str(error));self.save(row);raise

    def freeze_source(self,source,label):
        path=self.root/'downloads'/label;cached=self.lib.root/'objects'/source.get('sha256','unavailable')
        if source.get('sha256') and cached.is_file() and self.c.sha(cached)==source['sha256']:path=cached
        else:
            request=urllib.request.Request(self.c.public_https(source['url']),headers={'User-Agent':'KIKI-update-build/1.0'})
            with urllib.request.build_opener(self.c.HTTPSRedirect()).open(request,timeout=45) as response,path.open('wb') as out:
                total=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>1024**3:raise ValueError('소스 입력은 1GiB 이하만 지원합니다.')
                    out.write(chunk)
        actual=self.c.sha(path)
        if source.get('sha256') and source['sha256']!=actual:raise ValueError('원본 SHA-256 불일치: '+label)
        source['sha256']=actual;self.lib.blob(path,actual)
        self.lib.catalog['sources'].setdefault(actual,{'sha256':actual,'file':Path(urllib.parse.urlsplit(source['url']).path).name,'url':source['url'],'size':path.stat().st_size,'verified_at':self.c.now()})

    def enqueue(self,row,plan):
        # Reuse the ordinary compiler queue, including retries of the exact frozen plan.
        data=urllib.parse.urlencode({'plan':row['id'],'sha256':plan['sha256']}).encode()
        request=urllib.request.Request('http://127.0.0.1:8091/package-update-build',data=data,
            headers={'Host':'127.0.0.1:18090','Origin':'http://127.0.0.1:18090','Content-Type':'application/x-www-form-urlencoded'})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        try:urllib.request.build_opener(NoRedirect()).open(request,timeout=20)
        except urllib.error.HTTPError as response:
            if response.code!=303:
                body=response.read(4096).decode(errors='replace');message=re.search(r'<p>Message: (.*?)</p>',body,re.S)
                reason=html.unescape(message[1]) if message else re.sub('<[^>]+>',' ',body)
                raise ValueError('빌드 대기열 제출 실패 (HTTP '+str(response.code)+'): '+reason.strip()[:300])
            location=response.headers.get('Location','')
        else:raise ValueError('빌드 대기열 응답 형식 오류')
        match=re.fullmatch(r'/jobs/(\d{8}-\d{6}-\d{4})',location)
        if not match:raise ValueError('빌드 작업 ID 오류')
        row.pop('error',None);row.update(status='queued',build_job=match[1],plan_sha256=plan['sha256']);self.save(row)
        return {'proposal':row['id'],'build_job':match[1],'plan_sha256':plan['sha256']}

    def poll(self):
        for row in self.list():
            if row['status'] not in {'queued','building'}:continue
            try:
                paths=[root/'build/ki2ci/jobs'/row['build_job'] for root in {self.lib.backend,self.lib.legacy_backend}]
                folder=next(p for p in paths if (p/'metadata.json').exists());job=self.c.read(folder/'metadata.json')
                if job['status'] in {'pending','running'}:
                    if row['status']!='building' and job['status']=='running':row['status']='building';self.save(row)
                    continue
                if job['status']!='succeeded':raise ValueError('패키지 빌드 실패: '+job.get('error',job['status']))
                plan=read_plan(self.root/'plans'/(row['id']+'.json'),row['plan_sha256']);result=self.c.read(folder/'update-result.json')
                if result.get('plan_sha256')!=row['plan_sha256'] or set(result['packages'])!=set(row['rebuild']):raise ValueError('빌드 결과와 고정 계획 불일치')
                selection=dict(self.c.read(self.lib.root/'snapshots'/row['base']/'manifest.json')['packages'])
                from ki2integrity import audit_payload
                for raw in plan['recipes']:
                    name=raw['name'];built=result['packages'][name];path=folder/'packages/x86_64'/built['file']
                    if Path(built['file']).name!=built['file']:raise ValueError('산출물 파일명 오류')
                    recipe=self.lib.build.normalize_recipe(raw,Path('frozen-update.json'));manifest=self.lib.repo.read_package_manifest(path)
                    if manifest.get('recipe_digest')!=recipe.digest:raise ValueError('실제 레시피 지문 불일치')
                    audit=audit_payload(path)
                    if audit['errors']:raise ValueError('산출물 파일 명세 오류')
                    source=dict(raw['source'])
                    if source.get('type')=='local':
                        archive=next(a for a in plan.get('local_archives',[]) if a['name']==name)
                        source['sha256']=archive['sha256']
                        self.lib.catalog['sources'].setdefault(archive['sha256'],{'sha256':archive['sha256'],'file':name+'-source-'+row['id']+'.tar.gz'})
                    record=self.lib.add_binary(path,built['sha256'],'업데이트 후보 · 파일 명세·SHA 통과 · VM 검증 전',source,{'update_plan':row['plan_sha256'],'update_id':row['id'],'job_id':row['build_job'],'payload_audit':audit,'local_archives':plan.get('local_archives',[])})
                    selection[name]=record['sha256']
                snapshot='update-'+row['id'];dest=self.lib.root/'snapshots'/snapshot
                if dest.exists():
                    if self.c.read(dest/'manifest.json')['packages']!=selection:raise ValueError('후보 스냅샷 충돌')
                else:self.lib.snapshot(snapshot,selection,'업데이트 후보 · 기존 시스템 업그레이드·재부팅 검증 대기')
                self.lib.commit();row.update(status='testing',snapshot=snapshot,candidate_manifest_sha256=self.c.sha(dest/'manifest.json'),index_sha256=self.c.sha(dest/'repo/index.x86_64.json'))
                self.save(row)
            except Exception as error:row.update(status='build-failed',error=str(error));self.save(row)

    def request_validation(self,key):
        with self.lib.lock:
            row=self.get(key)
            if row['status'] not in {'testing','validation-failed','validated'}:raise ValueError('완료된 후보 빌드가 필요합니다.')
            row.update(status='testing',validation_nonce=uuid.uuid4().hex,validation_requested_at=self.c.now())
            policy=self.config().get('security',{}).get('scap')
            if policy:row['security_policy']=dict(policy)
            row.pop('validation',None);row.pop('error',None);self.save(row);return row

    def validate_report(self,key):
        row=self.get(key);nonce=row.get('validation_nonce','')
        if not nonce:raise ValueError('먼저 VM 검증을 요청하세요.')
        path=self.root/'evidence'/(nonce+'.json');signature=path.with_suffix('.sig')
        key_file=Path(__file__).with_name('update-verifier.pub')
        if not path.is_file() or not signature.is_file() or path.stat().st_size>2*1024*1024:raise ValueError('서명된 VM 검증 결과가 아직 도착하지 않았습니다.')
        try:subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(key_file),'-rawin','-in',str(path),'-sigfile',str(signature)],check=True,capture_output=True)
        except subprocess.CalledProcessError as error:raise ValueError('VM 검증 보고서 서명 오류') from error
        report=self.c.read(path)
        if report.get('error') or report.get('cleanup_error') or any(v is not True for v in report.get('checks',{}).values()):raise ValueError('VM 검증 보고서에 실패한 검사가 있습니다.')
        for k,expected in {'proposal':row['id'],'nonce':nonce,'plan_sha256':row['plan_sha256'],'base_manifest_sha256':row['base_manifest_sha256'],
                          'candidate_manifest_sha256':row['candidate_manifest_sha256'],'index_sha256':row['index_sha256']}.items():
            if report.get(k)!=expected:raise ValueError('VM 검증 결과가 다른 후보를 가리킵니다: '+k)
        profiles=self.config().get('vm_profiles',[])
        if not any(p.get('vm_id')==report.get('vm_id') and p.get('profile')==report.get('profile') for p in profiles):raise ValueError('등록된 검증 VM이 아닙니다.')
        required={'signature_verified','offline_apply_succeeded','package_inventory','user_config_preserved','services_healthy','rebooted','gnome_session','kernel_recovery'}
        if 'linux' in row['rebuild']:required.add('updated_kernel')
        if not required<=set(report.get('checks',{})) or not all(report['checks'][k] is True for k in required):raise ValueError('업그레이드·복구·재부팅·GUI 검증이 모두 통과해야 합니다.')
        if report.get('boot_id_before')==report.get('boot_id_after') or not report.get('boot_id_after'):raise ValueError('재부팅 검증 누락')
        baseline=self.c.read(self.lib.root/'snapshots'/row['base']/'manifest.json')['packages']
        before=report.get('base_packages',{})
        if not before or any(baseline.get(n)!=h for n,h in before.items()) or not set(row['rebuild'])<=set(before):raise ValueError('검증 VM이 기준 구성의 변경 패키지를 모두 포함해야 합니다.')
        candidate=self.c.read(self.lib.root/'snapshots'/row['snapshot']/'manifest.json')['packages']
        selected={n:self.lib.catalog['binaries'][h] for n,h in candidate.items()}
        required_names=set(before)|set(self.c.closure(selected,row['rebuild']))
        expected_packages={n:candidate[n] for n in required_names}
        if report.get('packages')!=expected_packages:raise ValueError('검증 VM의 설치 패키지 해시가 후보의 설치 프로파일 구성과 다릅니다.')
        if row.get('security_policy'):
            scans=report.get('security',{})
            for phase in ['before','after']:
                scan=scans.get(phase,{})
                if scan.get('policy_sha256')!=row['security_policy']['sha256'] or scan.get('status')!='completed' or not scan.get('rules'):raise ValueError('OpenSCAP 설정 검사 누락·정책 불일치')
                if scan.get('profile')!=row['security_policy']['profile']:raise ValueError('OpenSCAP 프로파일 불일치')
                expected_rules=row['security_policy'].get('rules',[])
                rules=scan['rules']
                if expected_rules and (len(rules)!=len(expected_rules) or {r['id'] for r in rules}!=set(expected_rules)):raise ValueError('OpenSCAP 필수 규칙 누락')
                if not any(r.get('result') in {'pass','fail'} for r in rules):raise ValueError('OpenSCAP 적용 가능한 검사 결과 없음')
            if report.get('checks',{}).get('security_scan_executed') is not True:raise ValueError('OpenSCAP 실행 증거 누락')
        return row,report,self.c.sha(path)

    def accept_validation(self,key):
        with self.lib.lock:
            if self.get(key)['status']=='stable':raise ValueError('이미 안정 채널에 배포한 후보입니다.')
            try:row,report,report_hash=self.validate_report(key)
            except ValueError as error:
                row=self.get(key)
                if row['status'] in {'testing','validation-failed'}:
                    row.update(status='validation-failed',error=str(error));self.save(row)
                raise
            row.update(status='validated',validation={'sha256':report_hash,'vm_id':report['vm_id'],'profile':report['profile'],'at':self.c.now(),'checks':report['checks'],'security':report.get('security',{})})
            self.save(row);return row

    def promote(self,job):
        with self.lib.lock:
            row=self.get(job['values']['proposal'])
            if row['status']!='validated':raise ValueError('서명된 VM 검증을 먼저 통과해야 합니다.')
            _,_,report_hash=self.validate_report(row['id'])
            if row['validation']['sha256']!=report_hash:raise ValueError('검증 결과 변경')
            stable=self.stable()
            if stable.get('version')!=row.get('stable_before'):raise ValueError('후보 생성 후 안정 채널이 변경됐습니다. 최신 기준으로 다시 검증하세요.')
            path=self.lib.root/'snapshots'/row['snapshot']
            if self.c.sha(path/'manifest.json')!=row['candidate_manifest_sha256'] or self.c.sha(path/'repo/index.x86_64.json')!=row['index_sha256']:raise ValueError('검증 이후 후보 변경')
            self.baseline(row['snapshot'])
            state={'version':row['snapshot'],'proposal':row['id'],'promoted_at':self.c.now(),'previous':stable.get('version'),'validation_sha256':report_hash}
            self.c.save(self.root/'stable-history'/(row['id']+'.json'),state)
            self.c.save(self.root/'stable.json',state)
            config=self.config();config['baseline']=row['snapshot'];self.c.save(self.root/'config.json',config)
            row.update(status='stable',promoted_at=state['promoted_at']);self.save(row)
            return {'proposal':row['id'],'snapshot':row['snapshot'],'channel':'stable','validation_sha256':report_hash}

    def tick(self):
        self.poll();config=self.config()
        if not config.get('enabled') or not config.get('baseline'):return
        request_file=self.root/'last-check-request.json'
        last=self.c.read(request_file)['at'] if request_file.exists() else self.checks().get('checked_at')
        due=not last or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(last)).total_seconds()>=max(3600,int(config.get('interval_seconds',21600)))
        if due and not any(j['kind']=='update-check' and j['status'] in {'pending','running'} for j in self.lib.jobs()):
            self.c.save(request_file,{'at':self.c.now()})
            self.lib.submit('update-check',{'base':config['baseline']})
        security=config.get('security',{})
        if security.get('enabled'):
            bases={config['baseline']}|{r['snapshot'] for r in self.list() if r.get('snapshot') and r['status'] in {'testing','validated'}}
            for base in sorted(bases):
                checked=self.security.result(base).get('checked_at')
                due=not checked or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(checked)).total_seconds()>=max(3600,int(security.get('interval_seconds',21600)))
                recent=self.root/'security'/('last-request-'+base+'.json')
                retry_due=not recent.exists() or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(self.c.read(recent)['at'])).total_seconds()>3600
                if due and retry_due and not any(j['kind']=='update-security' and j['values'].get('base')==base and j['status'] in {'pending','running'} for j in self.lib.jobs()):
                    self.lib.submit('update-security',{'base':base});self.c.save(recent,{'at':self.c.now()})

    def action(self,kind,values):
        if kind=='update-check':return self.check(values)
        if kind=='update-security':return self.security.scan(values)
        if kind=='update-prepare':return self.prepare(values)
        if kind=='update-promote':return self.promote(values)
        raise ValueError('알 수 없는 업데이트 작업')
