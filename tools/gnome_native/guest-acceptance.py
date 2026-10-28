import json
import hashlib
import os
from pathlib import Path
import pwd
import subprocess
import shutil

def run(*args):
    args=list(args)
    if args[0].startswith('/') and not Path(args[0]).exists():args[0]=shutil.which(Path(args[0]).name) or args[0]
    result=subprocess.run(list(args),text=True,capture_output=True,timeout=30)
    return dict(code=result.returncode,stdout=result.stdout.strip(),stderr=result.stderr.strip())

user=pwd.getpwnam('kiki')
runtime='/run/user/'+str(user.pw_uid)
user_env=['/usr/bin/sudo','-u','kiki','/usr/bin/env','XDG_RUNTIME_DIR='+runtime,
          'DBUS_SESSION_BUS_ADDRESS=unix:path='+runtime+'/bus','WAYLAND_DISPLAY=wayland-0','XDG_SESSION_TYPE=wayland','LANG=ko_KR.UTF-8']
services=['gdm.service','NetworkManager.service','systemd-resolved.service','sshd.service','dbus.service']
user_services=['org.gnome.SettingsDaemon.'+n+'.service' for n in ['Keyboard','A11ySettings','Power','Datetime','Housekeeping','ScreensaverProxy','Rfkill']]
checks={name:run('/usr/bin/systemctl','is-active',name) for name in services}
user_checks={name:run(*user_env,'/usr/bin/systemctl','--user','is-active',name) for name in user_services}
sessions=run('/usr/bin/loginctl','list-sessions','--no-legend')
session_details=[]
for line in sessions['stdout'].splitlines():
    fields=line.split()
    if 'kiki' in fields:session_details.append(run('/usr/bin/loginctl','show-session',fields[0],'-p','Type','-p','State','-p','Class'))
