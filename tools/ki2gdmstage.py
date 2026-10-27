#!/usr/bin/env python3
"""Package real password authentication and GDM/systemd integration for the candidate."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import ki2sessioncandidate as c

dest=c.WORK/'gdm-integration-v5'
dest.mkdir(exist_ok=True)
files={
 'usr/lib/systemd/system/gdm.service.d/10-kiki-runtime.conf':'''[Service]
ExecStartPre=/usr/libexec/kiki-desktop-prepare
''',
 'usr/libexec/kiki-desktop-prepare':'''#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH
systemd-machine-id-setup
systemd-sysusers
systemd-tmpfiles --create
ldconfig
glib-compile-schemas /usr/share/glib-2.0/schemas
gio-querymodules /usr/lib/gio/modules
update-mime-database /usr/share/mime
gdk-pixbuf-query-loaders --update-cache
gtk4-update-icon-cache -t /usr/share/icons/hicolor
fc-cache
''',
 'etc/pam.d/gdm-password':'''#%PAM-1.0
auth requisite pam_nologin.so
auth requisite pam_succeed_if.so user != root quiet
auth include common-auth
account include common-account
password include common-password
session required pam_loginuid.so
session required pam_unix.so
session optional pam_keyinit.so force revoke
session required pam_limits.so
session optional pam_env.so
session required pam_systemd.so
''',
 'etc/pam.d/gdm-launch-environment':'''#%PAM-1.0
# Only the locked system greeter account may use this internal service.
auth requisite pam_succeed_if.so user = gdm-greeter quiet
auth required pam_permit.so
account required pam_succeed_if.so user = gdm-greeter quiet
password required pam_deny.so
session required pam_loginuid.so
session optional pam_keyinit.so force revoke
session required pam_limits.so
session optional pam_env.so
session required pam_systemd.so
''',
 'etc/pam.d/gdm-autologin':'''#%PAM-1.0
auth requisite pam_deny.so
account required pam_deny.so
session required pam_deny.so
''',
 'etc/gdm/custom.conf':'''# KIKI candidate: real local-password login through GDM and Wayland.
[daemon]
WaylandEnable=true
AutomaticLoginEnable=false
TimedLoginEnable=false
[security]
DisallowTCP=true
''',
 'usr/lib/sysusers.d/kiki-gdm.conf':'''u gdm - "GNOME Display Manager" /var/lib/gdm /usr/sbin/nologin
u gdm-greeter - "GNOME Login Screen" /run/gdm/home/gdm-greeter /usr/sbin/nologin
m gdm-greeter gdm
''',
 'usr/lib/tmpfiles.d/kiki-gdm.conf':'''d /var/lib/gdm 0750 gdm gdm -
d /var/cache/gdm 0750 gdm gdm -
d /var/log/gdm 0750 gdm gdm -
''',
 'etc/polkit-1/rules.d/49-kiki-admin.rules':'''// Select administrators; each privileged action still requires its policy.
polkit.addAdminRule(function(action, subject) {
    return ["unix-group:sudo"];
});
''',
}
for name,text in files.items():
 p=dest/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(text);p.chmod(0o755 if name=='usr/libexec/kiki-desktop-prepare' else 0o644)
raw=dict(name='kiki-gdm-integration',version='0.1.0',release='5',summary='KIKI GDM Wayland password-login integration',license='GPL-3.0-or-later',tier='desktop',architectures=['x86_64'],
         source=dict(type='local',path=str(dest)),dependencies=dict(build=[],runtime=['gdm','kiki-pam-config','polkit','systemd','shadow','glibc-locales','glib','glib-networking','gdk-pixbuf','librsvg','shared-mime-info','gtk','fontconfig']),build=dict(system='copy'))
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(password_required=True,root_graphical_login=False,autologin=False,polkit_admin_group='sudo',user_creation='systemd-sysusers'))
print('Packaged KIKI GDM integration')
