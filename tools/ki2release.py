#!/usr/bin/env python3
"""Immutable candidate library and serialized ISO jobs, separate from the compiler."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import html
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import tempfile
import tarfile
import time
import urllib.parse
import urllib.request
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ki2cpu import PROFILES as CPU_PROFILES, availability as cpu_availability, validate_selection as validate_cpu_selection
import ki2release_views as views
import ki2origins
from ki2updates import Updates
import ki2updates_views as update_views
from ki2releases import ReleaseManager
import ki2releases_views as release_views


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf-8') as stream:
            stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
            stream.flush();os.fsync(stream.fileno())
        temp.replace(path)
        if os.name=='posix':
            directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:temp.unlink(missing_ok=True)


def validate_catalog(value,root):
    if (not isinstance(value,dict) or value.get('schema')!='kiki-version-library-v1'
            or not isinstance(value.get('binaries'),dict) or not isinstance(value.get('sources'),dict)):
        raise ValueError('버전 목록 형식이 올바르지 않습니다.')
    for path in (Path(root)/'snapshots').glob('*/manifest.json'):
        if path.parent.name.startswith('.'):continue
        for name,key in read(path).get('packages',{}).items():
            if key not in value['binaries'] or value['binaries'][key]['name']!=name:
                raise ValueError('고정 스냅샷의 패키지가 버전 목록에 없습니다: '+name)
    return value


def load_catalog(root):
    root=Path(root);primary=root/'catalog.json';backup=root/'catalog.last-good.json'
    if not primary.exists() and not backup.exists():
        return {'schema':'kiki-version-library-v1','binaries':{},'sources':{}}
    try:return validate_catalog(read(primary),root)
    except (OSError,ValueError,TypeError,KeyError) as original:
        try:restored=validate_catalog(read(backup),root)
        except (OSError,ValueError,TypeError,KeyError):
            raise ValueError('버전 목록과 정상 백업을 읽지 못했습니다. 보관 파일은 유지했으며 복구가 필요합니다.') from original
        if primary.exists():shutil.copy2(primary,root/('catalog.invalid-'+uuid.uuid4().hex+'.json'))
        save(primary,restored)
        print('버전 목록을 정상 백업에서 복구했습니다. 손상 파일은 별도로 보존했습니다.',flush=True)
        return restored
def esc(value): return html.escape(str(value),quote=True)
def valid_id(value): return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',value))


def result_panel(kind,r):
    if kind=='iso':
        rows=[('OS 버전',r.get('release_version',r['snapshot'])),('패키지 스냅샷',r['snapshot']),('CPU 대상',CPU_PROFILES.get(r.get('cpu_profile','x86_64'),{'label':'미분류'})['label']),('ISO 파일',r['file']),('파일 크기',f"{r['bytes']:,}바이트"),
              ('SHA-256',r['sha256']),('내장 패키지',f"{r['media_packages']}개"),
              ('시스템 파일 검사',f"{r['root_regular_files_checked']:,}개"),
              ('BIOS 부팅 구조','통과' if r['bios_catalog'] else '실패'),
              ('UEFI 부팅 구조','통과' if r['uefi_catalog'] else '실패'),
              ('실제 설치','검증 완료' if r['fresh_install_tested'] else '미검증'),
              ('GDM/Wayland 로그인','검증 완료' if r['gdm_login_tested'] else '미검증'),
              ('Secure Boot 서명','서명됨' if r['secure_boot_signed'] else '미서명'),('검증 범위',r['validation'])]
    elif kind.startswith('update-'):rows=[(k,json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v) for k,v in r.items()]
    elif kind=='source':rows=[('소스 SHA-256',r['sha256']),('검증 범위',r['validation'])]
    elif kind=='snapshot':rows=[('보관 버전',r['snapshot_id']),('고정 패키지',f"{r['packages']}개"),('검증 범위',r['scope'])]
    elif kind=='release':rows=[('릴리즈',r['release_version']),('고정 스냅샷',r['snapshot']),('CPU 대상',CPU_PROFILES[r['cpu_profile']]['label']),('패키지',f"{r['packages']}개"),('변경한 패키지',f"{r['changed_packages']}개"),('검증 범위',r['validation'])]
    else:rows=[('SHA 검사','통과' if r['passed'] else '실패'),('검사 파일',f"{r['objects_checked']}개"),('바이너리',f"{r['binaries']}개"),('소스·관련 파일',f"{r['sources']}개")]
    return '<table>'+''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k,v in rows)+'</table><details><summary>원본 검증 명세</summary><pre>'+esc(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>'


def closure(binaries, roots):
    result,active=[],set()
    def visit(name):
        if name in result:return
        if name in active:raise ValueError('실행 의존성 순환: '+name)
        if name not in binaries:raise ValueError('실행 의존 패키지 없음: '+name)
        active.add(name)
        for dep in binaries[name]['dependencies'].get('runtime',[]):visit(dep)
        active.remove(name);result.append(name)
    for name in roots:visit(name)
    return result


def public_https(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in {None,443}:
        raise ValueError('공식 HTTPS 소스 주소만 허용합니다.')
    for entry in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(entry[4][0]).is_global:raise ValueError('내부 네트워크 소스 주소는 허용하지 않습니다.')
    return url


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_https(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Library:
    def __init__(self,root,backend,baseline,sources,native_packages,legacy_backend=None):
        self.root,self.backend,self.base,self.sources,self.native_packages=map(Path,[root,backend,baseline,sources,native_packages])
        self.legacy_backend=Path(legacy_backend) if legacy_backend else self.backend
        self.lock=threading.RLock();self.pending=queue.Queue();self.stop=threading.Event()
        for folder in ['objects','manifests','snapshots','jobs','private','tmp','release-versions','release-management']:(self.root/folder).mkdir(parents=True,exist_ok=True)
        self.catalog=load_catalog(self.root)
        self.catalog_generation=sha(self.root/'catalog.json') if (self.root/'catalog.json').exists() else None
        sys.path.insert(0,str(self.backend/'tools'))
        import ki2build,ki2repo
        self.build,self.repo=ki2build,ki2repo
        self.recipes={}
        if (self.backend/'distro/recipes').is_dir():
            for r in self.build.load_recipes(self.backend/'distro/recipes').values():
                self.recipes[(r.name,r.version)]=dict(r.source)
        spec=self.backend/'distro/specs/gnome-desktop-sources.toml'
        if spec.exists():
            for r in self.build.read_toml(spec).get('source',[]):
                self.recipes.setdefault((r['name'],str(r['version'])),{k:r[k] for k in ['url','sha256']})
        catalog=self.base/'recipes/catalog.json'
        if catalog.exists():
            for r in read(catalog)['recipes']:self.recipes[(r['name'],str(r['version']))]=r.get('source',{})
        for path in (self.base/'recipes').glob('*.toml'):
            for r in self.build.read_toml(path).get('recipe',[]):self.recipes[(r['name'],str(r['version']))]=r.get('source',{})
        self.releases=ReleaseManager(self,sys.modules[__name__])
        self.updates=Updates(self,sys.modules[__name__])

    def commit(self):
        with self.lock,(self.root/'catalog.commit.lock').open('a+b') as lease:
            if os.name=='posix':
                import fcntl
                fcntl.flock(lease.fileno(),fcntl.LOCK_EX)
            self._commit()

    def _commit(self):
        primary=self.root/'catalog.json';backup=self.root/'catalog.last-good.json'
        generation=sha(primary) if primary.exists() else None
        if generation!=self.catalog_generation:raise ValueError('버전 목록이 다른 프로세스에서 변경되었습니다. 작업자를 다시 시작한 뒤 재시도하세요.')
        value=validate_catalog(self.catalog,self.root)
        serialized=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        if primary.exists() and primary.read_bytes()==serialized and backup.exists():return
        save(backup,value);save(primary,value)
        self.catalog_generation=sha(primary)

    def blob(self,path,expected):
        if not re.fullmatch(r'[0-9a-f]{64}',expected) or sha(path)!=expected:raise ValueError('파일 SHA-256 불일치: '+Path(path).name)
        dest=self.root/'objects'/expected
        if dest.exists():
            if sha(dest)!=expected:raise ValueError('기존 보관 객체의 SHA가 변경됐습니다.')
            return dest
        temp=dest.with_name(expected+'.'+uuid.uuid4().hex+'.partial')
        shutil.copyfile(path,temp)
        if sha(temp)!=expected:raise ValueError('복사 후 SHA 불일치')
        try:os.link(temp,dest)
        except FileExistsError:
            if sha(dest)!=expected:raise ValueError('보관 객체 충돌')
        finally:temp.unlink(missing_ok=True)
        dest.chmod(0o444);return dest

    def add_binary(self,path,expected,scope,source=None,provenance=None):
        blob=self.blob(path,expected);m=self.repo.read_package_manifest(blob)
        info={k:m.get(k) for k in ['name','version','release','arch','summary','license','recipe_digest']}
        info.update(sha256=expected,file=Path(path).name,size=blob.stat().st_size,
                    dependencies=m.get('dependencies',{}),source=source or self.recipes.get((m['name'],str(m['version'])),{}),
                    validation=scope,provenance=provenance or {},registered_at=now())
        info.update(cpu_profile=m.get('cpu_profile','x86_64'),cpu_validation=m.get('cpu_validation','unclassified'))
        old=self.catalog['binaries'].get(expected)
        if old:return old
        self.catalog['binaries'][expected]=info
        manifest=self.root/'manifests'/(expected+'.json')
        if not manifest.exists():save(manifest,m)
        return info

    def synchronize(self):
        with self.lock:
            index=read(self.base/'validated-candidate/repo/index.x86_64.json')
            if not self.catalog['binaries']:
                for r in index['packages']:
                    self.add_binary(self.base/'validated-candidate/packages/x86_64'/r['file'],r['sha256'],'이전 후보 SHA 검증')
            for r in read(self.base/'source-lock.json')['sources']:
                p=self.sources/Path(r['file']).name
                if p.exists() and r['sha256'] not in self.catalog['sources']:
                    self.blob(p,r['sha256']);self.catalog['sources'][r['sha256']]={'sha256':r['sha256'],'file':p.name,'url':r.get('url',''),'size':p.stat().st_size,'verified_at':now()}
            baseline={r['name']:r['sha256'] for r in index['packages']}
            if not (self.root/'snapshots/baseline-6.1.187/manifest.json').exists():
                self.snapshot('baseline-6.1.187',baseline,'이전 검증 후보 · 새 서버 VM 재검증 전')
            mirror=self.sources/'mirror/index.json'
            if mirror.exists():
                expected={r.get('source',{}).get('sha256'):r['source'] for r in self.catalog['binaries'].values() if r.get('source',{}).get('sha256')}
                for r in read(mirror)['sources']:
                    key=r['sha256']
                    if key not in expected or key in self.catalog['sources']:continue
                    if r['file']!=key:raise ValueError('소스 미러 파일은 고정 SHA 이름이어야 합니다.')
                    path=mirror.parent/key;self.blob(path,key)
                    self.catalog['sources'][key]={'sha256':key,'file':Path(urllib.parse.urlsplit(expected[key]['url']).path).name,'url':expected[key]['url'],'size':path.stat().st_size,'verified_at':now()}
            self.sync_completed_jobs()
            gate=self.backend/'build/mesa-native-20261023/validation/rebuild-result.json'
            if gate.exists() and read(gate).get('passed'):
                current=read(gate);selection=dict(baseline)
                native_id='native-20261023-'+hashlib.sha256(json.dumps({n:r['sha256'] for n,r in current['packages'].items()},sort_keys=True).encode()).hexdigest()[:8]
                for name,r in current['packages'].items():
                    if not r.get('runtime_validated'):raise ValueError('네이티브 패키지 런타임 검증 대기')
                    path=self.native_packages/Path(r['file']).name
                    raw=self.build.read_toml(self.backend/'build/mesa-native-20261023/recipes'/(name+'.toml'))['recipe'][0]
                    if r['sha256'] not in self.catalog['binaries']:
                        self.add_binary(path,r['sha256'],'현 서버 SHA·ELF·렌더링 통과',raw['source'],r.get('provenance'))
                    selection[name]=r['sha256']
                existing=self.root/'snapshots'/native_id/'manifest.json'
                if existing.exists():
                    if read(existing)['packages']!=selection:raise ValueError('기존 네이티브 스냅샷의 SHA 선택이 다릅니다.')
                else:self.snapshot(native_id,selection,'현 서버 네이티브 검증 통과 · VM 설치·로그인 재검증 전')
            self.commit()

    def sync_completed_jobs(self):
        from ki2integrity import audit_payload
        imported=self.catalog.setdefault('imported_jobs',[])
        paths={p.resolve() for root in {self.backend,self.legacy_backend}
               for p in (root/'build/ki2ci/jobs').glob('*/metadata.json')}
        for metadata in sorted(paths):
            j=read(metadata)
            if j.get('update_plan'):continue  # Maintenance candidates require their own VM validation and promotion gate.
            if j.get('status')!='succeeded' or not j.get('package') or j['id'] in imported:continue
            git_source=j.get('source',{}) if j.get('source',{}).get('kind')=='git' else None
            if j.get('catalog'):
                if sha(metadata.parent/'catalog.json')!=j['catalog']['sha256']:raise ValueError('웹 카탈로그 고정 해시 불일치')
                recipe_path=metadata.parent/'source/distro/recipes/catalog.json'
                job_recipes={r['name']:self.build.normalize_recipe(r,recipe_path) for r in read(recipe_path)['recipes']}
            else:
                job_recipes=self.build.load_recipes(metadata.parent/'source/distro/recipes') if git_source else {}
            built={}
            for path in (metadata.parent/'packages').rglob('*.ki2'):
                digest=sha(path)
                if digest not in self.catalog['binaries']:
                    audit=audit_payload(path)
                    if audit['errors']:raise ValueError('완료 패키지 파일 명세 검사 실패: '+path.name)
                    source=None;provenance={'job_id':j['id'],'payload_audit':audit}
                    if git_source or j.get('catalog'):
                        manifest=self.repo.read_package_manifest(path)
                        recipe=job_recipes.get(manifest['name'])
                        if not recipe or recipe.digest!=manifest.get('recipe_digest'):
                            raise ValueError('Git 작업의 패키지 명세 지문이 산출물과 다릅니다: '+path.name)
                        source=dict(recipe.source)
                        if git_source:provenance['git']=git_source
                        if j.get('catalog'):provenance['web_catalog']=j['catalog']
                    self.add_binary(path,digest,'웹 빌드 SHA·파일 명세 통과 · 런타임 미검증',source=source,provenance=provenance)
                record=self.catalog['binaries'][digest]
                built[record['name']]=digest
            try:
                snapshot=self.auto_repository_snapshot(j,built)
                if snapshot:self.catalog.setdefault('repository_publications',{})[j['id']]={'status':'signed','snapshot':snapshot,'at':now()}
            except (ValueError,FileNotFoundError) as error:
                self.catalog.setdefault('repository_publications',{})[j['id']]={'status':'rejected','error':str(error),'at':now()}
            imported.append(j['id'])

    def auto_repository_snapshot(self,job,built):
        policy=self.root/'repository-auto-publish.json'
        if not policy.exists() or not read(policy).get('enabled') or not built:return
        config=read(policy);base=config.get('base','')
        if config.get('after'):
            if not job.get('finished_at'):return
            if dt.datetime.fromisoformat(job['finished_at'].replace('Z','+00:00')) < dt.datetime.fromisoformat(config['after'].replace('Z','+00:00')):return
        if not valid_id(base):raise ValueError('자동 배포 기준 스냅샷을 확인하세요.')
        selection=dict(read(self.root/'snapshots'/base/'manifest.json')['packages'])
        for package,digest in built.items():
            old_digest=selection.get(package)
            if old_digest and old_digest!=digest:
                old,new=self.catalog['binaries'][old_digest],self.catalog['binaries'][digest]
                if self.repo.latest_sort_key(new)<self.repo.latest_sort_key(old):raise ValueError('자동 배포 버전 하락 거부: '+package)
                if old['file']==new['file']:raise ValueError('동일 패키지 파일명 내용 변경: release 번호를 올려 다시 빌드하세요: '+package)
        selection.update(built)
        name='build-'+hashlib.sha256(str(job['id']).encode()).hexdigest()[:24]
        existing=self.root/'snapshots'/name/'manifest.json'
        if existing.exists():
            previous=read(existing)['packages']
            if any(previous.get(n)!=digest for n,digest in built.items()):raise ValueError('자동 배포 작업 산출물이 변경됐습니다.')
            if previous!=selection:return name  # A later committed job already advanced the base.
        else:
            self.snapshot(name,selection,'빌드 작업 '+str(job['id'])+' · SHA·파일 명세·의존성·후보 서명 통과 · 런타임·새 설치 미검증')
        # Recovery after snapshot commit reuses the immutable version before advancing the base.
        config.update(base=name,last_job=job['id'],updated_at=now())
        save(policy,config)
        return name

    def snapshot(self,name,selection,scope):
        if not valid_id(name):raise ValueError('버전 이름은 영문·숫자·점·밑줄·하이픈으로 64자까지 입력하세요.')
        binaries={n:self.catalog['binaries'][s] for n,s in selection.items()}
        if any(n!=r['name'] for n,r in binaries.items()):raise ValueError('패키지 이름과 버전 선택이 일치하지 않습니다.')
        closure(binaries,sorted(binaries))
        final=self.root/'snapshots'/name
        if final.exists():raise FileExistsError('같은 버전 이름은 덮어쓸 수 없습니다: '+name)
        # Persist all referenced objects before publishing an immutable snapshot.
        self.commit()
        directory=self.root/'snapshots'/('.pending-'+uuid.uuid4().hex);directory.mkdir(exist_ok=False)
        (directory/'packages').mkdir();(directory/'repo').mkdir()
        entries=[]
        for package,r in sorted(binaries.items()):
            path=self.root/'objects'/r['sha256']
            if sha(path)!=r['sha256']:raise ValueError('스냅샷 입력 SHA 불일치')
            dest=directory/'packages'/r['file'];os.link(path,dest)
            entries.append(self.repo.package_entry(dest,self.repo.read_package_manifest(dest)))
        self.repo.write_json(directory/'repo/index.x86_64.json',self.repo.build_index(entries,'x86_64',now()))
        metadata=self.repo.build_metadata(name='kiki-web-candidate',title='KIKI 웹 빌드 후보',description=scope,channel=name,arch='x86_64',base_url='',created_at=now(),repo_dir=directory/'repo',packages_dir=final/'packages',iso_dir=final/'iso',packages=entries)
        self.repo.write_json(directory/'repo/metadata.x86_64.json',metadata)
        key=self.root/'private/candidate.ed25519'
        if not key.exists():
            subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],check=True,capture_output=True);key.chmod(0o600)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(directory/'candidate.pub')],check=True,capture_output=True)
        self.repo.sign_metadata_file(directory/'repo/metadata.x86_64.json',key)
        if not self.repo.verify_metadata_file(directory/'repo/metadata.x86_64.json',directory/'candidate.pub'):raise ValueError('후보 메타데이터 서명 검사 실패')
        result={'id':name,'created_at':now(),'packages':selection,'source_pins':{n:{'sha256':r.get('source',{}).get('sha256'),'url':r.get('source',{}).get('url'),'version':r['version']} for n,r in binaries.items()},'validation_scope':scope,'kernel':'6.1.187','release_ready':False,'fresh_install_tested':False,'signing_scope':'후보 전용 Ed25519 키 · 공식 릴리스 아님','index_sha256':sha(directory/'repo/index.x86_64.json'),'metadata_sha256':sha(directory/'repo/metadata.x86_64.json')}
        save(directory/'manifest.json',result);directory.rename(final);return result

    def snapshots(self):return [read(p) for p in sorted((self.root/'snapshots').glob('*/manifest.json')) if not p.parent.name.startswith('.')]
    def jobs(self):return sorted([read(p) for p in (self.root/'jobs').glob('*/job.json')],key=lambda r:r['created_at'],reverse=True)
    def job(self,job_id):
        if not re.fullmatch('[0-9a-f]{32}',job_id):raise ValueError('올바르지 않은 작업 ID')
        return read(self.root/'jobs'/job_id/'job.json')
    def update(self,j,**values):j.update(values);save(self.root/'jobs'/j['id']/'job.json',j)

    def release_versions(self):
        return [read(p) for p in sorted((self.root/'release-versions').glob('*/manifest.json'))]

    def cpu_targets(self,snapshot):
        manifest=read(self.root/'snapshots'/snapshot/'manifest.json')
        return cpu_availability(self.catalog['binaries'][key] for key in manifest['packages'].values())

    def submit(self,kind,values):
        with self.lock:return self._submit(kind,dict(values))

    def _submit(self,kind,values):
        if kind=='iso' and shutil.disk_usage(self.root).free<4*1024**3:raise ValueError('ISO 생성에는 최소 4GiB 여유 공간이 필요합니다.')
        if sum(j['status'] in {'pending','running'} for j in self.jobs())>=8:raise ValueError('대기 작업이 많습니다. 기존 작업 완료 후 요청하세요.')
        if kind in {'update-check','update-security','update-prepare','update-promote'}:
            if kind in {'update-check','update-security'}:self.updates.baseline(values.get('base') or self.updates.config().get('baseline',''))
            else:
                row=self.updates.get(values.get('proposal',''))
                if kind=='update-prepare' and row['status'] not in {'proposed','prepare-failed','build-failed'}:raise ValueError('이미 준비·제출된 후보입니다.')
                if kind=='update-promote' and row['status']!='validated':raise ValueError('서명된 VM 검증을 먼저 통과해야 합니다.')
            if any(j['kind']==kind and j['values']==values and j['status'] in {'pending','running'} for j in self.jobs()):raise ValueError('이미 같은 요청이 대기 중입니다.')
            j={'id':uuid.uuid4().hex,'kind':kind,'status':'pending','phase':'대기','created_at':now(),'values':values,'result':None}
            self.update(j);(self.root/'jobs'/j['id']/'log.txt').write_text('',encoding='utf-8');self.pending.put(j['id']);return j
        if kind=='release':values=self.releases.validate_registration(values)
        elif kind=='iso':
            snapshot=values.get('snapshot','');profile=values.get('profile','')
            if not valid_id(snapshot) or not (self.root/'snapshots'/snapshot/'manifest.json').exists():raise ValueError('검증된 스냅샷을 선택하세요.')
            if profile not in {'gnome50','minimal-systemd'}:raise ValueError('지원되지 않는 ISO 구성')
            values['release_version']=values.get('release_version') or snapshot
            values['cpu_profile']=values.get('cpu_profile') or 'x86_64'
            values['vm_group']=values.get('vm_group') or ''
            if values['vm_group'] not in {'','vm-kvm','vm-hyperv'}:raise ValueError('지원되지 않는 VM 그룹')
            if not valid_id(values['release_version']):raise ValueError('OS 버전은 영문·숫자·점·밑줄·하이픈으로 64자까지 입력하세요.')
            self.releases.iso_allowed(values['release_version'],values['cpu_profile'],snapshot)
            manifest=read(self.root/'snapshots'/snapshot/'manifest.json')
            validate_cpu_selection(values['cpu_profile'],[self.catalog['binaries'][key] for key in manifest['packages'].values()])
            version_path=self.root/'release-versions'/values['release_version']/'manifest.json'
            version=read(version_path) if version_path.exists() else {'schema':'kiki-os-version-v2','version':values['release_version'],'targets':{},'created_at':now()}
            pins=views.version_targets(version) if version_path.exists() else version['targets']
            pin=pins.get(values['cpu_profile'])
            if pin and (pin['snapshot']!=snapshot or pin['snapshot_manifest_sha256']!=sha(self.root/'snapshots'/snapshot/'manifest.json')):
                raise ValueError('같은 OS 버전·CPU 대상의 패키지 스냅샷은 변경할 수 없습니다. 새 OS 버전을 입력하세요.')
        elif kind=='snapshot':
            version,base=values.get('version',''),values.get('base','')
            if not valid_id(version) or not valid_id(base) or not (self.root/'snapshots'/base/'manifest.json').exists():raise ValueError('기준 버전과 새 버전 이름을 확인하세요.')
            if (self.root/'snapshots'/version).exists():raise ValueError('같은 버전은 덮어쓸 수 없습니다.')
        elif kind=='sync':pass
        elif kind=='source':
            binary=self.catalog['binaries'].get(values.get('binary',''))
            if not binary or not re.fullmatch('[0-9a-f]{64}',binary.get('source',{}).get('sha256','')):raise ValueError('공식 URL과 고정 SHA가 있는 소스만 내려받을 수 있습니다.')
        else:raise ValueError('지원되지 않는 작업')
        if kind=='iso' and not pin:
            pins[values['cpu_profile']]={'snapshot':snapshot,'snapshot_manifest_sha256':sha(self.root/'snapshots'/snapshot/'manifest.json')}
            version.update(schema='kiki-os-version-v2',targets=pins)
            save(version_path,version)
        j={'id':uuid.uuid4().hex,'kind':kind,'status':'pending','phase':'대기','created_at':now(),'values':values,'result':None}
        self.update(j);(self.root/'jobs'/j['id']/'log.txt').write_text('',encoding='utf-8');self.pending.put(j['id']);return j

    def run(self,command,job,cwd=None):
        path=self.root/'jobs'/job['id']/'log.txt'
        with path.open('a',encoding='utf-8') as f:
            f.write('$ '+' '.join(map(str,command))+'\n');f.flush()
            subprocess.run(list(map(str,command)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)

    def source_job(self,j):
        r=self.catalog['binaries'][j['values']['binary']];source=r['source'];expected=source['sha256']
        if expected not in self.catalog['sources']:
            if shutil.disk_usage(self.root).free<5*1024**3:raise ValueError('소스 확보 전 빌드 볼륨에 5GiB 이상 여유 공간이 필요합니다.')
            url=public_https(source['url']);opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),HTTPSRedirect())
            temp=self.root/'jobs'/j['id']/'source.partial'
            with opener.open(url,timeout=60) as response,temp.open('xb') as out:
                count=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    count+=len(chunk)
                    if count>4*1024**3:raise ValueError('소스 크기 제한 4GiB 초과')
                    out.write(chunk)
            self.blob(temp,expected)
            with self.lock:
                self.catalog['sources'][expected]={'sha256':expected,'file':Path(urllib.parse.urlsplit(url).path).name,'url':url,'size':temp.stat().st_size,'verified_at':now()};self.commit()
            temp.unlink()
        return {'sha256':expected,'validation':'소스 SHA 통과 · 서명 검증은 별도 상태'}

    def iso_inputs(self,profile,binaries,catalog=None):
        native='kiki-desktop-defaults' in binaries
        backend=self.backend if native else self.legacy_backend
        if profile=='gnome50':
            if native:
                import ki2installcatalog
                return backend,'desktop-gnome',ki2installcatalog.expand(catalog or ki2installcatalog.load(),['desktop-gnome'])['packages']
            return backend,profile,read(self.base/'validation/desktop-root-plan.json')['order']
        if profile!='minimal-systemd':raise ValueError('지원되지 않는 ISO 구성')
        return backend,profile,['base-files','linux','systemd','dbus','bash','coreutils','util-linux','busybox','shadow','openssh','kiki-netconfig']

    def iso_job(self,j):
        values=j['values'];snap=self.root/'snapshots'/values['snapshot'];manifest=read(snap/'manifest.json')
        self.releases.iso_allowed(values.get('release_version',values['snapshot']),values.get('cpu_profile','x86_64'),values['snapshot'])
        binaries={n:self.catalog['binaries'][s] for n,s in manifest['packages'].items()}
        cpu=validate_cpu_selection(values.get('cpu_profile','x86_64'),list(binaries.values()))
        release_version=values.get('release_version',values['snapshot'])
        pinned=self.root/'release-versions'/release_version/'manifest.json'
        if pinned.exists():
            pin=views.version_targets(read(pinned)).get(cpu['id'])
            if not pin or pin['snapshot']!=values['snapshot'] or pin['snapshot_manifest_sha256']!=sha(snap/'manifest.json'):
                raise ValueError('OS 버전의 고정 스냅샷이 변경됐습니다.')
        if shutil.disk_usage(self.root).free<max(4*1024**3,sum(r['size'] for r in binaries.values())*5+2*1024**3):raise ValueError('ISO 작업에 필요한 여유 공간이 부족합니다. 기존 버전은 삭제하지 않았습니다.')
        for r in binaries.values():
            if sha(snap/'packages'/r['file'])!=r['sha256']:raise ValueError('ISO 입력 패키지 SHA 불일치')
        if sha(snap/'repo/index.x86_64.json')!=manifest['index_sha256'] or sha(snap/'repo/metadata.x86_64.json')!=manifest['metadata_sha256']:raise ValueError('고정된 저장소 메타데이터 변경')
        if not self.repo.verify_metadata_file(snap/'repo/metadata.x86_64.json',snap/'candidate.pub'):raise ValueError('저장소 서명 검사 실패')
        dest=self.root/'jobs'/j['id']
        catalog=None;catalog_args=[]
        if 'ki2ctl' in binaries:
            import ki2installcatalog
            with tarfile.open(snap/'packages'/binaries['ki2ctl']['file']) as archive:
                member=archive.getmember('rootfs/usr/share/ki2/package-groups.json')
                if not member.isfile() or member.size>1024*1024:raise ValueError('패키지 그룹 카탈로그 형식·크기 오류')
                raw=archive.extractfile(member).read()
            path=dest/'package-groups.json';path.write_bytes(raw)
            catalog=ki2installcatalog.load(path)
            for group in catalog['groups']:ki2installcatalog.expand(catalog,[group['id']])
            with tarfile.open(snap/'packages'/binaries['kiki-installer-gtk']['file']) as archive:
                runtime=json.load(archive.extractfile('rootfs/usr/share/kiki-installer-gtk/runtime-manifest.json'))
            if runtime.get('catalog_sha256')!=sha(path):raise ValueError('GTK 설치기와 ki2ctl의 그룹 구성이 다릅니다. 설치기를 같은 편집본으로 재빌드하세요.')
            catalog_args=['--catalog-file',path,'--catalog-sha256',sha(path)]
        backend,installer_profile,roots=self.iso_inputs(values['profile'],binaries,catalog)
        if values.get('vm_group'):
            if not catalog:raise ValueError('VM 그룹에는 설치 카탈로그가 필요합니다.')
            roots=list(dict.fromkeys(roots+ki2installcatalog.expand(catalog,[values['vm_group']])['packages']))
        order=closure(binaries,roots)
        if values.get('runtime_patch_from'):
            import ki2cloudruntime
            return ki2cloudruntime.refresh(self,j,manifest,binaries,cpu)
        root=dest/'rootfs';root.mkdir(exist_ok=False)
        self.update(j,phase='패키지 SHA·의존성 확인 후 시스템 파일 트리 구성')
        installed=[]
        for position,name in enumerate(order,1):
            self.update(j,phase=f'시스템 파일 구성 {position}/{len(order)} · {name}')
            with (dest/'log.txt').open('a',encoding='utf-8') as log:log.write(f'Extract [{position}/{len(order)}] {name}\n')
            path=snap/'packages'/binaries[name]['file'];self.build.extract_package_rootfs(path,root);installed.append((path,self.repo.read_package_manifest(path)))
        checked=0
        self.update(j,phase='구성한 시스템 파일의 SHA-256 검사')
        for _,m in installed:
            for entry in m.get('files',[]):
                if entry['type']=='file':
                    path=root/entry['path'].lstrip('/')
                    if not path.is_file() or sha(path)!=entry['sha256']:raise ValueError('시스템 파일 SHA 불일치: '+entry['path'])
                    checked+=1
                    if checked%1000==0:self.update(j,phase=f'시스템 파일 SHA-256 검사 · {checked:,}개 확인')
        self.build.write_rootfs_installed_state(root,installed)
        save(root/'etc/kiki/build-target.json',{'schema':'kiki-build-target-v1','os_version':release_version,
            'snapshot':values['snapshot'],'cpu_profile':cpu['id'],'cpu_level':cpu['level'],
            'cpu_validation':'unclassified' if cpu['id']=='x86_64' else 'runtime-verified'})
        self.run(['chroot',root,'/sbin/ldconfig'],j)
        self.update(j,phase='설치 ISO 생성 · 설치기 프런트엔드는 기존 KI2 그대로 사용')
        output=dest/('kiki-'+release_version+'-'+values['profile']+'-'+cpu['id']+'-'+j['id'][:8]+'.iso')
        installer=binaries['kiki-installer-gtk']
        kernel=binaries['linux']
        self.run([sys.executable,Path(__file__).with_name('ki2iso_preserved.py'),'--expected-installer-file',installer['file'],'--expected-installer-sha256',installer['sha256'],'--expected-kernel-file',kernel['file'],'--expected-kernel-sha256',kernel['sha256'],'--repo-root',backend,*catalog_args,'--profile',installer_profile,'--release-name',release_version,'--rootfs-dir',root,'--repo-dir',snap/'repo','--packages-dir',snap/'packages','--mode','installer','--media-public-key',snap/'candidate.pub','--no-install-image','--no-hyperv-vhdx','--output',output],j)
        self.update(j,phase='ISO SHA·부팅 카탈로그·내장 패키지 목록 확인')
        check=subprocess.run(['xorriso','-indev',str(output),'-report_el_torito','plain'],capture_output=True,text=True,check=True)
        save(dest/'boot-catalog.json',{'stdout':check.stdout,'stderr':check.stderr})
        boot_report=check.stdout+check.stderr
        if 'BIOS' not in boot_report or 'UEFI' not in boot_report:raise ValueError('BIOS·UEFI 부팅 항목이 모두 있어야 합니다.')
        extracted=dest/'iso-manifest.json';self.run(['xorriso','-osirrox','on','-indev',output,'-extract','/manifest.json',extracted],j)
        media=read(extracted)
        if media['package_media']['copied']!=len(binaries) or media['package_media']['missing']:raise ValueError('ISO 내 패키지 보관 수 불일치')
        result={'file':output.name,'sha256':sha(output),'bytes':output.stat().st_size,'snapshot':manifest['id'],'profile':values['profile'],'root_packages':len(order),'root_regular_files_checked':checked,'media_packages':len(binaries),'preserved_installer_sha256':installer['sha256'],'bios_catalog':True,'uefi_catalog':True,'fresh_install_tested':False,'gdm_login_tested':False,'secure_boot_signed':False,'validation':'SHA·저장소 서명·의존성·ISO 부팅 구조 검사 통과'}
        result.update(release_version=release_version,cpu_profile=cpu['id'],cpu_validation='unclassified' if cpu['id']=='x86_64' else 'runtime-verified',snapshot_manifest_sha256=sha(snap/'manifest.json'))
        if catalog:result.update(catalog_sha256=sha(dest/'package-groups.json'),catalog_groups=len(catalog['groups']))
        network_helper=Path(__file__).with_name('ki2network.py')
        if network_helper.is_file():result['installer_network_helper_sha256']=sha(network_helper)
        import ki2cloudseed
        cloud_public=ki2cloudseed.public_key_path()
        if cloud_public.is_file():
            result.update(cloud_install_supported=True,cloud_install_public_key_sha256=sha(cloud_public),cloud_install_helper_sha256=sha(Path(__file__).with_name('ki2cloudseed.py')))
        save(dest/'result.json',result);(dest/(output.name+'.sha256')).write_text(result['sha256']+'  '+output.name+'\n')
        return result

    def start(self):
        self.synchronize()
        for j in reversed(self.jobs()):
            if j['status']=='running':self.update(j,status='interrupted',phase='서비스 재시작으로 중단됨',finished_at=now())
            elif j['status']=='pending':self.pending.put(j['id'])
        def worker():
            while not self.stop.is_set():
                try:job_id=self.pending.get(timeout=10)
                except queue.Empty:
                    try:self.synchronize()
                    except Exception as e:save(self.root/'synchronization-error.json',{'at':now(),'error':str(e)})
                    try:self.updates.tick()
                    except Exception as e:save(self.root/'updates/error.json',{'at':now(),'error':str(e)})
                    continue
                j=self.job(job_id)
                try:
                    self.update(j,status='running',phase='입력 검증',started_at=now())
                    if j['kind'].startswith('update-'):result=self.updates.action(j['kind'],j)
                    elif j['kind']=='iso':result=self.iso_job(j)
                    elif j['kind']=='release':result=self.releases.register_job(j)
                    elif j['kind']=='source':result=self.source_job(j)
                    elif j['kind']=='snapshot':
                        parent=read(self.root/'snapshots'/j['values']['base']/'manifest.json')
                        self.update(j,phase='패키지 SHA 확인·새 버전 서명 중')
                        with self.lock:r=self.snapshot(j['values']['version'],parent['packages'],parent['validation_scope'])
                        result={'snapshot_id':r['id'],'packages':len(r['packages']),'scope':r['validation_scope']}
                    else:
                        self.update(j,phase='완료 패키지·소스 동기화 및 보관 파일 SHA 재검증')
                        self.synchronize()
                        records=list(self.catalog['binaries'].values())+list(self.catalog['sources'].values())
                        for r in records:
                            if sha(self.root/'objects'/r['sha256'])!=r['sha256']:raise ValueError('보관 파일 SHA 불일치: '+r['file'])
                        result={'passed':True,'objects_checked':len(records),'binaries':len(self.catalog['binaries']),'sources':len(self.catalog['sources'])}
                    self.update(j,status='succeeded',phase='완료',result=result,finished_at=now())
                except Exception as e:self.update(j,status='failed',phase='실패',error=str(e),finished_at=now())
                finally:self.pending.task_done()
        threading.Thread(target=worker,daemon=True).start()
        import ki2clouddeploy
        ki2clouddeploy.start(self)


def render(title,body,refresh=False):
    nav=[('/','운영 현황'),('/jobs','빌드 작업'),('/packages','패키지'),('/package-build','개별 패키지 빌드'),('/profiles','구성 프로필'),('/artifacts','산출물'),('/security','검증 현황'),('/deploy','서버 구성'),('/updates','업데이트 관리'),('/releases','릴리즈 관리'),('/versions','소스·바이너리 버전'),('/iso-build','버전별 ISO'),('/cpu-profiles','CPU 대상 관리')]
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><script src='/build-console.js' defer></script>"+('<meta http-equiv="refresh" content="5">' if refresh else '')+f'<title>{esc(title)} · KIKI OS</title>'+'''<style>
body{margin:0;background:#f4f6f8;color:#20242c;font:14px system-ui}header{background:#20242c;color:white;padding:20px 26px}h1{font-size:22px;margin:0}nav{display:flex;flex-wrap:wrap;background:#2a303a;padding:0 18px}nav a{color:#e3e9f2;text-decoration:none;padding:12px}main{max-width:1300px;margin:auto;padding:24px}.panel{background:white;border:1px solid #d9dee7;border-radius:8px;padding:20px;margin-bottom:18px;overflow:auto}h2{font-size:18px;margin:0 0 14px}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #e0e5ed;vertical-align:top}th{font-size:12px;color:#526071;background:#f8f9fb}a{color:#1f5fbf}button{border:0;background:#1f5fbf;color:white;padding:9px 14px;border-radius:5px;cursor:pointer}input,select{padding:9px;border:1px solid #bcc5d0;border-radius:5px;font:inherit;max-width:100%}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;width:100%}.fields label{display:grid;gap:8px}.wide{grid-column:1/-1;width:100%}.tabs{display:flex;gap:18px;flex-wrap:wrap}.tabs [aria-current=page]{font-weight:700;border-bottom:2px solid #1f5fbf}textarea{font:inherit;padding:9px;border:1px solid #bcc5d0;border-radius:5px;max-width:100%;box-sizing:border-box}form.fields{display:grid}form{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0}label{font-weight:650}small,.muted{color:#667085}code{overflow-wrap:anywhere}pre{background:#141922;color:#e3ebf7;padding:16px;max-height:420px;overflow:auto;white-space:pre-wrap}.good{color:#16703a}.bad{color:#b42318}.tag{padding:3px 8px;background:#edf1f6;border-radius:4px;display:inline-block}.notice{background:#eef3fa;padding:14px;border-left:3px solid #1f5fbf;line-height:1.6}@media(max-width:700px){main{padding:12px}.panel{padding:14px}nav a{padding:10px 8px}}
</style></head><body><header>'''+f'<h1>{esc(title)}</h1></header><nav>'+''.join(f"<a href='{path}'>{label}</a>" for path,label in nav)+f'</nav><main>{body}</main></body></html>').encode('utf-8')


def make_handler(lib):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body=b'',kind='text/html; charset=utf-8',headers=()):
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            for k,v in headers:self.send_header(k,v)
            self.end_headers();self.wfile.write(body)
        def redirect(self,path):self.reply(303,headers=[('Location',path)])
        def allowed(self):
            if self.headers.get('Host') not in {'127.0.0.1:18090','localhost:18090','127.0.0.1:18091'}:
                self.reply(403,b'Gateway required');return False
            return True
        def download(self,path,name):
            name=re.sub('[^A-Za-z0-9._+-]','_',name)
            self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Disposition',f'attachment; filename="{name}"');self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
            with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
        def do_GET(self):
            if not self.allowed():return
            p=urllib.parse.urlsplit(self.path);query=urllib.parse.parse_qs(p.query)
            try:
                if p.path=='/updates':self.reply(200,update_views.index(lib.updates,render,query));return
                if p.path=='/updates/new':self.reply(200,update_views.new(lib.updates,render,query));return
                if p.path=='/updates/security':self.reply(200,update_views.security(lib.updates,render,query));return
                if p.path=='/updates/security/sbom':
                    base=query.get('base',[lib.updates.config().get('baseline','')])[0]
                    self.reply(200,json.dumps(lib.updates.security.sbom(base),ensure_ascii=False).encode(),'application/json');return
                if p.path=='/api/updates/security':
                    self.reply(200,json.dumps(lib.updates.security.result(query.get('base',[None])[0]),ensure_ascii=False).encode(),'application/json');return
                if p.path=='/api/updates':self.reply(200,json.dumps({'checks':lib.updates.checks(),'proposals':lib.updates.list(),'stable':lib.updates.stable()},ensure_ascii=False).encode(),'application/json');return
                m=re.fullmatch(r'/updates/([a-f0-9]{32})(/manifest|/security-report)?',p.path)
                if m:
                    row=lib.updates.get(m[1])
                    if m[2]:self.reply(200,json.dumps(row.get('validation',{}).get('security',{}) if m[2]=='/security-report' else row,ensure_ascii=False,indent=2).encode(),'application/json')
                    else:self.reply(200,update_views.detail(lib.updates,render,m[1]))
                    return
                if p.path in ['/artifacts','/api/artifacts']:
                    import ki2artifacts
                    if p.path=='/artifacts':self.reply(200,ki2artifacts.page(lib,render,query))
                    else:self.reply(200,json.dumps(ki2artifacts.inventory(lib),ensure_ascii=False).encode(),'application/json')
                    return
                if p.path=='/versions':self.reply(200,self.versions(query));return
                if p.path=='/iso-build':self.reply(200,views.iso_page(lib,render,query));return
                if p.path=='/cpu-profiles':self.reply(200,views.cpu_page(lib,render));return
                if p.path=='/releases':self.reply(200,release_views.index(lib.releases,render,query));return
                if p.path=='/releases/new':self.reply(200,release_views.new(lib.releases,render,query));return
                m=re.fullmatch(r'/releases/([A-Za-z0-9][A-Za-z0-9._-]{0,63})(/manifest)?',p.path)
                if m:
                    if m[2]:self.reply(200,json.dumps(lib.releases.manifest(m[1]),ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8',[('Content-Disposition','attachment; filename="'+m[1]+'-release.json"')])
                    else:self.reply(200,release_views.detail(lib.releases,render,m[1],query))
                    return
                if p.path=='/api/releases/summary':
                    jobs=lib.jobs();value=dict(schema='kiki-release-summary-v1',binaries=len(lib.catalog['binaries']),sources=len(lib.catalog['sources']),snapshots=len(lib.snapshots()),isos=sum(j['kind']=='iso' and j['status']=='succeeded' for j in jobs),active=sum(j['status'] in ['pending','running'] for j in jobs))
                    self.reply(200,json.dumps(value).encode(),'application/json');return
                if p.path=='/api/releases':self.reply(200,json.dumps({'snapshots':lib.snapshots(),'release_versions':lib.release_versions(),'managed_releases':lib.releases.list(),'cpu_profiles':list(CPU_PROFILES.values()),'jobs':lib.jobs(),'binaries':list(lib.catalog['binaries'].values()),'sources':list(lib.catalog['sources'].values())},ensure_ascii=False).encode(),'application/json');return
                m=re.fullmatch(r'/library/snapshots/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/(manifest|index|metadata|public-key)',p.path)
                if m:
                    mapping={'manifest':'manifest.json','index':'repo/index.x86_64.json','metadata':'repo/metadata.x86_64.json','public-key':'candidate.pub'}
                    path=lib.root/'snapshots'/m[1]/mapping[m[2]];self.download(path,m[1]+'-'+path.name);return
                m=re.fullmatch(r'/library/files/(binary|source|manifest)/([0-9a-f]{64})',p.path)
                if m:
                    kind,key=m.groups();record=lib.catalog['binaries' if kind in {'binary','manifest'} else 'sources'][key]
                    path=lib.root/'manifests'/(key+'.json') if kind=='manifest' else lib.root/'objects'/key
                    self.download(path,(record['file']+'.manifest.json') if kind=='manifest' else record['file']);return
                m=re.fullmatch(r'/iso-build/jobs/([0-9a-f]{32})(?:/(file|sha256|report|cloud-report))?',p.path)
                if m:
                    job=lib.job(m[1]);directory=lib.root/'jobs'/job['id']
                    if m[2]:
                        if job['status']!='succeeded':raise ValueError('완료된 산출물만 다운로드할 수 있습니다.')
                        result=job['result'];name='cloud-deploy.json' if m[2]=='cloud-report' else 'result.json' if m[2]=='report' else result['file']+('.sha256' if m[2]=='sha256' else '')
                        self.download(directory/name,name);return
                    self.reply(200,self.job_page(job));return
                raise FileNotFoundError()
            except (ValueError,KeyError,FileNotFoundError) as e:self.reply(400,render('요청 확인 필요',f'<div class="panel"><p>{esc(e)}</p><a href="/versions">버전 목록</a></div>'))
        def do_POST(self):
            if not self.allowed():return
            try:
                if urllib.parse.urlsplit(self.headers.get('Origin','')).netloc!=self.headers.get('Host'):raise ValueError('요청 출처 불일치')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=(131072 if self.path.startswith('/releases/') else 32768):raise ValueError('올바르지 않은 요청 크기')
                data={k:v[0] for k,v in urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'),max_num_fields=16).items()}
                if self.path=='/updates/check':
                    lib.submit('update-check',{'base':lib.updates.config().get('baseline','')});self.redirect('/updates');return
                if self.path=='/updates/security/check':
                    lib.submit('update-security',{'base':data.get('base') or lib.updates.config().get('baseline','')});self.redirect('/updates/security');return
                if self.path=='/updates/security/acknowledge':
                    lib.updates.security.acknowledge(data.get('base') or lib.updates.config().get('baseline',''));self.redirect('/updates/security');return
                if self.path=='/updates/acknowledge':lib.updates.acknowledge();self.redirect('/updates');return
                if self.path=='/updates/create':
                    row=lib.updates.create(data);self.redirect('/updates/'+row['id']);return
                m=re.fullmatch(r'/updates/([a-f0-9]{32})/(build|validate|accept-validation|promote)',self.path)
                if m:
                    key,action=m.groups()
                    if action=='validate':lib.updates.request_validation(key)
                    elif action=='accept-validation':lib.updates.accept_validation(key)
                    else:lib.submit('update-prepare' if action=='build' else 'update-promote',{'proposal':key})
                    self.redirect('/updates/'+key);return
                if self.path=='/releases/register':
                    j=lib.submit('release',{k:data.get(k,'') for k in ['release_version','base','cpu_profile','profile','title','notes','changes']});self.redirect('/iso-build/jobs/'+j['id']);return
                m=re.fullmatch(r'/releases/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/manage',self.path)
                if m:
                    lib.releases.manage(m[1],data.get('action',''),data.get('revision',''),data.get('title',''),data.get('notes',''))
                    self.redirect('/releases/'+m[1]+'?tab=settings');return
                if self.path=='/library/snapshot':
                    j=lib.submit('snapshot',{k:data.get(k,'') for k in ['base','version']});self.redirect('/iso-build/jobs/'+j['id']);return
                if self.path=='/library/sync':
                    j=lib.submit('sync',{});self.redirect('/iso-build/jobs/'+j['id']);return
                kind='iso' if self.path=='/iso-build' else 'source' if self.path=='/library/source' else None
                j=lib.submit(kind,{k:v for k,v in data.items() if k in {'snapshot','profile','binary','release_version','cpu_profile','vm_group','runtime_patch_from'}});self.redirect('/iso-build/jobs/'+j['id'])
            except (ValueError,KeyError,StopIteration,FileExistsError) as e:self.reply(400,render('요청 확인 필요',f'<div class="panel"><p>{esc(e)}</p><a href="/versions">버전 목록</a></div>'))
        def versions(self,q):
            search=q.get('q',[''])[0].lower();rows=[]
            records=list(lib.catalog['binaries'].values());sources=dict(lib.catalog['sources'])
            try:origin_audits=ki2origins.load_audit(Path(__file__).with_name('source-origins.json'))
            except (OSError,ValueError,TypeError,AttributeError):origin_audits={}
            for r in sorted(records,key=lambda r:(r['name'],r['version'],r['release'])):
                if search and search not in (r['name']+' '+r['version']+' '+r['release']).lower():continue
                origin=ki2origins.source_origin(ki2origins.audited_record(r,r,origin_audits))
                source=dict(r.get('source',{}),url=origin['url']);key=origin['sha256']
                source_link=ki2origins.links(origin,f'/library/files/source/{key}' if key in sources else '')
                if key not in sources and ki2origins.public_url(r.get('source',{}).get('url')) and origin['sha256']:
                    source_link+=f"<form method='post' action='/library/source'><input type='hidden' name='binary' value='{r['sha256']}'><button>소스 확보·SHA 검사</button></form>"
                rows.append(f"<tr><td><b>{esc(r['name'])}</b><br>{esc(r['version'])}-{esc(r['release'])}<br><small>{esc(r['arch'])}</small></td><td>{esc(r['validation'])}<br><details><summary>SHA·의존성·출처</summary><p>바이너리 SHA-256<br><code>{r['sha256']}</code></p><p>소스 SHA-256<br><code>{esc(key or '미등록')}</code></p><p>{esc(source.get('url','로컬 소스'))}</p><p>실행 의존성: {esc(', '.join(r['dependencies'].get('runtime',[])))}</p></details></td><td>{source_link}</td><td><a href='/library/files/binary/{r['sha256']}'>KI2 다운로드</a><br><a href='/library/files/manifest/{r['sha256']}'>파일 명세</a><br><small>{r['size']:,}바이트</small></td></tr>")
            snaps=lib.snapshots();options=''.join(f"<option value='{esc(s['id'])}'>{esc(s['id'])}</option>" for s in snaps)
            body=f"<div class='panel'><h2>고정된 버전 스냅샷</h2><p class='notice'>소스와 바이너리는 SHA-256별로 보존합니다. 스냅샷은 패키지 버전·저장소 인덱스·후보 서명을 고정하며, 같은 이름을 덮어쓰지 않습니다. 새 네이티브 검증 결과는 자동으로 별도 버전으로 등록됩니다.</p><table><tr><th>버전</th><th>패키지</th><th>검증 범위</th></tr>"+''.join(f"<tr><td>{esc(s['id'])}<br><a href='/library/snapshots/{esc(s['id'])}/manifest'>고정 명세</a> · <a href='/library/snapshots/{esc(s['id'])}/metadata'>서명 메타데이터</a> · <a href='/library/snapshots/{esc(s['id'])}/public-key'>후보 공개키</a></td><td>{len(s['packages'])}</td><td>{esc(s['validation_scope'])}</td></tr>" for s in snaps)+f"</table><form method='post' action='/library/snapshot'><label for='base'>기준 버전</label><select id='base' name='base'>{options}</select><label for='version'>보관할 버전 이름</label><input id='version' name='version' required pattern='[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}' placeholder='stage3-6.1.187-r1'><button>새 스냅샷 보관</button></form><form method='post' action='/library/sync'><button>완료 패키지 동기화·SHA 확인</button></form></div>"
            body+=f"<div class='panel'><h2>소스·바이너리 버전 목록</h2><p>바이너리 {len(records)}개 · 소스·관련 파일 {len(sources)}개. 소스가 없는 항목은 원격 공식 소스를 확보한 뒤 SHA가 일치해야 다운로드에 표시됩니다.</p><form method='get' action='/versions'><label for='q'>패키지·버전 검색</label><input id='q' name='q' value='{esc(search)}'><button>검색</button></form><table><tr><th>패키지·버전</th><th>검증·연결 정보</th><th>소스</th><th>바이너리</th></tr>{''.join(rows)}</table></div>"
            policy=lib.root/'repository-auto-publish.json'
            if policy.exists() and read(policy).get('enabled'):
                auto=read(policy)
                body="<div class='panel'><h2>후보 저장소 자동 배포</h2><p>완료 빌드의 파일 명세·SHA·의존성을 확인하고 후보 서명을 생성한 뒤 공개 저장소에 자동 게시합니다. 런타임·새 설치 검증과 공식 릴리스 승격은 별도입니다.</p><p>현재 기준: <code>"+esc(auto.get('base',''))+"</code> · <a href='/ki2/'>공개 패키지 저장소</a></p></div>"+body
                rejected=[(job,r) for job,r in lib.catalog.get('repository_publications',{}).items() if r['status']=='rejected']
                if rejected:
                    body="<div class='panel'><h2>저장소 배포 보류</h2><ul>"+''.join('<li>'+esc(job)+': '+esc(r['error'])+'</li>' for job,r in rejected[-10:])+"</ul></div>"+body
            return render('소스·바이너리 버전 관리',views.version_panel(lib)+body)
        def job_page(self,j):
            labels={'iso':'설치 ISO 생성','source':'공식 소스 확보','snapshot':'버전 스냅샷 보관','sync':'보관 파일 SHA 검사','release':'릴리즈 구성 등록','update-check':'새 버전 확인','update-security':'CVE 취약점 확인','update-prepare':'업데이트 후보 준비','update-promote':'안정 업데이트 승격'}
            body=f"<div class='panel'><h2>{labels[j['kind']]}</h2><p><code>{j['id']}</code></p><p id='release-job-phase'>{esc(j['phase'])}</p><p>{esc(j.get('error',''))}</p>"
            if j.get('result'):
                r=j['result'];body+=result_panel(j['kind'],r)
                if j['kind']=='iso':body+=f"<p><a href='/iso-build/jobs/{j['id']}/file'>ISO 다운로드</a> · <a href='/iso-build/jobs/{j['id']}/sha256'>SHA-256 다운로드</a> · <a href='/iso-build/jobs/{j['id']}/report'>검증 명세</a></p>"
                elif j['kind']=='source':body+=f"<a href='/library/files/source/{r['sha256']}'>소스 다운로드</a>"
                elif j['kind']=='release':body+=f"<a href='/releases/{esc(r['release_version'])}'>등록한 릴리즈 열기</a>"
                elif j['kind']=='update-security':body+=f"<a href='/updates/security?base={esc(r['base'])}'>CVE 확인 결과</a>"
                else:body+="<a href='/versions'>버전 목록으로</a>"
            cloud_file=lib.root/'jobs'/j['id']/'cloud-deploy.json'
            cloud=read(cloud_file) if cloud_file.is_file() else {}
            cloud_config=Path(os.environ.get('KI2_CLOUD_DEPLOY_CONFIG',str(lib.root/'cloud-deploy-config.json')))
            try:auto_enabled=cloud_config.is_file() and read(cloud_config).get('enabled') is True
            except (OSError,ValueError):auto_enabled=False
            cloud_eligible=j['kind']=='iso' and (j.get('result') or {}).get('cloud_install_supported') and j['values'].get('profile')=='gnome50'
            if cloud:
                cloud_labels={'queued':'자동 배포 대기','creating':'VM 생성','installing':'무인 설치','cutover':'설치 디스크로 전환','validating':'첫 디스크 부팅 검사','rebooting':'재부팅 검사','passed':'실제 설치 검증 통과','failed':'검증 실패','needs-review':'점검 필요 · VM 보존'}
                body+=f"<h2>OpenStack 자동 설치·검증</h2><p>{esc(cloud_labels.get(cloud.get('status'),cloud.get('status')))} · {esc(cloud.get('phase',''))}</p><p>설치 VM: <code>{esc(cloud.get('installerVmId',''))}</code><br>설치된 VM: <code>{esc(cloud.get('runtimeVmId',''))}</code></p><p>{esc(cloud.get('error') or '')}</p><p><a href='/iso-build/jobs/{j['id']}/cloud-report'>VM 검증 보고서</a></p>"
            elif cloud_eligible:
                body+="<p>서명된 OpenStack 무인 설치 지원 · "+('자동 배포 요청 준비 중' if auto_enabled else '자동 배포 설정 대기')+"</p>"
            log=(lib.root/'jobs'/j['id']/'log.txt').read_text(encoding='utf-8',errors='replace')[-60000:]
            refresh=j['status'] in {'pending','running'} or bool(cloud and cloud.get('status') not in {'passed','failed','needs-review'}) or bool(cloud_eligible and auto_enabled and not cloud)
            return render('ISO·소스 작업 상세',body+f"</div><div class='panel'><h2>실행 로그</h2><p>컴파일러·도구 출력은 원문으로 표시합니다.</p><pre>{esc(log)}</pre></div>",refresh)
    return Handler


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True);p.add_argument('--backend',type=Path,default=Path('/backend'))
    p.add_argument('--legacy-backend',type=Path)
    p.add_argument('--baseline',type=Path,default=Path('/inputs/baseline'));p.add_argument('--sources',type=Path,default=Path('/sources'))
    p.add_argument('--native-packages',type=Path,default=Path('/native-packages'));p.add_argument('--port',type=int,default=8094)
    p.add_argument('action',choices=['serve','sync','iso']);p.add_argument('--snapshot',default='baseline-6.1.187');p.add_argument('--profile',default='gnome50')
    p.add_argument('--release-version',default='');p.add_argument('--cpu-profile',default='x86_64')
    args=p.parse_args();os.umask(0o077);lib=Library(args.store,args.backend,args.baseline,args.sources,args.native_packages,args.legacy_backend)
    os.environ['TMPDIR']=str(lib.root/'tmp');tempfile.tempdir=str(lib.root/'tmp')
    import fcntl
    lease=(lib.root/'worker.lock').open('a+b')
    fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.action=='sync':lib.synchronize();print('후보 패키지·소스·스냅샷 등록 완료');return
    lib.start()
    if args.action=='iso':
        j=lib.submit('iso',{'snapshot':args.snapshot,'profile':args.profile,'release_version':args.release_version,'cpu_profile':args.cpu_profile});lib.pending.join();print(json.dumps(lib.job(j['id']),ensure_ascii=False));return
    with ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(lib)) as server:
        signal.signal(signal.SIGTERM,lambda *_:threading.Thread(target=server.shutdown,daemon=True).start())
        print('KIKI 버전·ISO 관리 서비스 준비 완료',flush=True)
        try:server.serve_forever()
        finally:lib.stop.set()


if __name__=='__main__':main()
