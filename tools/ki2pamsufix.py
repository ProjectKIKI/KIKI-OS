#!/usr/bin/env python3
"""Supply a missing PAM include while preserving every existing auth restriction."""
import contextlib
import io
import json
import re
from pathlib import Path
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

name='kiki-pam-config';r=json.loads((c.TARGET/'validation'/(name+'-build.json')).read_text())
if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed PAM policy archive')
m=read_manifest(r['file']);raw=tomli.loads((c.TARGET/'recipes'/(name+'.toml')).read_text())['recipe'][0]
raw['release']=str(int(m['release'])+1)
dest=c.WORK/'pam-common-policy-repaired';c.build.extract_package_rootfs(Path(r['file']),dest)
su_before=c.sha256_file(dest/'etc/pam.d/su')
if not re.search(r'^auth\s+required\s+pam_wheel\.so\s+use_uid\s*$',(dest/'etc/pam.d/su').read_text(),re.M):raise ValueError('Existing wheel restriction not found')
policies={
'system-auth':'''#%PAM-1.0
# Compatibility for preserved native tools that reference system-auth.
auth include common-auth
account include common-account
password include common-password
session include common-session
''',
}
for filename,text in policies.items():p=dest/'etc/pam.d'/filename;p.write_text(text);p.chmod(0o644)
if c.sha256_file(dest/'etc/pam.d/su')!=su_before:raise ValueError('Existing su policy changed')
c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],common_policy_integration=list(policies),root_account_remains_locked=True,password_auth_unchanged=True,su_policy_sha256=su_before,wheel_restriction_preserved=True))
print('Packaged missing system-auth include; existing su/wheel policy byte-identical',flush=True)
