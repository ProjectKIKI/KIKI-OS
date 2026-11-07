"""Test transport restricted to the two dedicated Paper Pixel Hyper-V clones.

Credentials and SSH trust come from the existing private GA test configuration;
they are never copied to output or placed on command lines.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--role',choices=['baseline','candidate','candidate-r4'],required=True)
    p.add_argument('--command-file',type=Path)
    p.add_argument('--put',type=Path)
    p.add_argument('--get')
    p.add_argument('--remote')
    p.add_argument('--local',type=Path)
    p.add_argument('--root',action='store_true')
    p.add_argument('--output',type=Path)
    p.add_argument('--test-password-stdin',action='store_true',help='Feed the private clone password to an explicit guest authentication test over SSH stdin; never as an argument')
    a=p.parse_args()
    if a.test_password_stdin and (not a.command_file or not a.root):
        p.error('--test-password-stdin requires an explicit root command file')
    repo=Path(__file__).resolve().parents[1]
    root=repo/'artifacts/server-shell/20261105-stage1'
    state=json.loads((root/a.role/'vm.json').read_text(encoding='utf-8-sig'))
    if state['scope']!='isolated-paper-pixel-stage1':raise SystemExit('Wrong VM scope')
    identifier=str(uuid.UUID(state['id']))
    command=(f"$v=Get-VM -Id '{identifier}';if($v.State -ne 'Running'){{throw 'VM is not running'}};"
        "if((Get-VM -Name 'kiki-build-v1-ga-hyperv-20261101').State -ne 'Off'){throw 'Source VM must remain off'};"
        "if(Get-VM -Name 'kiki-paper-pixel-*' | Where-Object {$_.Id -ne $v.Id -and $_.State -ne 'Off'}){throw 'Only one MAC-preserving pixel clone may run'};"
        "$n=Get-VMNetworkAdapter -VM $v;@{name=$v.Name;mac=$n.MacAddress;ips=@($n.IPAddresses)}|ConvertTo-Json -Compress")
    vm=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',command],text=True))
    if vm['name']!=state['name'] or vm['mac']!=state['mac']:raise SystemExit('VM identity changed')
    config=json.loads((repo/'artifacts/build-v1-ga-hyperv/guest-config.json').read_text())
    if config['guest_host'] not in vm['ips']:raise SystemExit('Pinned clone IP not observed on Hyper-V NIC')
    sys.path.insert(0,config['ssh_library'])
    import paramiko
    c=paramiko.SSHClient();c.load_host_keys(config['guest_known_hosts']);c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(config['guest_host'],username=config['guest_user'],password=config['guest_password'],
        look_for_keys=False,allow_agent=False,timeout=15)
    try:
        if a.put:
            if not a.remote or not a.remote.startswith('/tmp/kiki-pixel/'):raise SystemExit('Uploads restricted to test staging')
            s=c.open_sftp();s.put(str(a.put),a.remote);s.close()
        if a.get:
            if not a.local:raise SystemExit('--local is required')
            a.local.parent.mkdir(parents=True,exist_ok=True)
            s=c.open_sftp();s.get(a.get,str(a.local));s.close()
        if a.command_file:
            payload=a.command_file.read_text(encoding='utf-8')
            cmd="sudo -S -p '' sh -c "+shlex.quote(payload) if a.root else payload
            stdin,stdout,stderr=c.exec_command(cmd,timeout=180)
            if a.root:stdin.write(config['guest_password']+'\n');stdin.flush()
            if a.test_password_stdin:
                stdin.write(config['guest_password']+'\n');stdin.flush()
            out,err=stdout.read().decode('utf-8','replace'),stderr.read().decode('utf-8','replace')
            # Test helpers must never echo the private credential into evidence.
            out=out.replace(config['guest_password'],'[REDACTED]')
            err=err.replace(config['guest_password'],'[REDACTED]')
            status=stdout.channel.recv_exit_status()
            if a.output:
                a.output.write_text(out,encoding='utf-8')
                print('Saved guest output:',a.output,'bytes:',len(out.encode('utf-8')))
            else:
                print(out[:12000],end='')
            print(err[:4000],end='',file=sys.stderr)
            if status:raise SystemExit(status)
    finally:c.close()


if __name__=='__main__':main()
