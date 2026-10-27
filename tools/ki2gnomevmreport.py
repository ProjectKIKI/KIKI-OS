#!/usr/bin/python3
"""Collect actual candidate VM session evidence without passwords or identity hashes."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import pwd
import select
import subprocess
import termios
import time

if os.geteuid()!=0 or os.uname().nodename!='kiki-lab' or Path('/sys/class/block/sda/size').read_text().strip()!='67108864':raise SystemExit('Disposable candidate VM only')
def run(args,check=True):return subprocess.run(args,check=check,capture_output=True,text=True).stdout.strip()
sessions=[]
for line in run(['loginctl','list-sessions','--no-legend','--no-pager']).splitlines():
    sid=line.split()[0]
    values=run(['loginctl','show-session',sid,'-p','Id','-p','User','-p','Name','-p','Type','-p','Seat','-p','Active','-p','Class','-p','Service','-p','Remote'])
    sessions.append(dict(line.split('=',1) for line in values.splitlines()))
graphical=[s for s in sessions if s.get('User')=='1000' and s.get('Type')=='wayland' and s.get('Seat')=='seat0' and s.get('Active')=='yes' and s.get('Service')=='gdm-password' and s.get('Remote')=='no']
if not graphical:raise SystemExit('No actual local GDM password-authenticated user Wayland session')
services={n:run(['systemctl','is-active',n]) for n in ['gdm','dbus','systemd-logind','polkit','upower','user@1000.service']}
userenv=['sudo','-u','kiki','env','XDG_RUNTIME_DIR=/run/user/1000','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus']
bus=run(userenv+['busctl','--user','call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetId'])
namespace=subprocess.run(['sudo','-u','kiki','/usr/bin/unshare','-Ur','/usr/bin/true'],capture_output=True,text=True)
if namespace.returncode:raise SystemExit('Unprivileged user namespace failed: '+namespace.stderr)
master,slave=pty.openpty()
def child():
    os.setsid();fcntl.ioctl(0,termios.TIOCSCTTY,0)
    account=pwd.getpwnam('kiki')
    os.initgroups('kiki',account.pw_gid);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',HOME='/home/kiki',TERM='xterm',LC_ALL='__KIKI_INVALID_UTF8__',HISTFILE='/dev/null',PS1='BASH_PROBE> ')
p=subprocess.Popen(['/usr/bin/bash','--noprofile','--norc','-i'],stdin=slave,stdout=slave,stderr=slave,env=env,preexec_fn=child)
os.close(slave);time.sleep(.2)
os.write(master,b"printf 'BASH_VM_INVALID_LOCALE_OK\\n'\n")
time.sleep(.2);os.write(master,b'\x1b[A\nexit 0\n')
data=bytearray();deadline=time.monotonic()+8
while time.monotonic()<deadline:
    if select.select([master],[],[],.2)[0]:
        try:data.extend(os.read(master,65536))
        except OSError:break
    if p.poll() is not None:break
os.close(master)
try:status=p.wait(timeout=1)
except subprocess.TimeoutExpired:p.kill();raise SystemExit('Bash PTY test timed out')
text=data.decode(errors='replace')
if status or text.count('BASH_VM_INVALID_LOCALE_OK')<2:raise SystemExit('Bash invalid-locale/history regression failed')
failed=run(['systemctl','--failed','--no-legend','--no-pager'])
if failed:raise SystemExit('Failed system units: '+failed)
policy=Path('/etc/pam.d/su').read_bytes()
if b'pam_wheel.so use_uid' not in policy:raise SystemExit('Original su wheel restriction missing')
report=dict(passed=True,scope='Actual installed candidate Hyper-V guest; not fresh installer validation',kernel=os.uname().release,graphical_sessions=graphical,sessions=sessions,services=services,user_dbus_reply=bus,unprivileged_user_namespace_exit=namespace.returncode,bash_invalid_locale_history_pty=dict(passed=True,exit_code=status,output=text),failed_units=[],su_wheel_restriction_preserved=True,su_policy_sha256=hashlib.sha256(policy).hexdigest(),boot_time=run(['systemd-analyze','time']),autologin=False)
if os.environ.get('KIKI_FRESH_INSTALL_REPORT')=='1':
    installed=Path('/var/lib/ki2/installed.list').read_text().splitlines()
    if len(installed)!=179 or 'kiki-gnome-desktop' not in installed or 'socat' not in installed:
        raise SystemExit('Fresh installation package list does not match validated closure')
    if any(n in installed for n in ['kiki-installer-gtk','kiki-installer-tui','kiki-x11','kiki-kmscon']):
        raise SystemExit('Live installer bundle unexpectedly installed in desktop target')
    offline=subprocess.run(['/usr/libexec/kiki-wait-online-needed'],capture_output=True,text=True)
    if offline.returncode!=1:raise SystemExit('Fresh OFF network did not skip online wait')
    report['offline_wait_gate_exit']=offline.returncode
    shadow={line.split(':',2)[0]:line.split(':',2)[1] for line in Path('/etc/shadow').read_text().splitlines()}
    if not shadow['kiki'].startswith('$6$') or shadow['root'][:1] not in ['!','*']:
        raise SystemExit('Fresh admin SHA512 hash or locked root policy missing')
    if 'ENCRYPT_METHOD SHA512' not in Path('/etc/login.defs').read_text():
        raise SystemExit('Native Shadow hash default mismatch')
    report.update(admin_password_scheme='SHA512',root_password_locked=True)
    report.update(scope='Fresh installation from signed candidate ISO onto blank 32 GiB Hyper-V disk; ISO ejected',fresh_install_tested=True,installed_package_count=len(installed),installed_packages=installed,installed_index_sha256=hashlib.sha256(Path('/var/lib/ki2/repo-index.x86_64.json').read_bytes()).hexdigest(),locale=Path('/etc/locale.conf').read_text(),default_target=run(['systemctl','get-default']),network_online_wait=run(['systemctl','show','systemd-networkd-wait-online.service','-p','Result','-p','ConditionResult','-p','ExecMainStatus']),installer_bundle_in_target=False,socat_version=run(['/usr/bin/socat','-V']))
out=Path('/var/lib/kiki-session-lab/final-runtime.json');out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')
print('KIKI_VM_REPORT_BEGIN',flush=True)
print(base64.b64encode(json.dumps(report).encode()).decode(),flush=True)
print('KIKI_VM_REPORT_END',flush=True)