installed=json.loads(Path('/var/lib/ki2/installed.json').read_text())
shadow=next(line.split(':')[1] for line in Path('/etc/shadow').read_text().splitlines() if line.startswith('root:'))
system_failed=run('/usr/bin/systemctl','--failed','--no-legend','--plain')
user_failed=run(*user_env,'/usr/bin/systemctl','--user','--failed','--no-legend','--plain')
report=dict(
    uid=os.getuid(),uname=run('/bin/uname','-r'),hostname=run('/bin/hostname'),
    root=run('/usr/bin/findmnt','-no','SOURCE,FSTYPE','/'),
    default_target=run('/usr/bin/systemctl','get-default'),
    display_manager=os.readlink('/etc/systemd/system/display-manager.service'),
    root_locked=shadow.startswith(('!','*')),services=checks,user_services=user_checks,
    system_failed=system_failed,user_failed=user_failed,sessions=session_details,
    tty1_enabled=run('/usr/bin/systemctl','is-enabled','getty@tty1.service'),
    tty2_enabled=run('/usr/bin/systemctl','is-enabled','getty@tty2.service'),
    network=run('/usr/bin/ip','-4','-o','addr','show'),
    https=run('/usr/bin/curl','-I','--max-time','20','https://example.com'),
    locale=Path('/etc/locale.conf').read_text(),timezone=os.readlink('/etc/localtime'),
    ibus_engines=run(*user_env,'/usr/bin/ibus','list-engine'),
    input_sources=run(*user_env,'/usr/bin/gsettings','get','org.gnome.desktop.input-sources','sources'),
    appearance=run(*user_env,'/usr/bin/gsettings','get','org.gnome.desktop.interface','color-scheme'),
    installed_packages={n:dict(version=r['version'],release=r['release']) for n,r in installed['packages'].items()},
    installed_package_count=len(installed['packages']),
    install_plan=Path('/var/lib/ki2/install-plan.yaml').read_text(),
    boot_errors=run('/usr/bin/journalctl','-b','-p','err','--no-pager','-n','35'),
    user_namespace=run('/usr/bin/unshare','-Ur','/usr/bin/id','-u'),
    upower_sandbox=run('/usr/bin/systemctl','show','upower.service','-p','PrivateUsers','-p','RestrictNamespaces','-p','NoNewPrivileges','-p','CapabilityBoundingSet'),
    upower=run('/usr/bin/systemctl','is-active','upower.service'),
    upower_unit_sha256=hashlib.sha256(Path('/usr/lib/systemd/system/upower.service').read_bytes()).hexdigest(),
    upower_overrides=run('/usr/bin/systemctl','show','upower.service','-p','DropInPaths'),
    terminal_shell=run(*user_env,'/usr/bin/gsettings','get','org.gnome.Console','shell'),
    directory_handler=run(*user_env,'/usr/bin/gio','mime','inode/directory'),
    networkd=run('/usr/bin/systemctl','is-enabled','systemd-networkd.service','systemd-networkd.socket'),
    nm_connections=run('/usr/bin/nmcli','-f','NAME,TYPE,DEVICE','connection','show','--active'),
    app_versions={n:run(*user_env,'/usr/bin/'+n,'--version') for n in ['gnome-control-center','nautilus','kgx']},
    portal_theme=run(*user_env,'/usr/bin/gdbus','call','--session','--timeout','15','--dest','org.freedesktop.portal.Desktop','--object-path','/org/freedesktop/portal/desktop','--method','org.freedesktop.portal.Settings.Read','org.freedesktop.appearance','color-scheme'),
    fuse_device=Path('/dev/fuse').is_char_device(),
    document_portal=run(*user_env,'/usr/bin/gdbus','call','--session','--timeout','15','--dest','org.freedesktop.portal.Documents','--object-path','/org/freedesktop/portal/documents','--method','org.freedesktop.portal.Documents.GetMountPoint'),
    fuse_control=run('/usr/bin/findmnt','-n','-o','FSTYPE','/sys/fs/fuse/connections'),
    gui_folder=Path(user.pw_dir,'gui-renamed').is_dir(),
    gui_trash_copy=Path(user.pw_dir,'.local/share/Trash/files/gui-renamed (사본)').is_dir(),
    gui_hangul=Path(user.pw_dir,'native-hangul.txt').read_text().strip() if Path(user.pw_dir,'native-hangul.txt').exists() else '',
    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
)
report['checks']=dict(
    root_privilege=report['uid']==0,graphical_boot=report['default_target']['stdout']=='graphical.target',
    root_locked=report['root_locked'],all_system_services_active=all(r['stdout']=='active' for r in checks.values()),
    all_selected_gsd_plugins_active=all(r['stdout']=='active' for r in user_checks.values()),
    system_failed_units_empty=not system_failed['stdout'],user_failed_units_empty=not user_failed['stdout'],
    wayland_login=any('Type=wayland' in r['stdout'] and 'State=active' in r['stdout'] for r in session_details),
    hangul_engine_registered='hangul' in report['ibus_engines']['stdout'],
    hangul_source_configured='hangul' in report['input_sources']['stdout'],
    recovery_console_enabled=report['tty2_enabled']['stdout']=='enabled',
    desktop_apps_installed=all(n in installed['packages'] for n in ['gnome-control-center','nautilus','gnome-console','NetworkManager','ibus-hangul','gnome-settings-daemon']),
    target_is_virtual_disk='/dev/sda' in report['root']['stdout'],
    https_reachable=report['https']['code']==0,
    installed_database_recorded=Path('/var/lib/ki2/installed.json').is_file(),
    user_namespaces_work=report['user_namespace']['code']==0,
    upower_active=report['upower']['stdout']=='active',
    upower_sandbox_preserved='PrivateUsers=yes' in report['upower_sandbox']['stdout'] and 'RestrictNamespaces=yes' in report['upower_sandbox']['stdout'] and report['upower_overrides']['stdout']=='DropInPaths=',
    terminal_uses_bash=report['terminal_shell']['stdout']=="['/bin/bash', '--login']",
    directory_handler_is_nautilus='org.gnome.Nautilus.desktop' in report['directory_handler']['stdout'],
    networkd_disabled=report['networkd']['stdout'].splitlines()==['disabled','disabled'],
    portal_theme_available=report['portal_theme']['code']==0,
    fuse_available=report['fuse_device'],
    native_apps_run=all(v['code']==0 for v in report['app_versions'].values()),
    document_portal_mounted=report['document_portal']['code']==0 and report['fuse_control']['stdout']=='fusectl',
    gui_file_operations_recorded=report['gui_folder'] and report['gui_trash_copy'],
    gui_hangul_saved=report['gui_hangul']=='한글',
    plan_uses_networkmanager='manager: "NetworkManager"' in report['install_plan'] and 'NetworkManager.service' in report['install_plan'],
)
report['status']='passed' if all(report['checks'].values()) else 'failed'
Path('/tmp/kiki-desktop-guest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(status=report['status'],checks=report['checks'],system_failed=system_failed,user_failed=user_failed),indent=2),flush=True)
