#!/usr/bin/env python3
"""Build a candidate-only installed initramfs with a real mount-root handoff."""
import difflib
import importlib.util
from pathlib import Path
import shutil
import ki2sessioncandidate as c

original=c.REPO/'tools/ki2bootiso.py';before=original.read_text()
old='''    ksys(SYS_chroot, (long)"/sysroot", 0, 0, 0, 0, 0);
    ksys(SYS_chdir, (long)"/", 0, 0, 0, 0, 0);
    char *argv_systemd[]'''
new='''    /* Move the installed mount onto the namespace root, as switch_root does.
     * A chroot alone leaves current_chrooted() true and blocks user namespaces. */
    if (ksys(SYS_chdir, (long)"/sysroot", 0, 0, 0, 0, 0) < 0 ||
        ksys(SYS_mount, (long)".", (long)"/", 0, 8192 /* MS_MOVE */, 0, 0) < 0 ||
        ksys(SYS_chroot, (long)".", 0, 0, 0, 0, 0) < 0 ||
        ksys(SYS_chdir, (long)"/", 0, 0, 0, 0, 0) < 0) {
        say("Installed mount-root handoff failed; refusing to start a chrooted PID 1.\\n");
        return 0;
    }
    char *argv_systemd[]'''
if before.count(old)!=1:raise ValueError('Unexpected original boot handoff source')
after=before.replace(old,new)
frozen=c.TARGET/'inputs/boot-handoff';frozen.mkdir(exist_ok=True,parents=True)
source=frozen/'ki2bootiso.py'
if source.exists():raise FileExistsError(source)
source.write_text(after)
patch=frozen/'installed-mount-root.patch'
patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/tools/ki2bootiso.py',tofile='b/tools/ki2bootiso.py')))
spec=importlib.util.spec_from_file_location('kiki_candidate_handoff_boot',source)
boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)
work=c.WORK/'installed-handoff-v1';work.mkdir(exist_ok=False)
output=c.TARGET/'boot/installed-initramfs-msmove-v1.img';output.parent.mkdir(exist_ok=True)
boot.build_initramfs(output,work,arch='x86_64',profile='gnome50-candidate',cc='gcc',installed=True)
tree=work/'tree/boot/grub';tree.mkdir(exist_ok=True,parents=True)
kernel=c.WORK/'native-desktop-root-v2/boot/vmlinuz-kiki'
shutil.copy2(kernel,tree.parent/'vmlinuz');shutil.copy2(output,tree.parent/'installed.img')
(tree/'grub.cfg').write_text('''set timeout=0
set default=0
menuentry "KIKI candidate installed-root handoff validation" {
 linux /boot/vmlinuz root=/dev/sda3 console=tty0 console=ttyS0,115200
 initrd /boot/installed.img
}
''')
iso=c.TARGET/'iso/installed-root-handoff-validation.iso'
if iso.exists():raise FileExistsError(iso)
boot.build_boot_iso(work/'tree',iso)
record=dict(original_source_sha256=c.sha256_file(original),candidate_source_sha256=c.sha256_file(source),patch_sha256=c.sha256_file(patch),initramfs=str(output),initramfs_sha256=c.sha256_file(output),kernel_sha256=c.sha256_file(kernel),compiler_sha256=c.sha256_file('/usr/bin/gcc'),scope='Candidate-only handoff validation; old installer/boot image preserved')
c.save(c.TARGET/'validation/installed-handoff-build.json',record)
c.save(Path(str(iso)+'.sha256.json'),dict(file=str(iso),sha256=c.sha256_file(iso),bootable=True,scope=record['scope']))
print('Built candidate mount-root handoff initramfs and validation ISO',flush=True)
