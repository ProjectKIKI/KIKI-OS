"""Durable ISO completion outbox. Build success and VM validation stay separate."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
import subprocess
import tempfile
import time
import urllib.request
import uuid

import ki2installcatalog

PART_BYTES = 256 * 1024**2


def api(config, method, route, value=None):
    body = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode() if value is not None else b''
    stamp = str(int(time.time())); nonce = uuid.uuid4().hex
    digest = hashlib.sha256(body).hexdigest()
    message = '\n'.join([method, route, stamp, nonce, digest]).encode()
    with tempfile.TemporaryDirectory(prefix='kiki-machine-sign-') as directory:
        path=Path(directory)/'message';path.write_bytes(message)
        signature=subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',config['signing_key'],'-in',str(path)],check=True,capture_output=True,timeout=10).stdout.hex()
    request = urllib.request.Request(config['endpoint'].rstrip('/')+route, body if value is not None else None,
        method=method, headers={'Content-Type': 'application/json', 'Accept':'application/json','User-Agent':'KIKI-Build-Deploy/1.0', 'X-Kiki-Time': stamp, 'X-Kiki-Nonce': nonce,
                               'X-Kiki-Signature': signature})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def publish_parts(iso, directory, sha):
    directory.mkdir(exist_ok=True)
    manifest = directory/'index.json'
    if manifest.exists():
        result = json.loads(manifest.read_text())
        if result['iso_sha256'] != sha(iso): raise ValueError('published ISO changed')
        for part in result['parts']:
            path = directory/(part['sha256']+'.part')
            if path.stat().st_size != part['bytes'] or sha(path) != part['sha256']:raise ValueError('published ISO part changed')
        return result['parts']
    parts = []
    with iso.open('rb') as source:
        while block := source.read(PART_BYTES):
            digest = hashlib.sha256(block).hexdigest(); target = directory/(digest+'.part')
            temporary = target.with_suffix('.pending')
            temporary.write_bytes(block);temporary.replace(target)
            parts.append({'sha256': digest, 'bytes': len(block)})
    from ki2release import save
    save(manifest, {'schema': 'kiki-cloud-artifact-v1', 'iso_sha256': sha(iso), 'parts': parts})
    return parts


POLICY_FILES = ['kiki-desktop-xccdf.xml','kiki-desktop-oval.xml','kiki-cpe.xml']


def package_policy_digest(package, package_sha256, critical):
    import hashlib, tarfile
    from ki2release import sha
    if sha(package)!=package_sha256:raise ValueError('security policy package changed')
    digest=hashlib.sha256()
    with tarfile.open(package) as archive:
        for name in POLICY_FILES:
            path='/usr/share/kiki-security/'+name
            member=archive.getmember('rootfs'+path)
            if not member.isfile():raise ValueError('security policy must be a regular file')
            payload=archive.extractfile(member).read()
            if hashlib.sha256(payload).hexdigest()!=critical.get(path):raise ValueError('security policy payload mismatch')
            digest.update(name.encode()+b'\0'+payload)
    return digest.hexdigest()


def pinned_policy_digest(lib, job, expected):
    snapshot=lib.root/'snapshots'/job['values']['snapshot']
    manifest=json.loads((snapshot/'manifest.json').read_text())
    record=lib.catalog['binaries'][manifest['packages']['kiki-security-content']]
    if record['sha256']!=expected['packages']['kiki-security-content']:raise ValueError('security policy input binding mismatch')
    return package_policy_digest(snapshot/'packages'/record['file'],record['sha256'],expected['critical_files'])


def expected_install(lib, job):
    from ki2release import closure, sha
    snapshot = lib.root/'snapshots'/job['values']['snapshot']
    manifest = json.loads((snapshot/'manifest.json').read_text())
    binaries = {n: lib.catalog['binaries'][s] for n,s in manifest['packages'].items()}
    catalog = ki2installcatalog.load(lib.root/'jobs'/job['id']/'package-groups.json')
    groups=['desktop-gnome','security-audit']
    if job['values'].get('vm_group'):groups.append(job['values']['vm_group'])
    selected = ki2installcatalog.expand(catalog, groups)
    order = closure(binaries, selected['packages'])
    critical = {}
    names = ['ki2ctl','kiki-installer-tui','kiki-admin','gnome-control-center','nautilus','gnome-console','openscap','kiki-security-content','linux','readline','openssh','kiki-desktop-defaults']
    names += [n for n in ['qemu-guest-agent','hyperv-daemons','kiki-vm-tools'] if n in order]
    for name in names:
        package = lib.repo.read_package_manifest(snapshot/'packages'/binaries[name]['file'])
        for entry in package['files']:
            path = entry['path']
            vm_policy=name in {'qemu-guest-agent','hyperv-daemons','kiki-vm-tools'} and path.startswith(('/usr/sbin/','/usr/lib/systemd/system/','/usr/libexec/hypervkvpd/','/etc/qemu/'))
            if entry['type']=='file' and (vm_policy or path.startswith(('/usr/bin/','/usr/libexec/kiki-security','/usr/share/kiki-security/','/boot/')) or path in ['/usr/lib/libreadline.so.8.3','/usr/lib/libhistory.so.8.3','/usr/sbin/sshd','/etc/ssh/sshd_config','/etc/ssh/sshd_config.d/00-kiki-defaults.conf','/etc/kiki/desktop-firewall.nft','/usr/lib/systemd/system/kiki-desktop-firewall.service','/etc/ki2/repos.d/default.repo','/etc/ki2/trust/kiki-development.ed25519.pub']):
                critical[path] = entry['sha256']
    result = {'profile':'desktop-gnome','groups':selected['groups'], 'packages':{n:binaries[n]['sha256'] for n in order},
            'catalog_sha256':sha(lib.root/'jobs'/job['id']/'package-groups.json'), 'critical_files':critical,
            'security_policy_sha256':critical['/usr/share/kiki-security/kiki-desktop-xccdf.xml']}
    result['security_policy_sha256']=pinned_policy_digest(lib,job,result)
    return result


def validate_result(response, manifest, expected_policy=None):
    if response.get('id')!=manifest['job_id'] or response.get('iso_sha256')!=manifest['iso_sha256']:
        raise ValueError('deployment report identity mismatch')
    if response.get('status')!='passed':return
    reports=response.get('reports',[]);expected=manifest['expected']
    if len(reports)!=2 or reports[0].get('boot_id')==reports[1].get('boot_id') or not response.get('runtimeVmId'):
        raise ValueError('VM report does not prove two distinct disk boots')
    for report in reports:
        if report.get('status')!='passed' or not report.get('checks') or not all(v is True for v in report['checks'].values()):
            raise ValueError('VM checks have not all passed')
        if report.get('vm_id')!=response['runtimeVmId'] or report.get('iso_sha256')!=manifest['iso_sha256'] or report.get('catalog_sha256')!=expected['catalog_sha256']:
            raise ValueError('VM report input binding mismatch')
        if report.get('installed_count')!=len(expected['packages']) or report.get('critical_files_checked')!=len(expected['critical_files']):
            raise ValueError('VM report does not cover all package inputs')
        scap=report.get('scap',{})
        policy=expected_policy or expected['security_policy_sha256']
        if expected_policy:
            paths=['/usr/share/kiki-security/'+name for name in POLICY_FILES]
            if any(path not in expected['critical_files'] for path in paths):raise ValueError('OpenSCAP policy file coverage missing')
            if report.get('policy_content_files')!={p:expected['critical_files'][p] for p in paths}:raise ValueError('OpenSCAP policy file hashes differ')
            # Early v1 manifests accidentally anchored the XCCDF file alone.
            # Preserve those immutable inputs, but compare the scan against the
            # independent bundle digest recomputed from their signed package.
            if expected['security_policy_sha256'] not in [policy,expected['critical_files'][paths[0]]]:raise ValueError('OpenSCAP policy anchor mismatch')
        if scap.get('policy_sha256')!=policy or len(scap.get('rules',[]))!=9 or any(r.get('result')!='pass' for r in scap['rules']):
            raise ValueError('unchanged nine-rule OpenSCAP scan did not pass')


def tick(lib, config):
    from ki2release import read, save, sha, now
    if not config.get('enabled'):return
    for job in reversed(lib.jobs()):
        result = job.get('result') or {}
        if job['kind'] != 'iso' or job['status'] != 'succeeded' or not result.get('cloud_install_supported') or job['values']['profile'] != 'gnome50':continue
        directory = lib.root/'jobs'/job['id']; statefile = directory/'cloud-deploy.json'
        state = read(statefile) if statefile.exists() else {}
        if state.get('status') in ['passed','failed','needs-review']:continue
        if not state.get('submitted'):
            iso = directory/result['file']
            if sha(iso) != result['sha256']:raise ValueError('ISO changed before deployment')
            parts = publish_parts(iso, directory/'cloud-artifact', sha)
            expected = expected_install(lib, job)
            manifest = {'schema':'kiki-cloud-build-v1', 'job_id':job['id'], 'iso_sha256':result['sha256'],
                        'iso_bytes':result['bytes'], 'parts':parts, 'snapshot':job['values']['snapshot'], 'expected':expected}
            save(directory/'cloud-manifest.json',manifest)
            response = api(config,'POST','/api/kiki-builds',manifest)
            state = {'submitted':True,'status':response['status'],'at':now()};save(statefile,state)
        response = api(config,'GET','/api/kiki-builds/'+job['id'])
        manifest=read(directory/'cloud-manifest.json')
        policy=pinned_policy_digest(lib,job,manifest['expected']) if response.get('status')=='passed' else None
        validate_result(response,manifest,policy)
        save(statefile, {**response,'submitted':True,'at':now()})
        if response.get('status') == 'passed':
            save(directory/'openstack-install-report.json',response)
            reports=response.get('reports',[])
            current=lib.job(job['id']);result={**current['result'],'fresh_install_tested':True,'fresh_install_status':'passed','fresh_vm_id':response['runtimeVmId'],
                'fresh_boot_ids':[r['boot_id'] for r in reports],'openstack_install_report_sha256':sha(directory/'openstack-install-report.json'),'gdm_login_tested':False}
            save(directory/'result.json',result)
            lib.update(current,result=result)
        # One active deployment at a time; the ISO builder itself remains free.
        if response.get('status') not in ['passed','failed','needs-review']:break


def start(lib):
    configfile = Path(os.environ.get('KI2_CLOUD_DEPLOY_CONFIG',str(lib.root/'cloud-deploy-config.json')))
    if not configfile.is_file():return
    def work():
        from ki2release import save, now
        while not lib.stop.is_set():
            try:tick(lib,json.loads(configfile.read_text()))
            except Exception as error:save(lib.root/'cloud-deploy-error.json',{'at':now(),'error':type(error).__name__})
            lib.stop.wait(20)
    threading.Thread(target=work,daemon=True,name='cloud-deploy-outbox').start()
