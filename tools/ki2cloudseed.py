#!/usr/bin/env python3
"""Signed OpenStack config-drive adapter for the common stage-1 installer.

No seed means normal interactive boot. A present invalid seed fails closed.
Only the explicitly named, empty Cinder disk may be erased.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

RUN = Path('/run/kiki/cloud-install')
TRUST = Path('/etc/ki2/trust/cloud-install.ed25519.pub')
REQUEST = Path('/run/kiki/gui-install.request')


def report(message):
    print(message, flush=True)
    try:
        fd = os.open('/dev/ttyS0', os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try: os.write(fd, (message+'\n').encode())
        finally: os.close(fd)
    except OSError:
        pass


def public_key_path():
    default = Path(__file__).resolve().parents[1]/'distro/installer/cloud-install.ed25519.pub'
    sibling = Path(__file__).with_name('cloud-install.ed25519.pub')
    return Path(os.environ.get('KI2_CLOUD_INSTALL_PUBLIC_KEY', str(sibling if sibling.is_file() else default)))


def command(args, **kwargs):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=45, **kwargs)
    except subprocess.CalledProcessError as error:
        # These fixed commands carry no password arguments. Keep diagnostics
        # useful without dumping the signed seed, command arguments or stdout.
        stderr = error.stderr or b''
        if isinstance(stderr, bytes): stderr = stderr.decode(errors='replace')
        first = stderr.splitlines()[0][:200] if stderr.splitlines() else 'no diagnostic'
        raise ValueError(f'{Path(args[0]).name} exited {error.returncode}: {first}') from None


def generate_host_key(root):
    target_dev = root/'dev'
    target_dev.mkdir(exist_ok=True)
    if os.path.ismount(target_dev):
        raise ValueError('unexpected existing target device mount')
    # OpenSSH sanitises its file descriptors through /dev/null, even when
    # getrandom provides entropy. The common backend has already unmounted its
    # temporary device bind by this stage. Only unmount the bind we create.
    command(['/bin/busybox', 'mount', '-o', 'bind', '/dev', str(target_dev)])
    try:
        command(['/bin/busybox', 'chroot', str(root), '/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/etc/ssh/ssh_host_ed25519_key'])
    finally:
        command(['/bin/busybox', 'umount', str(target_dev)])


def private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data.encode() if isinstance(data, str) else data)


def validate_seed(seed, now=None):
    if seed.get('schema') != 'kiki-cloud-install-v1':
        raise ValueError('unsupported cloud installation seed')
    for field in ('job_id', 'volume_id'):
        if not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', seed.get(field, '')):
            raise ValueError('invalid ' + field)
    if not re.fullmatch(r'[a-f0-9]{64}', seed.get('iso_sha256', '')):
        raise ValueError('invalid ISO hash')
    if not (0 < seed.get('expires_at', 0) - (time.time() if now is None else now) <= 86400):
        raise ValueError('expired cloud installation seed')
    if seed.get('disk_size_gb') not in range(16, 257):
        raise ValueError('invalid installation disk size')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', seed.get('username', '')):
        raise ValueError('invalid account')
    for field in ('hostname', 'password', 'profile'):
        value = seed.get(field, '')
        if not isinstance(value, str) or not value or len(value) > 100 or any(c in value for c in '\r\n\x00'):
            raise ValueError('invalid ' + field)
    if len(seed['password']) < 20 or not re.fullmatch(r'[a-f0-9]{64}', seed.get('report_secret', '')):
        raise ValueError('weak cloud installation credentials')
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]{60,100}(?: [a-zA-Z0-9-]+)?', seed.get('ssh_public_key', '')):
        raise ValueError('invalid SSH public key')
    packages = seed.get('packages')
    if not isinstance(packages, list) or not 10 <= len(packages) <= 512 or len(set(packages)) != len(packages):
        raise ValueError('invalid package selection')
    if any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+_.-]{0,95}', name) for name in packages):
        raise ValueError('invalid package name')
    if not re.fullmatch(r'[a-f0-9]{64}', seed.get('catalog_sha256', '')):
        raise ValueError('invalid catalogue hash')
    return seed


def choose_disk(seed, sysblock=Path('/sys/class/block'), dev=Path('/dev'), probe=True):
    expected = seed['volume_id'].replace('-', '').lower()
    matches = []
    for disk in sysblock.iterdir():
        if not re.fullmatch(r'(?:sd|vd)[a-z]+|nvme\d+n\d+', disk.name) or (disk/'partition').exists():
            continue
        serials = [disk/'device/serial', disk/'serial']
        serial = next((p.read_text().strip() for p in serials if p.is_file()), '')
        # Linux SCSI exposes the QEMU/Cinder serial through VPD page 0x80;
        # virtio-blk instead provides a plain-text serial attribute.
        vpd = disk/'device/vpd_pg80'
        if not serial and vpd.is_file():
            data=vpd.read_bytes()
            if len(data)>=4 and data[1]==0x80:
                length=int.from_bytes(data[2:4], 'big')
                if 0<length<=252 and len(data)>=4+length:
                    serial=data[4:4+length].decode('ascii', errors='strict').strip('\x00 ')
        serial=serial.replace('-', '').lower()
        if len(serial) < 20 or not expected.startswith(serial):
            continue
        if int((disk/'size').read_text()) * 512 != seed['disk_size_gb'] * 1024**3:
            raise ValueError('target volume size mismatch')
        if any((part/'partition').exists() for part in disk.glob(disk.name+'*')):
            raise ValueError('target volume already has partitions')
        path = dev/disk.name
        if probe:
            result = subprocess.run([shutil.which('blkid') or '/sbin/blkid', '-p', str(path)], capture_output=True, timeout=10)
            if result.returncode != 2:
                raise ValueError('target disk is not empty or cannot be probed')
        matches.append(str(path))
    if len(matches) != 1:
        raise ValueError('expected exactly one matching empty Cinder disk')
    return matches[0]


def find_seed():
    mount = RUN/'config-drive'
    mount.mkdir(parents=True, exist_ok=True)
    seeds = []
    for disk in sorted(Path('/sys/class/block').iterdir()):
        if (disk/'partition').exists() or not re.fullmatch(r'sr\d+|(?:sd|vd)[a-z]+', disk.name):
            continue
        if int((disk/'size').read_text()) * 512 > 64 * 1024**2:
            continue
        result = subprocess.run(['/bin/busybox', 'mount', '-t', 'iso9660', '-o', 'ro,nosuid,nodev,noexec', '/dev/'+disk.name, str(mount)], capture_output=True, timeout=10)
        if result.returncode:
            continue
        try:
            data = mount/'openstack/latest/user_data'
            if data.is_file() and data.stat().st_size <= 64 * 1024:
                raw = data.read_bytes()
                if b'kiki-cloud-install' in raw:
                    seeds.append(raw)
        finally:
            command(['/bin/busybox', 'umount', str(mount)])
    if len(seeds) > 1:
        raise ValueError('multiple installation seeds')
    return seeds[0] if seeds else None


def prepare():
    os.umask(0o077)
    RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run(['/sbin/mdev', '-s'], capture_output=True, timeout=20)
    raw = find_seed()
    if raw is None:
        return 0
    private(RUN/'seed-present', '1\n')
    envelope = json.loads(raw)
    payload = base64.b64decode(envelope['payload'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    private(RUN/'payload.json', payload)
    private(RUN/'signature', signature)
    command(['/usr/bin/openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(TRUST), '-rawin', '-in', str(RUN/'payload.json'), '-sigfile', str(RUN/'signature')])
    seed = validate_seed(json.loads(payload))
    report('KIKI_CLOUD_INSTALL_SEED_VERIFIED '+seed['job_id'])
    disk = choose_disk(seed)
    seed['disk'] = disk
    private(RUN/'state.json', json.dumps(seed))
    fields = {'version': '2', 'plan': '/run/kiki/cloud-install-plan.yaml', 'disk': disk,
              'swap': 'off', 'hostname': seed['hostname'], 'user': seed['username'], 'password': seed['password'],
              'confirmed': 'INSTALL '+disk, 'locale': 'ko_KR.UTF-8', 'keymap': 'us', 'timezone': 'Asia/Seoul',
              'network': 'dhcp', 'profile': seed['profile'], 'runtime': 'profile-default', 'ai': 'off'}
    private(REQUEST, ''.join(k+'='+v+'\n' for k, v in fields.items())+''.join('package='+p+'\n' for p in seed['packages']))
    report('KIKI_CLOUD_INSTALL_AUTHORIZED '+seed['job_id'])
    return 0


def finalize():
    seed = json.loads((RUN/'state.json').read_text())
    root = Path('/mnt/target')
    catalogue = root/'usr/share/ki2/package-groups.json'
    if hashlib.sha256(catalogue.read_bytes()).hexdigest() != seed['catalog_sha256']:
        raise ValueError('installed catalogue differs from signed seed')
    installed = json.loads((root/'var/lib/ki2/installed.json').read_text())['packages']
    if set(installed) != set(seed['packages']):
        raise ValueError('installed package set differs from signed seed')
    rows = [line.split(':') for line in (root/'etc/passwd').read_text().splitlines() if line.split(':')[0] == seed['username']]
    if len(rows) != 1 or rows[0][5] != '/home/'+seed['username']:
        raise ValueError('installed user is missing')
    uid, gid = int(rows[0][2]), int(rows[0][3])
    home = root/rows[0][5].lstrip('/')
    home.mkdir(parents=True, exist_ok=True); os.chown(home, uid, gid)
    ssh = home/'.ssh'; ssh.mkdir(mode=0o700, exist_ok=True); ssh.chmod(0o700); os.chown(ssh, uid, gid)
    private(ssh/'authorized_keys', seed['ssh_public_key']+'\n'); os.chown(ssh/'authorized_keys', uid, gid)
    # Generate on the installer's entropy source; never bake host keys in ISO.
    hostkey = root/'etc/ssh/ssh_host_ed25519_key'
    if not hostkey.exists():
        generate_host_key(root)
    host_public = hostkey.with_suffix('.pub').read_text().strip()
    provenance = {k: seed[k] for k in ('job_id', 'iso_sha256', 'volume_id', 'catalog_sha256', 'profile')}
    provenance.update(schema='kiki-cloud-install-result-v1', status='installed', ssh_host_key=host_public)
    private(root/'var/lib/kiki/cloud-install.json', json.dumps(provenance, indent=2)+'\n')
    private(RUN/'result.json', json.dumps(provenance, separators=(',', ':')))


def complete():
    seed = json.loads((RUN/'state.json').read_text())
    payload = (RUN/'result.json').read_bytes()
    signature = hmac.new(bytes.fromhex(seed['report_secret']), payload, hashlib.sha256).hexdigest()
    marker = 'KIKI_CLOUD_INSTALL_RESULT '+base64.b64encode(payload).decode()+'.'+signature+'\n'
    # Serial survives guest shutdown and is retrieved through authenticated Nova.
    report(marker.rstrip('\n'))
    for name in ('state.json', 'payload.json', 'signature'):
        (RUN/name).unlink(missing_ok=True)


def inject_init(source):
    """Also patch the frozen, payload-verified backend used by release workers."""
    def once(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('cloud installer hook does not match backend: '+old[:60])
        source = source.replace(old, new)
    once('static void run_guided_package_installer_with_request(', '''static int cloud_install_active = 0;
static int cloud_seed_command(const char *action) {
    char *argv[] = {"/usr/bin/python3", "-B", "/usr/lib/kiki-installer/ki2cloudseed.py", (char *)action, 0};
    return run_program("/usr/bin/python3", argv);
}
static void run_guided_package_installer_with_request(''')
    once('    if (!finalize_target_mounts()) return;', '''    if (cloud_install_active && cloud_seed_command("finalize") != 0) goto target_configuration_failed;
    if (!finalize_target_mounts()) return;''')
    once('    if (!maybe_run_cmdline_autoinstall()) {', '''    int cloud_seed_status = cloud_seed_command("prepare");
    if (cloud_seed_status != 0 || file_exists("/run/kiki/cloud-install/seed-present")) {
        cloud_install_active = 1;
        struct gui_install_request cloud_request;
        if (cloud_seed_status == 0 && load_gui_install_request(&cloud_request)) {
            run_guided_package_installer_with_request(0, 1, &cloud_request);
            for (size_t i = 0; i < sizeof(cloud_request); i++) ((volatile char *)&cloud_request)[i] = 0;
            if (gui_install_succeeded && cloud_seed_command("complete") == 0) poweroff_now();
        }
        cloud_seed_command("failure");
        say("Cloud installation failed. Disk and console are preserved for inspection.\\n");
        for (;;) ksys(SYS_pause, 0, 0, 0, 0, 0, 0);
    }
    if (!maybe_run_cmdline_autoinstall()) {''')
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'finalize', 'complete', 'failure'])
    args = parser.parse_args()
    try:
        if args.action == 'prepare': return prepare()
        if args.action == 'finalize': finalize()
        elif args.action == 'complete': complete()
        else: report('KIKI_CLOUD_INSTALL_FAILED common-installer-backend')
        return 0
    except Exception as error:
        # Seed/password/key material must never reach console diagnostics.
        detail = ': '+str(error) if isinstance(error, ValueError) else ''
        report('KIKI_CLOUD_INSTALL_FAILED '+type(error).__name__+detail)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
