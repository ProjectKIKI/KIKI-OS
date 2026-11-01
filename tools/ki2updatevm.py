#!/usr/bin/env python3
"""Windows Hyper-V update validator. Report signing key stays on this host."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()

class Validator:
    def __init__(self,config):
        self.config=config;self.repo=Path(__file__).resolve().parents[1]
        sys.path.insert(0,config['ssh_library'])
        import paramiko
        self.ssh=paramiko;self.out=Path(config['output']);self.out.mkdir(parents=True,exist_ok=True)

    def server(self):
        c=self.ssh.SSHClient();c.load_host_keys(self.config['server_known_hosts']);c.set_missing_host_key_policy(self.ssh.RejectPolicy())
        c.connect(self.config['server_host'],port=self.config['server_port'],username=self.config['server_user'],key_filename=self.config['server_key'],allow_agent=False,look_for_keys=False,timeout=15)
        c.get_transport().set_keepalive(20)
        return c

    def guest(self):
        c=self.ssh.SSHClient();c.load_host_keys(self.config['guest_known_hosts']);c.set_missing_host_key_policy(self.ssh.RejectPolicy())
        c.connect(self.config['guest_host'],username=self.config['guest_user'],password=self.config['guest_password'],allow_agent=False,look_for_keys=False,timeout=8)
        return c

    def run(self,c,command,root=False,timeout=180):
        if root:command="sudo -S -p '' sh -c "+shlex.quote(command)
        stdin,stdout,stderr=c.exec_command(command,timeout=timeout)
        if root:stdin.write(self.config['guest_password']+'\n');stdin.flush()
        text=stdout.read().decode('utf-8',errors='replace');error=stderr.read().decode('utf-8',errors='replace');status=stdout.channel.recv_exit_status()
        if status==-1:raise ConnectionError('guest connection closed before an exit status was returned')
        if status:raise RuntimeError('guest command failed ('+str(status)+'): '+text[-2000:]+' '+error[-2000:])
        return text

    def ps(self,action,nonce=''):
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.repo/'tools/ki2updatevm.ps1'),'-Action',action,
                 '-VmName',self.config['vm_name'],'-VmId',self.config['vm_id']]
        if nonce:command+=['-Nonce',nonce]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        if result.returncode:raise RuntimeError('Hyper-V operation failed: '+result.stderr[-2000:])
        return result.stdout.strip()

    def wait_guest(self,old_boot=None,timeout=240):
        end=time.monotonic()+timeout;last=None
        while time.monotonic()<end:
            c=None
            try:
                c=self.guest();boot=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
                if old_boot and boot==old_boot:c.close();time.sleep(3);continue
                return c,boot
            except Exception as error:
                last=error
                if c:c.close()
                time.sleep(3)
        raise RuntimeError('VM did not become reachable after boot: '+str(last))

    def reboot(self,c):
        old=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
        try:self.run(c,'systemctl reboot',root=True,timeout=15)
        except (EOFError,OSError):pass
        c.close();return self.wait_guest(old)

    def inspect(self):
        c=self.guest()
        try:
            command="python3 -c "+shlex.quote("import json;from pathlib import Path;d=json.load(open('/var/lib/ki2/installed.json'));print(json.dumps({'count':len(d['packages']),'packages':{n:r['sha256'] for n,r in d['packages'].items()},'base_config':d['packages']['base-files']['files'],'boot':Path('/proc/cmdline').read_text()}))")
            return json.loads(self.run(c,command))
        finally:c.close()

    def security_scan(self,c,policy):
        report=json.loads(self.run(c,'/usr/libexec/kiki-security-scan',root=True,timeout=240))
        if report.get('status')!='completed' or report.get('policy_sha256')!=policy['sha256'] or not report.get('rules'):raise ValueError('OpenSCAP scan failed or policy changed')
        return report

    def validate(self,server,sftp,row):
        nonce=row['validation_nonce'];base=self.config['server_store'];folder=self.out/nonce;folder.mkdir(exist_ok=True)
        report={k:row[k] for k in ['plan_sha256','base_manifest_sha256','candidate_manifest_sha256','index_sha256']}
        report.update(schema='ki2-update-vm-report-v1',proposal=row['id'],nonce=nonce,vm_id=self.config['vm_id'],profile=self.config['profile'],started_at=stamp(),checks={})
        (folder/'request.json').write_text(json.dumps(row,indent=2))
        c=None;original_config=None
        def progress(phase):print(json.dumps({'phase':phase,'proposal':row['id'],'at':stamp()}),flush=True)
        try:
            progress('baseline-and-vm-identity')
            identity=json.loads(self.ps('inspect'))
            if identity['id'].lower()!=self.config['vm_id'].lower():raise ValueError('Hyper-V VM identity changed')
            if identity['state']=='Off':
                self.ps('start');started,_=self.wait_guest();started.close()
            with sftp.open(base+'/snapshots/'+row['base']+'/manifest.json') as f:raw=f.read()
            if hashlib.sha256(raw).hexdigest()!=row['base_manifest_sha256']:raise ValueError('baseline manifest changed')
            baseline=json.loads(raw)
            with sftp.open(base+'/snapshots/'+row['snapshot']+'/manifest.json') as f:raw=f.read()
            if hashlib.sha256(raw).hexdigest()!=row['candidate_manifest_sha256']:raise ValueError('candidate manifest changed')
            candidate=json.loads(raw)
            with sftp.open(base+'/snapshots/'+row['snapshot']+'/repo/index.x86_64.json') as f:raw=f.read()
            if hashlib.sha256(raw).hexdigest()!=row['index_sha256']:raise ValueError('candidate index changed')
            catalog={p['name']:p for p in json.loads(raw)['packages']}
            c=self.guest();before=json.loads(self.run(c,"python3 -c "+shlex.quote("import json;d=json.load(open('/var/lib/ki2/installed.json'));print(json.dumps({n:r['sha256'] for n,r in d['packages'].items()}))")))
            if not before or any(baseline['packages'].get(n)!=h for n,h in before.items()):raise ValueError('VM installed inventory differs from the pinned baseline; no update was applied')
            if not set(row['rebuild'])<=set(before):raise ValueError('VM profile does not include every rebuilt package; extend the test profile before validation')
            report['base_packages']=before
            report['boot_id_before']=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
            report['failed_before']=self.run(c,'systemctl --failed --no-legend --plain').strip()
            if row.get('security_policy'):report['security']={'before':self.security_scan(c,row['security_policy'])}
            try:self.run(c,'systemctl poweroff',root=True,timeout=15)
            except (EOFError,OSError):pass
            c.close();c=None
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if json.loads(self.ps('inspect'))['state']=='Off':break
                time.sleep(2)
            self.ps('checkpoint',nonce);self.ps('start')
            progress('checkpoint-created')
            c,_=self.wait_guest()
            remote='/var/tmp/ki2-update-validator/'+nonce
            self.run(c,'mkdir -p '+shlex.quote(remote+'/usr/bin')+' '+shlex.quote(remote+'/usr/libexec'))
            g=c.open_sftp()
            for relative in ['usr/bin/ki2ctl','usr/libexec/ki2-kernel-recovery']:
                g.put(str(self.repo/'distro/sources/ki2ctl'/relative),remote+'/'+relative);g.chmod(remote+'/'+relative,0o755)
            key_file=folder/'candidate.pub';sftp.get(base+'/snapshots/'+row['snapshot']+'/candidate.pub',str(key_file));g.put(str(key_file),remote+'/verify.pub')
            if sha(key_file)!=self.config['repository_key_sha256']:raise ValueError('candidate repository signing key changed')
            # Modify an actually package-owned configuration, not an unrelated temporary file.
            original_config=self.run(c,"python3 -c "+shlex.quote("import base64;print(base64.b64encode(open('/etc/profile','rb').read()).decode())"),root=True).strip()
            token='# KIKI update preservation probe '+nonce+'\n'
            self.run(c,"python3 -c "+shlex.quote("from pathlib import Path;p=Path('/etc/profile');p.write_bytes(p.read_bytes()+"+repr(token.encode())+")"),root=True)
            config_before=self.run(c,'sha256sum /etc/profile',root=True).split()[0]
            # Bootstrap only a service override in /etc for an OS predating offline update support.
            unit='/etc/systemd/system/ki2-offline-update.service'
            existing=self.run(c,'cat '+unit+' 2>/dev/null || true')
            if 'Description=KIKI frozen update bootstrap' in existing:report['bootstrap_service']=True
            packaged=self.run(c,'test -f /usr/lib/systemd/system/ki2-offline-update.service && echo yes || echo no').strip()=='yes'
            if not packaged and self.run(c,'test -e '+unit+' && echo yes || echo no').strip()=='no':
                text='[Unit]\nDescription=KIKI frozen update bootstrap\nDefaultDependencies=no\nRequires=sysinit.target\nAfter=sysinit.target system-update-pre.target\nBefore=system-update.target\nFailureAction=reboot\nSuccessAction=reboot\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /var/lib/ki2/offline-update/ki2ctl offline-apply\nTimeoutStartSec=1h\n'
                self.run(c,"python3 -c "+shlex.quote("from pathlib import Path;Path('"+unit+"').write_text("+repr(text)+")"),root=True)
                report['bootstrap_service']=True
                self.run(c,'systemctl daemon-reload',root=True)
            repo=self.config['public_url']+'/ki2/versions/updates-testing/'+row['snapshot']
            # Older images have the trusted CA bundle but lack OpenSSL's compatibility link.
            # Use that installed bundle for the first update; normal boot must fix the default path.
            runner='/usr/bin/ki2ctl' if packaged else remote+'/usr/bin/ki2ctl'
            report['runner_scope']='installed updater' if packaged else 'bootstrap for image predating offline updates'
            output=self.run(c,'SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt python3 '+shlex.quote(runner)+' --repo '+shlex.quote(repo)+' offline-stage --verify-key '+shlex.quote(remote+'/verify.pub')+' '+' '.join(shlex.quote(n) for n in row['rebuild']),root=True,timeout=300)
            report['stage_output']=output[-2000:]
            progress('signed-update-staged')
            report['checks']['signature_verified']=row['index_sha256'] in output
            # Stage and run at boot with GDM stopped by system-update.target, then return to a normal boot.
            old=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
            try:self.run(c,'systemctl reboot',root=True,timeout=15)
            except (EOFError,OSError):pass
            c.close();c=None
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                try:
                    c,boot=self.wait_guest(old,timeout=35)
                    if self.run(c,'test -e /system-update && echo pending || echo ready').strip()=='ready':break
                    c.close();c=None
                except Exception:pass
                time.sleep(3)
            if not c:raise RuntimeError('offline update did not finish')
            completion="import json;from pathlib import Path;rows=[json.loads(p.read_text()) for p in Path('/var/lib/ki2').glob('offline-completed-*/result.json')];assert any(r.get('passed') is True and r.get('index_sha256')=="+repr(row['index_sha256'])+" for r in rows);print('OFFLINE_APPLY_SUCCEEDED')"
            report['checks']['offline_apply_succeeded']='OFFLINE_APPLY_SUCCEEDED' in self.run(c,'python3 -c '+shlex.quote(completion),root=True)
            progress('offline-apply-finished')
            report['boot_id_after']=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
            report['checks']['rebooted']=report['boot_id_after']!=report['boot_id_before']
            after=json.loads(self.run(c,"python3 -c "+shlex.quote("import json;d=json.load(open('/var/lib/ki2/installed.json'));print(json.dumps({n:r['sha256'] for n,r in d['packages'].items()}))")))
            needed=set(row['rebuild'])
            while True:
                deps={d for n in needed for d in catalog[n].get('dependencies',{}).get('runtime',[])}
                if deps<=needed:break
                needed|=deps
            expected={n:candidate['packages'][n] for n in set(before)|needed}
            report['packages']=after;report['checks']['package_inventory']=after==expected
            if 'acl' in row['rebuild']:
                smoke="import os,subprocess,tempfile;fd,path=tempfile.mkstemp(prefix='ki2-acl-',dir='/var/tmp');os.close(fd)\ntry:\n subprocess.run(['setfacl','-m','u:65534:r',path],check=True);text=subprocess.check_output(['getfacl','-ncp',path],text=True);assert 'user:65534:r--' in text;print('ACL_SET_AND_READ_PASSED')\nfinally:os.unlink(path)"
                result=self.run(c,'python3 -c '+shlex.quote(smoke),root=True)
                report['checks']['acl_runtime']='ACL_SET_AND_READ_PASSED' in result
            report['checks']['user_config_preserved']=self.run(c,'sha256sum /etc/profile',root=True).split()[0]==config_before
            tls="import ssl,urllib.request;assert ssl.create_default_context().cert_store_stats()['x509_ca']>0;urllib.request.urlopen("+repr(repo+'/repo/metadata.x86_64.json')+",timeout=30).read(1);print('DEFAULT_TLS_TRUST_PASSED')"
            report['checks']['default_tls_trust']='DEFAULT_TLS_TRUST_PASSED' in self.run(c,'python3 -c '+shlex.quote(tls))
            report['failed_after']=self.run(c,'systemctl --failed --no-legend --plain').strip()
            report['checks']['services_healthy']=not (set(report['failed_after'].splitlines())-set(report['failed_before'].splitlines()))
            recovery=json.loads(self.run(c,'python3 /usr/libexec/ki2-kernel-recovery check',root=True))
            self.run(c,'python3 /usr/libexec/ki2-kernel-recovery select-recovery',root=True)
            progress('booting-recovery-kernel')
            c,fallback_boot=self.reboot(c)
            cmdline=self.run(c,'cat /proc/cmdline').strip()
            report['recovery_cmdline']=cmdline
            self.run(c,'python3 /usr/libexec/ki2-kernel-recovery select-primary',root=True)
            progress('returning-to-primary-kernel')
            c,primary_boot=self.reboot(c)
            report['checks']['kernel_recovery']='kiki.recovery='+recovery['id'] in cmdline and fallback_boot!=primary_boot
            # SSH becomes available before the graphical login screen has finished starting.
            deadline=time.monotonic()+120;wayland=''
            while time.monotonic()<deadline:
                try:
                    self.run(c,'systemctl is-active gdm',root=True)
                    shell="from pathlib import Path;found=[]\nfor p in Path('/proc').iterdir():\n if not p.name.isdigit():continue\n try:\n  if (p/'exe').resolve().name=='gnome-shell':found.append(p.name)\n except OSError:pass\nassert found;print(','.join(found))"
                    self.run(c,'python3 -c '+shlex.quote(shell),root=True)
                    wayland=self.run(c,'find /run/user -maxdepth 2 -type s -name "wayland-*"',root=True)
                    if wayland.strip():break
                except RuntimeError:pass
                time.sleep(3)
            report['checks']['gnome_session']=bool(wayland.strip())
            report['gui_scope']='GNOME Wayland login greeter after update and recovery boots; interactive user authentication is not automated'
            report['kernel_after']=self.run(c,'uname -r').strip()
            if row.get('security_policy'):
                report['security']['after']=self.security_scan(c,row['security_policy'])
                report['checks']['security_scan_executed']=True
            report['boot_id_after']=self.run(c,'cat /proc/sys/kernel/random/boot_id').strip()
            if 'linux' in row['rebuild']:
                expected_kernel=next(r['version'] for r in row['recipes'] if r['name']=='linux')
                report['checks']['updated_kernel']=expected_kernel in report['kernel_after']
        except Exception as error:
            report['error']=str(error);report['traceback']=traceback.format_exc()[-6000:]
        finally:
            if c:
                try:
                    if original_config is not None:
                        self.run(c,"python3 -c "+shlex.quote("import base64;from pathlib import Path;Path('/etc/profile').write_bytes(base64.b64decode("+repr(original_config)+"))"),root=True)
                    if report.get('bootstrap_service'):
                        self.run(c,'if test -f /usr/lib/systemd/system/ki2-offline-update.service; then unlink /etc/systemd/system/ki2-offline-update.service; systemctl daemon-reload; systemctl reenable ki2-offline-update.service; fi',root=True)
                except Exception as error:report['cleanup_error']=str(error)
                c.close()
            report['finished_at']=stamp();path=folder/'report.json';path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            from cryptography.hazmat.primitives import serialization
            key=serialization.load_pem_private_key(Path(self.config['sign_key']).read_bytes(),password=None)
            signature=folder/'report.sig';signature.write_bytes(key.sign(path.read_bytes()))
            sftp.put(str(path),base+'/updates/evidence/'+nonce+'.json');sftp.put(str(signature),base+'/updates/evidence/'+nonce+'.sig')
        print(json.dumps({'proposal':row['id'],'nonce':nonce,'checks':report['checks'],'error':report.get('error'),'report':str(path)}),flush=True)
        return report

    def once(self):
        server=self.server();sftp=server.open_sftp();base=self.config['server_store']
        try:
            for name in sftp.listdir(base+'/updates/proposals'):
                if not name.endswith('.json'):continue
                with sftp.open(base+'/updates/proposals/'+name) as f:row=json.load(f)
                if row['status']!='testing' or not row.get('validation_nonce'):continue
                try:sftp.stat(base+'/updates/evidence/'+row['validation_nonce']+'.sig');continue
                except FileNotFoundError:pass
                report=self.validate(server,sftp,row)
                if report.get('error') or report.get('cleanup_error') or not report.get('checks') or not all(v is True for v in report['checks'].values()):return False
            return True
        finally:sftp.close();server.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--probe',action='store_true')
    a=p.parse_args();validator=Validator(json.loads(a.config.read_text(encoding='utf-8-sig')))
    # Task Scheduler ignores overlapping runs; this lock also protects manual invocations.
    lock=(validator.out/'validator.lock').open('a+b')
    if os.name=='nt':
        import msvcrt
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    if a.probe:print(json.dumps(validator.inspect(),indent=2))
    else:raise SystemExit(0 if validator.once() else 1)
