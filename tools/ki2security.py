"""Source-aware advisory lookup. Missing coverage never means vulnerability-free."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request


def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def checksum(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def fetch_json(url,data=None):
    # Providers are fixed by this module; no user-controlled URL or credentials.
    if urllib.parse.urlsplit(url).hostname not in {'api.osv.dev','services.nvd.nist.gov','www.cisa.gov'}:raise ValueError('unsupported security provider')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('security provider redirect refused')
    request=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,
        headers={'User-Agent':'KIKI-security/1.0','Accept':'application/json','Content-Type':'application/json'})
    with urllib.request.build_opener(Redirect()).open(request,timeout=20) as response:
        raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('security response too large')
        return json.loads(raw)


def osv_query(mapping,version,reader=fetch_json):
    version=version.replace('.',mapping.get('version_separator','.'))
    query={'package':{'ecosystem':mapping['ecosystem'],'name':mapping['project']},'version':mapping.get('tag_prefix','')+version}
    results={}
    for page in range(20):
        response=reader('https://api.osv.dev/v1/query',query)
        if not isinstance(response,dict) or not isinstance(response.get('vulns',[]),list):raise ValueError('invalid OSV response')
        for record in response.get('vulns',[]):
            if not record.get('withdrawn'):results[record['id']]=record
        token=response.get('next_page_token')
        if not token:return list(results.values())
        query['page_token']=token
    raise ValueError('OSV pagination limit reached; incomplete lookup')


def normalize(record,provider,kev):
    aliases=sorted(set([record['id']]+record.get('aliases',[])))
    cves=[v for v in aliases if v.startswith('CVE-')]
    fixed=sorted({e['fixed'] for a in record.get('affected',[]) for r in a.get('ranges',[]) for e in r.get('events',[]) if 'fixed' in e})
    links=[r['url'] for r in record.get('references',[]) if urllib.parse.urlsplit(r.get('url','')).scheme=='https']
    return {'id':cves[0] if cves else record['id'],'aliases':aliases,'summary':str(record.get('summary',''))[:1500],
        'modified':record.get('modified'),'severity':record.get('severity',[]),'fixed':fixed,'references':links[:30],
        'provider':provider,'kev':any(c in kev for c in cves),'status':'potential','reason':'원본 버전 조회 결과; 빌드 옵션·백포트 패치는 별도 확인'}


def merge_findings(rows):
    merged=[]
    for row in rows:
        matching=[r for r in merged if set(r['aliases'])&set(row['aliases'])]
        for old in matching:
            merged.remove(old)
            for key in ['aliases','fixed','references']:row[key]=sorted(set(row[key]+old[key]))
            row['kev']=row['kev'] or old['kev']
        cves=sorted(a for a in row['aliases'] if a.startswith('CVE-'))
        if cves:row['id']=cves[0]
        merged.append(row)
    return merged


class Security:
    def __init__(self,updates):
        self.u=updates;self.c=updates.c;self.root=updates.root/'security';self.root.mkdir(exist_ok=True)
        self.mapping_file=Path(__file__).with_name('security-mappings.json')

    def mappings(self):return self.c.read(self.mapping_file) if self.mapping_file.exists() else {'packages':{}}
    def result(self,base=None):
        base=base or self.u.config().get('baseline','')
        if not self.c.valid_id(base):return {'rows':[],'notifications':[],'base':base}
        p=self.root/(base+'.json')
        return self.c.read(p) if p.exists() else {'rows':[],'notifications':[],'base':base}

    def acknowledge(self,base):
        with self.u.lib.lock:
            data=self.result(base)
            for n in data.get('notifications',[]):n['read']=True
            self.c.save(self.root/(data['base']+'.json'),data)

    def cached(self,identity,loader):
        path=self.root/'cache'/(checksum(identity)+'.json')
        if path.exists() and time.time()-path.stat().st_mtime<21600:return self.c.read(path)['data']
        value=loader();self.c.save(path,{'identity':identity,'at':now(),'data':value});return value

    def sbom(self,base):
        snap,packages=self.u.baseline(base);mapping=self.mappings()['packages'];components=[]
        for name,p in sorted(packages.items()):
            m=mapping.get(name,{})
            row={'type':'library','name':name,'version':p['version']+'-'+p['release'],'bom-ref':p['sha256'],
                'hashes':[{'alg':'SHA-256','content':p['sha256']}],
                'properties':[{'name':'ki2:upstream-version','value':p['version']},{'name':'ki2:recipe-digest','value':p.get('recipe_digest','')}]}
            for key in ['url','sha256']:
                if p.get('source',{}).get(key):row['properties'].append({'name':'ki2:source:'+key,'value':p['source'][key]})
            if m.get('cpe'):row['cpe']=m['cpe'].replace('{version}',p['version'])
            components.append(row)
        return {'bomFormat':'CycloneDX','specVersion':'1.6','version':1,'metadata':{'timestamp':now(),
            'component':{'type':'operating-system','name':'KIKI OS','version':base}},'components':components}

    def scan(self,job,reader=fetch_json):
        base=job['values'].get('base') or self.u.config()['baseline'];_,packages=self.u.baseline(base)
        mappings=self.mappings();previous=self.result(base);previous_rows={r['name']:r for r in previous['rows']}
        origins={r['name']:r['url'] for r in self.u.source_rows(base)}
        self.u.lib.update(job,phase='CVE 원본 프로젝트 매핑·공식 데이터 조회')
        kev=set();kev_error=None
        try:
            data=self.cached('cisa-kev',lambda:reader('https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'))
            kev={r['cveID'] for r in data['vulnerabilities']}
        except Exception as e:kev_error=str(e)[:300]
        def check(item):
            name,p=item;m=mappings['packages'].get(name)
            row={'name':name,'version':p['version'],'release':p['release'],'sha256':p['sha256'],'findings':[],
                'status':'unmapped','message':'원본 프로젝트 매핑 필요','checked_at':now(),'source_url':origins.get(name,'')}
            if not m:return row
            # Mappings bind to reviewed source provenance, not a similar binary name.
            source=p.get('source',{});url=source.get('url','') or origins.get(name,'')
            if not any(url.startswith(prefix) for prefix in m.get('source_prefixes',[])):
                row['message']='보존 출처와 검토된 프로젝트 매핑 불일치';return row
            row['mapping']=m;row['providers']={}
            if m.get('osv') is False:
                row.update(status='pending' if self.u.config().get('security',{}).get('nvd') else 'unmapped',message='NVD CPE 조회 · 대용량 OSV 커널 응답은 사용하지 않음')
                row['providers']['osv']='not-used';return row
            try:
                records=self.cached(['osv',m['ecosystem'],m['project'],m.get('tag_prefix',''),p['version']],lambda:osv_query(m,p['version'],reader))
                row['findings']=merge_findings([normalize(r,'OSV',kev) for r in records]);row['providers']['osv']='ok'
                row['status']='potential' if records else 'no-known-match';row['message']='지원 데이터 범위의 조회 결과; 안전성 보증 아님'
            except Exception as e:
                row.update(status='error',message=str(e)[:400]);row['providers']['osv']='error'
                old=previous_rows.get(name,{})
                if old.get('sha256')==p['sha256']:
                    row['findings']=old.get('findings',[]);row['previous_checked_at']=old.get('checked_at')
            return row
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(check,sorted(packages.items())))
        # NVD is optional and deliberately serialized for the public API limit.
        if self.u.config().get('security',{}).get('nvd',False):
            last_request=[0.0]
            for row in rows:
                m=row.get('mapping',{})
                if not m.get('cpe'):continue
                cpe=m['cpe'].replace('{version}',row['version'])
                def nvd():
                    records=[];start=0
                    for page in range(50):
                        time.sleep(max(0,6.5-(time.monotonic()-last_request[0])));last_request[0]=time.monotonic()
                        url='https://services.nvd.nist.gov/rest/json/cves/2.0?'+urllib.parse.urlencode({'cpeName':cpe,'isVulnerable':'','resultsPerPage':100,'startIndex':start})
                        data=reader(url);batch=data.get('vulnerabilities',[])
                        for item in batch:
                            c=item['cve'];records.append({'cve':{k:c[k] for k in ['id','lastModified','vulnStatus','metrics','descriptions','references'] if k in c}})
                        start+=len(batch)
                        if start>=data.get('totalResults',len(batch)):return {'totalResults':start,'vulnerabilities':records}
                        if not batch:break
                    raise ValueError('NVD result incomplete; pagination limit reached')
                try:
                    data=self.cached(['nvd',cpe],nvd)
                    existing={a for f in row['findings'] for a in f['aliases']}
                    for entry in data.get('vulnerabilities',[]):
                        c=entry['cve']
                        if c.get('vulnStatus')=='Rejected':continue
                        severity=[]
                        for entries in c.get('metrics',{}).values():
                            for metric in entries:
                                cvss=metric.get('cvssData',{})
                                if not cvss:continue
                                severity.append({'type':'CVSS'+cvss.get('version',''),'score':cvss.get('vectorString',''),'base_score':cvss.get('baseScore'),'source':metric.get('source')})
                        normalized=normalize({'id':c['id'],'modified':c.get('lastModified'),'severity':severity,'summary':next((d['value'] for d in c.get('descriptions',[]) if d['lang']=='en'),''),'references':c.get('references',[])},'NVD',kev)
                        if c['id'] in existing:
                            target=next(f for f in row['findings'] if c['id'] in f['aliases'])
                            target['severity']+= [s for s in severity if s not in target['severity']]
                            target['references']=sorted(set(target['references']+normalized['references']));target['provider']='OSV·NVD'
                        else:row['findings'].append(normalized)
                    row['providers']['nvd']='ok'
                    if row['status']!='error':row['status']='potential' if row['findings'] else 'no-known-match'
                except Exception as e:
                    row.update(status='error',message='NVD: '+str(e)[:350]);row['providers']['nvd']='error'
                    old=previous_rows.get(row['name'],{})
                    if old.get('sha256')==row['sha256']:
                        current={a for f in row['findings'] for a in f['aliases']}
                        row['findings'] += [f for f in old.get('findings',[]) if not current.intersection(f['aliases'])]
                        row['previous_checked_at']=old.get('checked_at')
        notices=list(previous.get('notifications',[]));known={n['key'] for n in notices}|set(previous.get('observed_keys',[]));observed=[]
        for row in rows:
            for f in row['findings']:
                identity=checksum([row['sha256'],f['id'],f.get('modified'),f.get('kev'),f.get('severity')])
                observed.append(identity)
                if identity not in known:
                    notices.append({'key':identity,'name':row['name'],'id':f['id'],'kev':f['kev'],'read':False,'at':now()});known.add(identity)
        result={'schema':'ki2-security-v1','base':base,'checked_at':now(),'mapping_sha256':checksum(mappings),
            'index_sha256':self.c.sha(self.u.lib.root/'snapshots'/base/'repo/index.x86_64.json'),'rows':rows,
            'notifications':notices[-2000:],'observed_keys':observed,'kev_error':kev_error,'policy':'advisory','coverage':{k:sum(r['status']==k for r in rows) for k in ['unmapped','error','potential','no-known-match']}}
        self.c.save(self.root/(base+'.json'),result)
        return {'base':base,'coverage':result['coverage'],'findings':sum(len(r['findings']) for r in rows),'kev_error':kev_error}
