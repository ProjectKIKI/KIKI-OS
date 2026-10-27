"""Release membership, immutable CPU inputs and reversible lifecycle metadata."""
import json
from ki2cpu import PROFILES, validate_selection
from ki2release_views import os_version, version_targets


STATES = {'candidate':'후보', 'locked':'구성 잠금', 'archived':'보관됨', 'legacy':'기존 보관 · 관리 미등록'}


class ReleaseManager:
    def __init__(self, lib, core):
        self.lib, self.c = lib, core

    def version_path(self, name):
        if not self.c.valid_id(name):raise ValueError('올바르지 않은 릴리즈 이름입니다.')
        return self.lib.root/'release-versions'/name/'manifest.json'

    def metadata_path(self, name):
        self.version_path(name)
        return self.lib.root/'release-management'/name/'record.json'

    def get(self, name):
        version_path=self.version_path(name)
        if not version_path.exists():
            jobs=self.isos(name)
            if not jobs:raise FileNotFoundError('릴리즈가 없습니다.')
            pins={}
            for job in jobs:
                cpu=job['values'].get('cpu_profile','x86_64');snapshot=job['values']['snapshot']
                path=self.lib.root/'snapshots'/snapshot/'manifest.json'
                digest=(job.get('result') or {}).get('snapshot_manifest_sha256') or self.c.sha(path)
                pin={'snapshot':snapshot,'snapshot_manifest_sha256':digest}
                if cpu in pins and pins[cpu]!=pin:raise ValueError('과거 ISO의 패키지 구성이 서로 다릅니다. 별도 릴리즈로 구분해야 합니다.')
                pins[cpu]=pin
            return dict(version=name,title=name,notes='기존 ISO 기록에서 조회한 구성입니다. 관리 등록 시 SHA·의존성·서명을 다시 검사합니다.',state='legacy',revision=0,
                        created_at=min(j['created_at'] for j in jobs),default_profile=jobs[0]['values']['profile'],history=[],targets=pins)
        version=self.c.read(version_path);path=self.metadata_path(name)
        meta=self.c.read(path) if path.exists() else {}
        state=meta.get('state','candidate')
        if state not in STATES:raise ValueError('릴리즈 관리 상태를 확인하세요.')
        return dict(version=name, title=meta.get('title',name), notes=meta.get('notes',''), state=state,
                    revision=meta.get('revision',0), created_at=version['created_at'],
                    default_profile=meta.get('default_profile','gnome50'), history=meta.get('history',[]),
                    targets=version_targets(version))

    def list(self):
        names={v['version'] for v in self.lib.release_versions()}
        names.update(os_version(j) for j in self.lib.jobs() if j['kind']=='iso')
        return sorted([self.get(n) for n in names],key=lambda r:r['created_at'],reverse=True)

    def packages(self, name, cpu):
        release=self.get(name)
        if cpu not in release['targets']:raise ValueError('해당 릴리즈에 등록되지 않은 CPU 대상입니다.')
        pin=release['targets'][cpu];path=self.lib.root/'snapshots'/pin['snapshot']/'manifest.json'
        if self.c.sha(path)!=pin['snapshot_manifest_sha256']:raise ValueError('릴리즈의 고정 스냅샷 명세가 변경됐습니다.')
        snapshot=self.c.read(path)
        return snapshot, {n:self.lib.catalog['binaries'][key] for n,key in snapshot['packages'].items()}

    def isos(self, name, cpu=None):
        return [j for j in self.lib.jobs() if j['kind']=='iso' and os_version(j)==name
                and (cpu is None or j['values'].get('cpu_profile','x86_64')==cpu)]

    def iso_allowed(self, name, cpu, snapshot=None):
        if name in {'new','register'}:raise ValueError('화면 경로에 사용하는 이름입니다. 다른 릴리즈 이름을 입력하세요.')
        for job in self.lib.jobs():
            if job['kind']=='release' and job['status'] in {'pending','running'} and job['values']['release_version']==name and job['values']['cpu_profile']==cpu:
                raise ValueError('릴리즈 구성을 등록 중입니다. 등록 완료 후 ISO를 생성하세요.')
        path=self.version_path(name)
        if not path.exists():
            previous={j['values']['snapshot'] for j in self.isos(name,cpu)}
            if previous and (len(previous)!=1 or snapshot is not None and snapshot not in previous):
                raise ValueError('과거 ISO와 다른 패키지 구성입니다. 새 릴리즈 이름을 사용하세요.')
            return
        release=self.get(name)
        if release['state']=='archived':raise ValueError('보관한 릴리즈입니다. 보관 해제 후 ISO를 생성하세요.')
        if release['state']=='locked' and cpu not in release['targets']:
            raise ValueError('잠긴 릴리즈에 CPU 구성을 추가할 수 없습니다. 새 릴리즈를 등록하세요.')

    def validate_registration(self, values, own_job=None):
        name=values.get('release_version','');self.version_path(name)
        if name in {'new','register'}:raise ValueError('new·register는 화면 경로에 사용하는 이름입니다. 다른 릴리즈 이름을 입력하세요.')
        base=values.get('base','');cpu=values.get('cpu_profile','x86_64');profile=values.get('profile','gnome50')
        if not self.c.valid_id(base):raise ValueError('기준 스냅샷을 선택하세요.')
        path=self.lib.root/'snapshots'/base/'manifest.json'
        if not path.exists():raise ValueError('기준 스냅샷이 없습니다.')
        if profile not in {'gnome50','minimal-systemd'}:raise ValueError('운영 구성을 확인하세요.')
        digest=self.c.sha(path)
        if values.get('base_manifest_sha256',digest)!=digest:raise ValueError('등록 대기 중 기준 스냅샷 명세가 변경됐습니다.')
        title=values.get('title','').strip() or name;notes=values.get('notes','')
        if len(title)>120 or len(notes)>8000 or '\0' in title+notes:raise ValueError('제목은 120자, 메모는 8,000자까지 입력하세요.')
        changes=values.get('changes',{})
        if isinstance(changes,str):changes=json.loads(changes)
        if not isinstance(changes,dict) or len(changes)>1024:raise ValueError('패키지 변경 목록을 확인하세요.')
        selection=dict(self.c.read(path)['packages'])
        for package,key in changes.items():
            if not isinstance(package,str) or not isinstance(key,str):raise ValueError('패키지 선택 형식이 올바르지 않습니다.')
            if not key:
                if package not in selection:raise ValueError('구성에 없는 패키지는 제외할 수 없습니다.')
                selection.pop(package)
            else:
                record=self.lib.catalog['binaries'].get(key)
                if not record or record['name']!=package:raise ValueError('등록된 패키지 이름과 SHA가 일치하지 않습니다.')
                selection[package]=key
        binaries={n:self.lib.catalog['binaries'][key] for n,key in selection.items()}
        validate_selection(cpu,list(binaries.values()))
        self.c.closure(binaries,sorted(binaries))
        roots=(self.c.read(self.lib.base/'validation/desktop-root-plan.json')['order'] if profile=='gnome50'
               else ['base-files','linux','systemd','dbus','bash','coreutils','util-linux','busybox','shadow','openssh','kiki-netconfig'])
        self.c.closure(binaries,list(roots)+['linux','kiki-installer-gtk'])
        if self.version_path(name).exists():
            release=self.get(name)
            if release['state']!='candidate':raise ValueError('후보 릴리즈에만 새 CPU 구성을 추가할 수 있습니다.')
            if cpu in release['targets']:raise ValueError('이미 고정된 릴리즈·CPU 구성입니다. 변경하려면 새 릴리즈를 등록하세요.')
        else:
            previous=self.isos(name,cpu)
            if previous and (any(j['values']['snapshot']!=base for j in previous) or selection!=self.c.read(path)['packages']):
                raise ValueError('과거 ISO를 다른 패키지로 다시 등록할 수 없습니다. 새 릴리즈 이름을 사용하세요.')
        for job in self.lib.jobs():
            if job['id']==own_job or job['status'] not in {'pending','running'}:continue
            if job['kind']=='release' and job['values']['release_version']==name:
                raise ValueError('이 릴리즈를 등록 중입니다. 기존 작업 완료 후 요청하세요.')
            if job['kind']=='iso' and os_version(job)==name and job['values'].get('cpu_profile','x86_64')==cpu:
                raise ValueError('이 릴리즈·CPU의 ISO 작업이 진행 중입니다.')
        return dict(release_version=name,base=base,cpu_profile=cpu,profile=profile,title=title,notes=notes,
                    changes=changes,base_manifest_sha256=digest)

    def register_job(self, job):
        values=self.validate_registration(job['values'],job['id']);name=values['release_version'];cpu=values['cpu_profile']
        base_dir=self.lib.root/'snapshots'/values['base'];base=self.c.read(base_dir/'manifest.json')
        selection=dict(base['packages'])
        for package,key in values['changes'].items():
            if key:selection[package]=key
            else:selection.pop(package)
        self.lib.update(job,phase='릴리즈 패키지 SHA·의존성·후보 서명 검사')
        for kind,key in [('index','index_sha256'),('metadata','metadata_sha256')]:
            if self.c.sha(base_dir/'repo'/(kind+'.x86_64.json'))!=base[key]:raise ValueError('기준 저장소 명세 SHA가 변경됐습니다.')
        if not self.lib.repo.verify_metadata_file(base_dir/'repo/metadata.x86_64.json',base_dir/'candidate.pub'):
            raise ValueError('기준 스냅샷의 후보 서명 검사 실패')
        for package,key in selection.items():
            record=self.lib.catalog['binaries'][key]
            if self.c.sha(self.lib.root/'objects'/key)!=key:raise ValueError('릴리즈 패키지 보관 객체 SHA 불일치: '+package)
            if base['packages'].get(package)==key and self.c.sha(base_dir/'packages'/record['file'])!=key:
                raise ValueError('기준 스냅샷의 패키지 SHA 불일치: '+package)
        changed={n for n in set(selection)|set(base['packages']) if selection.get(n)!=base['packages'].get(n)}
        snapshot=base
        if changed:
            snapshot_name='rel-'+name[:32]+'-'+cpu+'-'+job['id'][:8]
            self.lib.update(job,phase='변경한 패키지 구성을 별도 스냅샷으로 보관')
            snapshot=self.lib.snapshot(snapshot_name,selection,'릴리즈 SHA·의존성 검사 · 실제 설치·로그인은 별도 검증')
        with self.lib.lock:
            # Recheck lifecycle and reservations after the slow file verification.
            self.validate_registration(values,job['id'])
            path=self.version_path(name);existed=path.exists()
            version=self.c.read(path) if existed else {'schema':'kiki-os-version-v2','version':name,'created_at':self.c.now(),'targets':{}}
            pins=version_targets(version) if existed else {}
            pins[cpu]={'snapshot':snapshot['id'],'snapshot_manifest_sha256':self.c.sha(self.lib.root/'snapshots'/snapshot['id']/'manifest.json')}
            version.update(schema='kiki-os-version-v2',targets=pins);self.c.save(path,version)
            meta=self.get(name)
            if not existed:meta.update(title=values['title'],notes=values['notes'],default_profile=values['profile'])
            meta['history'].append({'at':self.c.now(),'action':'CPU 구성 등록','cpu':cpu,'snapshot':snapshot['id']})
            meta['revision']+=1;self.c.save(self.metadata_path(name),meta)
        return dict(release_version=name,snapshot=snapshot['id'],cpu_profile=cpu,packages=len(selection),changed_packages=len(changed),
                    validation='패키지 SHA·실행 의존성·후보 서명 검사 통과 · VM 검증은 별도')

    def manage(self, name, action, revision, title='', notes=''):
        with self.lib.lock:
            release=self.get(name)
            if release['state']=='legacy':raise ValueError('기존 보관 릴리즈를 먼저 관리 등록하세요.')
            if str(release['revision'])!=str(revision):raise ValueError('다른 화면에서 릴리즈가 변경됐습니다. 새로고침 후 요청하세요.')
            before=release['state']
            if action=='edit':
                title=title.strip() or name
                if len(title)>120 or len(notes)>8000 or '\0' in title+notes:raise ValueError('제목·메모 길이를 확인하세요.')
                release.update(title=title,notes=notes)
            else:
                if any(j['status'] in {'pending','running'} and (os_version(j) if j['kind']=='iso' else j['values'].get('release_version'))==name for j in self.lib.jobs()):
                    raise ValueError('진행 중인 릴리즈·ISO 작업이 끝난 뒤 상태를 변경하세요.')
                if action=='lock' and before=='candidate':release['state']='locked'
                elif action=='unlock' and before=='locked':release['state']='candidate'
                elif action=='archive' and before in {'candidate','locked'}:release.update(state='archived',restore_state=before)
                elif action=='restore' and before=='archived':
                    previous=self.c.read(self.metadata_path(name)).get('restore_state','candidate')
                    release['state']=previous if previous in {'candidate','locked'} else 'candidate'
                else:raise ValueError('허용되지 않는 릴리즈 상태 변경입니다.')
            release['revision']+=1
            release['history'].append({'at':self.c.now(),'action':action,'from':before,'to':release['state']})
            if before=='archived' and action=='edit':
                release['restore_state']=self.c.read(self.metadata_path(name)).get('restore_state','candidate')
            self.c.save(self.metadata_path(name),release)
            return release

    def compare(self, name, other, cpu):
        _,current=self.packages(name,cpu);_,previous=self.packages(other,cpu);rows=[]
        for package in sorted(set(current)|set(previous)):
            old=previous.get(package);new=current.get(package)
            if old and new and old['sha256']==new['sha256']:continue
            rows.append({'package':package,'kind':'추가' if not old else '제외' if not new else '교체', 'before':old,'after':new})
        return rows

    def manifest(self, name):
        release=self.get(name);targets={}
        for cpu in release['targets']:
            snapshot,packages=self.packages(name,cpu)
            targets[cpu]={'snapshot':snapshot['id'],'packages':packages,
                          'isos':[{'id':j['id'],'status':j['status'],'profile':j['values']['profile'],'result':j.get('result')} for j in self.isos(name,cpu)]}
        return {'schema':'kiki-release-inventory-v1','release':release,'targets':targets,
                'validation_scope':'구성 잠금은 공식 배포 승인이나 실제 설치·로그인 검증을 뜻하지 않습니다.'}
