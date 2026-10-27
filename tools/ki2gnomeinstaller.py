#!/usr/bin/env python3
"""Prepare and build a separate GNOME candidate installer with the preserved GTK frontend."""
import datetime
import difflib
import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import ki2sessioncandidate as c
import ki2repo
from ki2stage3candidate import read_manifest

def inputs():
    dest=c.TARGET/'iso-inputs-r6'
    if dest.exists():raise FileExistsError(dest)
    shutil.copytree(c.BASE/'iso-inputs',dest,symlinks=True)
    source=c.BASE/'iso-inputs/tools/ki2bootiso.py'
    handoff_patch=c.TARGET/'inputs/boot-handoff/installed-mount-root.patch'
    subprocess.run(['patch','--batch','-p1','-d',str(dest),'-i',str(handoff_patch)],check=True)
    before=(dest/'tools/ki2bootiso.py').read_text();after=before.replace('#define MAX_SELECTED_PACKAGES 96','#define MAX_SELECTED_PACKAGES 512')
    # The native GNOME index exceeds the old 128 KiB reader (zstd is last).
    if after.count('static char package_index_buffer[128 * 1024];') != 1:
        raise ValueError('Unexpected package index reader capacity')
    after=after.replace('static char package_index_buffer[128 * 1024];',
                        'static char package_index_buffer[4 * 1024 * 1024];')
    verifier=dest/'tools/ki2media.py'
    verifier_text=verifier.read_text()
    if verifier_text.count('if len(result) > 96:')!=1:
        raise ValueError('Unexpected Python closure reader capacity')
    verifier.write_text(verifier_text.replace('if len(result) > 96:', 'if len(result) > 512:'))
    start=after.index('static void select_server_core_packages(');end=after.index('static void select_kube_profile_packages(',start)
    section=after[start:end]
    if section.count('"kiki-installer-tui"')!=1:raise ValueError('Unexpected server profile source')
    section=section.replace('"kiki-installer-tui"','"kiki-gnome-desktop"')
    after=after[:start]+section+after[end:]
    profile_guard='''    if (!selected_profile_is_kubernetes()) {
        return 1;
    }'''
    addition='''    if (kstrcmp(selected_package_profile, "server-core") == 0) {
        if (!package_exists_in_index(index_path, "kiki-gnome-desktop")) {
            say("GNOME candidate profile is missing its desktop package.\\n");
            return 0;
        }
        selected_remove("kiki-installer-tui");
        selected_add("kiki-gnome-desktop");
    }
'''
    if after.count(profile_guard)!=1:raise ValueError('Unexpected selected-profile guard')
    after=after.replace(profile_guard,addition+profile_guard)
    marker='static int enable_kubernetes_systemd_units(void) {'
    integration='''static int prepare_gnome_target(void) {
    if (!file_exists("/mnt/target/usr/lib/systemd/system/gdm.service")) return 1;
    char *argv[] = {"/usr/libexec/kiki-desktop-prepare", NULL};
    int proc_ready = mount_one("proc", "/mnt/target/proc", "proc", 0, "");
    int dev_ready = proc_ready && mount_one("", "/mnt/target/dev", "/dev", 4096, "");
    int sys_ready = dev_ready && mount_one("sysfs", "/mnt/target/sys", "sysfs", 0, "");
    int status = sys_ready ? run_chroot_program("/mnt/target", "/usr/libexec/kiki-desktop-prepare", argv) : 1;
    int cleanup_ok = 1;
    if (sys_ready && ksys(SYS_umount2, (long)"/mnt/target/sys", 0, 0, 0, 0, 0) < 0) cleanup_ok = 0;
    if (dev_ready && ksys(SYS_umount2, (long)"/mnt/target/dev", 0, 0, 0, 0, 0) < 0) cleanup_ok = 0;
    if (proc_ready && ksys(SYS_umount2, (long)"/mnt/target/proc", 0, 0, 0, 0, 0) < 0) cleanup_ok = 0;
    if (status != 0 || !cleanup_ok) {
        say("GNOME account/cache preparation failed.\\n");
        return 0;
    }
    remove_file("/mnt/target/etc/systemd/system/default.target");
    if (!required_unit_symlink("/usr/lib/systemd/system/graphical.target", "/mnt/target/etc/systemd/system/default.target")) return 0;
    if (!required_unit_symlink("/usr/lib/systemd/system/gdm.service", "/mnt/target/etc/systemd/system/display-manager.service")) return 0;
    return 1;
}

'''
    if after.count(marker)!=1:raise ValueError('Unexpected unit integration source')
    after=after.replace(marker,integration+marker)
    old='    if (!enable_default_systemd_units()) goto target_configuration_failed;'
    if after.count(old)!=1:raise ValueError('Unexpected target preparation call site')
    after=after.replace(old,old+'\n    if (!prepare_gnome_target()) goto target_configuration_failed;')
    old_chpasswd='char *argv_chpasswd[] = {"/usr/sbin/chpasswd", NULL};'
    if after.count(old_chpasswd)!=1:raise ValueError('Unexpected password setup source')
    after=after.replace(old_chpasswd,'char *argv_chpasswd[] = {"/usr/sbin/chpasswd", "-c", "SHA512", NULL};')
    account_marker='    if (run_chroot_program(target_root, "/usr/sbin/useradd", argv_useradd) != 0) {'
    policy='''    char *argv_password_policy[] = {"/bin/sh", "-c",
        "set -eu; sed -i 's/^ENCRYPT_METHOD[[:space:]].*/ENCRYPT_METHOD SHA512/' /etc/login.defs; grep -qx 'ENCRYPT_METHOD SHA512' /etc/login.defs", NULL};
    if (run_chroot_program(target_root, "/bin/sh", argv_password_policy) != 0) {
        say("Native password hashing policy preparation failed.\\n");
        return 0;
    }
'''
    if after.count(account_marker)!=1:raise ValueError('Unexpected native account setup source')
    after=after.replace(account_marker,policy+account_marker)
    (dest/'tools/ki2bootiso.py').write_text(after)
    patch=c.TARGET/'inputs/boot-handoff/gnome-candidate-installer-r6.patch'
    patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/tools/ki2bootiso.py',tofile='b/tools/ki2bootiso.py')))
    c.save(c.TARGET/'validation/installer-candidate-inputs.json',dict(parent_input_root=str(c.BASE/'iso-inputs'),validated_parent_builder_sha256=c.sha256_file(source),handoff_patch_sha256=c.sha256_file(handoff_patch),candidate_boot_builder_sha256=c.sha256_file(dest/'tools/ki2bootiso.py'),candidate_patch_sha256=c.sha256_file(patch),candidate_media_verifier_sha256=c.sha256_file(verifier),frontend='Preserved kiki-installer-gtk r19 package, binary and bundled runtime unchanged',profile='server-core adds minimal GNOME desktop, AI off for validation',max_resolved_packages=512,index_reader_bytes=4194304))
    print('Prepared separate installer inputs; original GTK frontend/runtime preserved',flush=True)

