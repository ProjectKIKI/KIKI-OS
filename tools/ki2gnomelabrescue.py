#!/usr/bin/env python3
"""Make a narrowly scoped recovery ISO for only the disposable 32 GiB lab guest."""
import json
from pathlib import Path
import shutil
import subprocess
import ki2sessioncandidate as c
import ki2bootiso as boot

root=c.WORK/'lab-account-recovery-v3';root.mkdir(exist_ok=False)
initrd=root/'initrd';initrd.mkdir()
native=c.WORK/'native-desktop-root-v2'
for path in ['bin','lib64','dev','proc','sys','run','mnt/target']:(initrd/path).mkdir(parents=True,exist_ok=True)
shutil.copy2(native/'bin/busybox',initrd/'bin/busybox')
for name in ['sh','mount','umount','grep','cat','sleep','reboot','sync','mv','cp','chmod','mkdir','wc','hostname']:(initrd/'bin'/name).symlink_to('busybox')
for name in ['ld-linux-x86-64.so.2','libc.so.6','libm.so.6','libresolv.so.2']:shutil.copy2((native/'lib64'/name).resolve(),initrd/'lib64'/name)
shutil.copytree(c.WORK/'gdm-integration-v4',initrd/'repair')
shutil.copytree(c.WORK/'bash-conventional-path',initrd/'repair-bash')
hashed=subprocess.check_output(['openssl','passwd','-6','-stdin'],input=b'kiki123456\n').decode().strip()
script='''#!/bin/sh
PATH=/bin; export PATH
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs devtmpfs /dev
exec </dev/ttyS0 >/dev/ttyS0 2>&1
set -eu
grep -q 'kiki.lab-repair=b8b85400-c175-4474-8fa4-721cfb5eb039' /proc/cmdline
for n in 1 2 3 4 5; do [ -b /dev/sda3 ] && break; sleep 1; done
[ "$(cat /sys/class/block/sda/size)" = 67108864 ]
mount /dev/sda3 /mnt/target
grep -q KIKI /mnt/target/etc/os-release
mount --bind /dev /mnt/target/dev
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if ! /bin/busybox chroot /mnt/target /usr/bin/id -u kiki; then
 /bin/busybox chroot /mnt/target /usr/sbin/useradd -m -u 1000 -g users -G sudo -s /bin/bash kiki
fi
[ "$(/bin/busybox chroot /mnt/target /usr/bin/id -u kiki)" = 1000 ]
/bin/busybox chroot /mnt/target /usr/sbin/usermod -p '__LAB_HASH__' kiki
/bin/busybox chroot /mnt/target /usr/sbin/usermod -s /usr/bin/bash kiki
/bin/busybox chroot /mnt/target /usr/sbin/usermod -a -G sudo kiki
/bin/busybox chroot /mnt/target /usr/sbin/usermod -L root
mkdir -p /mnt/target/etc/sudoers.d
printf '%%sudo ALL=(ALL:ALL) ALL\\n' > /mnt/target/etc/sudoers.d/90-kiki-session-lab
chmod 0440 /mnt/target/etc/sudoers.d/90-kiki-session-lab
printf 'kiki-lab\\n' > /mnt/target/etc/hostname
/bin/busybox cp -a /repair/. /mnt/target/
/bin/busybox cp -a /repair-bash/. /mnt/target/
/bin/busybox chroot /mnt/target /usr/bin/systemd-machine-id-setup
/bin/busybox chroot /mnt/target /usr/bin/systemd-sysusers
/bin/busybox chroot /mnt/target /usr/bin/kiki-netconfig off --file 20-wired.network
root_id=$(/bin/busybox chroot /mnt/target /sbin/blkid -s UUID -o value /dev/sda3)
esp_id=$(/bin/busybox chroot /mnt/target /sbin/blkid -s UUID -o value /dev/sda1)
swap_id=$(/bin/busybox chroot /mnt/target /sbin/blkid -s UUID -o value /dev/sda2)
[ -n "$root_id" ]; [ -n "$esp_id" ]; [ -n "$swap_id" ]
printf 'UUID=%s / ext4 defaults 0 1\\nUUID=%s /boot/efi vfat noauto,nofail,umask=0077 0 0\\nUUID=%s none swap defaults,nofail 0 0\\n' "$root_id" "$esp_id" "$swap_id" > /mnt/target/etc/fstab
sync
umount /mnt/target/dev
umount /mnt/target
echo LAB_ACCOUNT_IDENTITY_FSTAB_RESTORED
echo HALT_REMOVE_RECOVERY_MEDIA
echo LAB_RECOVERY_V3_COMPLETE_REMOVE_MEDIA
exec /bin/sh
'''.replace('__LAB_HASH__',hashed)
(initrd/'init').write_text(script);(initrd/'init').chmod(0o755)
tree=root/'tree/boot/grub';tree.mkdir(parents=True)
shutil.copy2(native/'boot/vmlinuz-kiki',tree.parent/'vmlinuz')
boot.write_newc_gzip(initrd,tree.parent/'rescue.img')
(tree/'grub.cfg').write_text('''set timeout=0
set default=0
menuentry "KIKI isolated lab account recovery" {
 linux /boot/vmlinuz console=tty0 console=ttyS0,115200 kiki.lab-repair=b8b85400-c175-4474-8fa4-721cfb5eb039
 initrd /boot/rescue.img
}
''')
iso=c.TARGET/'iso/isolated-lab-account-recovery-v3.iso'
if iso.exists():raise FileExistsError(iso)
boot.build_boot_iso(root/'tree',iso)
c.save(Path(str(iso)+'.sha256.json'),dict(file=str(iso),sha256=c.sha256_file(iso),scope='Private disposable lab account recovery; never distribute',bootable=True))
print('Created private lab recovery ISO',flush=True)
