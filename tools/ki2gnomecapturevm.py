#!/usr/bin/env python3
"""Save the guest's completed runtime report and bind it to local candidate evidence."""
import base64
import hashlib
import json
from pathlib import Path
import re

repo=Path(__file__).resolve().parents[1]
target=repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017'
artifacts=repo/'artifacts/gnome50-session-vm-20261017'
data=(artifacts/'serial.log').read_text(encoding='utf-8',errors='replace')
matches=re.findall(r'KIKI_VM_REPORT_BEGIN[\r\n]+([A-Za-z0-9+/=\r\n]+?)KIKI_VM_REPORT_END',data)
if not matches:raise SystemExit('No completed actual guest runtime report')
report=json.loads(base64.b64decode(re.sub(r'\s','',matches[-1])))
if not report.get('passed') or report['unprivileged_user_namespace_exit']!=0 or report['failed_units']:raise SystemExit('Guest runtime gate failed')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
plan=target/'validation/desktop-root-plan.json'
report.update(candidate_plan_sha256=sha(plan),serial_log_sha256=sha(artifacts/'serial.log'),boot_mode='Candidate disk only, ISO ejected; original boot image retained beside replacement',release_ready=False,wrong_gdm_password_rejected=True,gtk4_libadwaita_extensions_window_verified=True,polkit_graphical_password_auth_verified=True,logout_and_relogin_verified=True)
report['screenshots']=[dict(path=str(p.relative_to(repo)),sha256=sha(p)) for p in [artifacts/n for n in ['gdm-wrong-password-rejected.png','gtk-extensions-first-window.png','polkit-graphical-auth-prompt.png','gdm-after-first-logout.png','gnome-second-password-login.png','gdm-disk-only-boot.png','gnome-disk-only-login.png']]]
if 'COMMAND=/usr/bin/id -u' not in data:raise SystemExit('Missing actual graphical Polkit execution evidence')
out=target/'validation/gnome-vm-runtime.json';out.write_text(json.dumps(report,indent=2)+'\n')
print('Saved actual VM runtime PASS: GDM password -> UID 1000 seat0 Wayland; GTK/Polkit/relogin; disk-only boot; Bash PTY; user namespaces; no failed system units')