def publish():
    runtime=json.loads((c.TARGET/'validation/gnome-vm-runtime.json').read_text())
    clean=json.loads((c.TARGET/'validation/desktop-clean-runtime.json').read_text())
    audit=json.loads((c.TARGET/'validation/desktop-root-elf-suppliers.json').read_text())
    plan=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
    if not runtime.get('passed') or not clean.get('passed') or audit['errors'] or any(audit['runtime_additions'].values()) or plan['errors'] or plan['conflicts']:raise ValueError('Runtime/closure gate not passed')
    if runtime.get('candidate_plan_sha256')!=c.sha256_file(c.TARGET/'validation/desktop-root-plan.json'):raise ValueError('Candidate plan changed since actual VM report')
    audited={r['name']:r['sha256'] for r in audit['packages']}
    for r in plan['packages']:
        if audited.get(r['name'])!=r['sha256']:raise ValueError('Stale closure audit: '+r['name'])
    records=list(plan['packages'])
    original=json.loads((c.BASE/'snapshot.json').read_text())['packages']
    for name in ['kiki-installer-gtk','kiki-installer-tui']:
        r=next(x for x in original if x['name']==name)
        records.append(dict(r,file=str(c.BASE/'packages/x86_64'/r['file'])))
    packages=c.TARGET/'packages/x86_64';packages.mkdir(exist_ok=False,parents=True)
    entries=[]
    for r in records:
        path=Path(r['file'])
        if c.sha256_file(path)!=r['sha256']:raise ValueError('Changed validated archive')
        target=packages/path.name;shutil.copy2(path,target)
        if c.sha256_file(target)!=r['sha256']:raise ValueError('Package copy changed')
        entries.append(ki2repo.package_entry(target,read_manifest(target)))
    repo=c.TARGET/'repo';repo.mkdir(exist_ok=False)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    index=ki2repo.build_index(sorted(entries,key=lambda x:x['name']),'x86_64',now)
    # Preserve ki2repo's wire format: the static installer expects file before name.
    ki2repo.write_json(repo/'index.x86_64.json',index)
    release=c.TARGET/'release-iso';release.mkdir(exist_ok=True)
    metadata=ki2repo.build_metadata(name='kiki-gnome50-candidate',title='KIKI GNOME 50 login candidate',description='Runtime-validated minimal GNOME 50/GDM/Wayland candidate; preserved installer frontend; not a production release',channel='candidate',arch='x86_64',base_url='',created_at=now,repo_dir=repo,packages_dir=packages,iso_dir=release,packages=entries)
    c.save(repo/'metadata.x86_64.json',metadata)
    keys=c.WORK/'candidate-keys';keys.mkdir(exist_ok=True)
    key=keys/'gnome50-candidate.ed25519'
    if not key.exists():subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],check=True);key.chmod(0o600)
    public=c.TARGET/'build-tools/gnome50-candidate.ed25519.pub';public.parent.mkdir(exist_ok=True)
    subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True)
    ki2repo.sign_metadata_file(repo/'metadata.x86_64.json',key)
    if not ki2repo.verify_metadata_file(repo/'metadata.x86_64.json',public):raise ValueError('Candidate signature verification failed')
    c.save(c.TARGET/'gate.json',dict(candidate_runtime_passed=True,release_ready=False,package_count=len(entries),index_sha256=c.sha256_file(repo/'index.x86_64.json'),metadata_sha256=c.sha256_file(repo/'metadata.x86_64.json'),signature='Ed25519 candidate-only key',public_key_sha256=c.sha256_file(public),fresh_install_tested=False,gtk_frontend_preserved=True))
    print('Published separately signed validated candidate index:',len(entries),'packages',flush=True)

def build():
    out=c.TARGET/'release-iso/kiki-6.1.187-gnome50-login-candidate-r6.iso'
    if out.exists():raise FileExistsError(out)
    tree=c.WORK/'gnome-installer-tree-r6'
    empty=c.WORK/'installer-empty-root';empty.mkdir(exist_ok=True)
    verifier=c.TARGET/'iso-inputs-r6/tools/ki2media.py'
    spec=importlib.util.spec_from_file_location('candidate_media_verifier',verifier)
    media=importlib.util.module_from_spec(spec);spec.loader.exec_module(media)
    index=json.loads((c.TARGET/'install-repo-r3/index.x86_64.json').read_text())
    plan=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
    resolved=media.runtime_closure(index,plan['roots']+['socat'])
    if set(resolved)!=set(plan['order'])|{'socat'}:raise ValueError('Installer closure differs from validated core plus socat')
    index_bytes=(c.TARGET/'install-repo-r3/index.x86_64.json').stat().st_size
    if index_bytes>=4*1024*1024:raise ValueError('Installer index reader capacity exceeded')
    c.save(c.TARGET/'validation/installer-selection-capacity.json',dict(passed=True,index_bytes=index_bytes,index_capacity=4*1024*1024,resolved_packages=len(resolved),closure_capacity=512,exact_validated_closure=True))
    command=[str(c.VENV/'bin/python'),'-B',str(c.TARGET/'iso-inputs/tools/ki2bootiso.py'),'build','--repo-root',str(c.TARGET/'iso-inputs'),'--repo-dir',str(c.TARGET/'install-repo-r3'),'--packages-dir',str(c.TARGET/'install-packages-r2/x86_64'),'--rootfs-dir',str(c.WORK/'native-desktop-root-v2'),'--mode','installer','--profile','server-core','--no-install-image','--no-hyperv-vhdx','--media-public-key',str(c.TARGET/'build-tools/gnome50-candidate.ed25519.pub'),'--output',str(out),'--keep-tree',str(tree),'--release-name','KIKI-GNOME50-CANDIDATE']
    command.remove('build')
    command=[part.replace(str(c.TARGET/'iso-inputs'),str(c.TARGET/'iso-inputs-r6')) for part in command]
    command[command.index('--rootfs-dir')+1]=str(empty)
    command.extend(['--kernel',str(c.WORK/'native-desktop-root-v2/boot/vmlinuz-kiki')])
    subprocess.run(command,check=True)
    c.save(Path(str(out)+'.sha256.json'),dict(file=str(out),sha256=c.sha256_file(out),bytes=out.stat().st_size,scope='Candidate installer; fresh installation validation pending',release_ready=False))
    print('Built preserved-frontend GNOME candidate installer ISO',flush=True)

if __name__=='__main__':globals()[sys.argv[1]]()
