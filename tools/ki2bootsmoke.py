"""Boot a fresh install-smoke disk through an isolated disposable overlay.

Never attaches host block devices or forwards network ports. Direct mode tests
runtime services; UEFI mode captures the actual firmware/GRUB boot for review.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import time


def qmp(sock, command, arguments=None):
    sock.sendall((json.dumps({'execute': command, 'arguments': arguments or {}}) + '\n').encode())
    while True:
        line = sock.makefile('rb', buffering=0).readline()
        if not line:
            raise RuntimeError('QMP closed')
        reply = json.loads(line)
        if 'error' in reply:
            raise RuntimeError(str(reply['error']))
        if 'return' in reply:
            return reply['return']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-result', type=Path, required=True)
    parser.add_argument('--media-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--mode', choices=['direct', 'uefi', 'secureboot'], required=True)
    parser.add_argument('--secure-vars', type=Path, help='LAB ONLY: prepared private OVMF variable template')
    parser.add_argument('--secure-uki', type=Path, help='LAB ONLY: UKI to boot from a separate read-only ESP')
    parser.add_argument('--expect-rejected', action='store_true', help='LAB ONLY: require firmware rejection of the unsigned UKI')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--lab-password', default='kiki',
                        help='password set in the isolated test installer, never an existing user VM')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--ai', action='store_true', help='test real packaged model replies with --once; never execute generated plans')
    parser.add_argument('--dnssec-test-off', action='store_true', help='TEST ONLY: compare per-link DNSSEC disabled in the overlay')
    parser.add_argument('--dbus-unit-override', type=Path, help='TEST ONLY: replace two units in the disposable overlay')
    args = parser.parse_args()
    if args.mode == 'secureboot':
        if not args.secure_vars or not args.secure_uki or not args.secure_vars.is_file() or not args.secure_uki.is_file():
            parser.error('secureboot requires regular --secure-vars and --secure-uki files')
    elif args.secure_vars or args.secure_uki or args.expect_rejected:
        parser.error('Secure Boot options require --mode secureboot')
    result_path = args.install_result.resolve(strict=True)
    installed = json.loads(result_path.read_text())
    disk = Path(installed['disk']).resolve(strict=True)
    if not installed.get('success') or disk.parent != result_path.parent or disk.name != 'install-test.qcow2':
        parser.error('requires the successful, fresh disk from ki2installsmoke.py')
    if not disk.is_file():
        parser.error('disk must be a regular file')
    media = args.media_root.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    overlay = output / 'boot-test.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(disk), str(overlay)], check=True)
    qmp_path = output / 'qmp.sock'
    command = ['/usr/libexec/qemu-kvm', '-machine', 'q35,accel=kvm', '-cpu', 'host',
               '-m', '2048' if args.ai else '1536', '-smp', '2', '-display', 'none', '-serial', 'stdio',
               '-monitor', 'none', '-qmp', f'unix:{qmp_path},server=on,wait=off',
               '-netdev', 'user,id=guestnet',
               '-device', 'virtio-net-pci,netdev=guestnet,addr=0x2', '-no-reboot',
               '-drive', f'file={overlay},format=qcow2,if=none,id=os-disk',
               '-device', 'virtio-blk-pci,drive=os-disk,addr=0x3,bootindex=2']
    if args.mode == 'direct':
        command += ['-kernel', str(media / 'boot/vmlinuz-kiki'),
                    '-initrd', str(media / 'boot/initramfs-kiki-installed.img'),
                    '-append', 'console=tty0 console=ttyS0,115200n8 root=/dev/vda3 rw init=/init kiki.boot=installed']
    else:
        firmware = Path('/usr/share/edk2/ovmf')
        variables = output / 'OVMF_VARS.fd'
        secure = args.mode == 'secureboot'
        shutil.copyfile(args.secure_vars if secure else firmware / 'OVMF_VARS.fd', variables)
        code = firmware / ('OVMF_CODE.secboot.fd' if secure else 'OVMF_CODE.fd')
        command += ['-drive', f'if=pflash,format=raw,readonly=on,file={code}',
                    '-drive', f'if=pflash,format=raw,file={variables}']
        if secure:
            command[command.index('q35,accel=kvm')] = 'q35,accel=kvm,smm=on'
            esp = output / 'esp.img'
            with esp.open('xb') as esp_file:
                esp_file.truncate(128 * 1024 * 1024)
            subprocess.run(['mformat', '-i', str(esp), '-F', '::'], check=True)
            subprocess.run(['mmd', '-i', str(esp), '::/EFI', '::/EFI/BOOT'], check=True)
            subprocess.run(['mcopy', '-i', str(esp), str(args.secure_uki), '::/EFI/BOOT/BOOTX64.EFI'], check=True)
            command += ['-global', 'driver=cfi.pflash01,property=secure,value=on',
                        '-drive', f'file={esp},format=raw,readonly=on,if=none,id=secure-esp',
                        '-device', 'virtio-blk-pci,drive=secure-esp,addr=0x4,bootindex=1']
    transcript = bytearray()
    phase = 0
    sudo_password_sent = False
    started = time.monotonic()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    os.set_blocking(process.stdout.fileno(), False)
    checks = {}
    override = ''
    if args.dbus_unit_override:
        for unit in ['dbus.service', 'dbus.socket']:
            encoded = base64.b64encode((args.dbus_unit_override / unit).read_bytes()).decode()
            override += f'printf %s {encoded} | base64 -d | sudo -n tee /usr/lib/systemd/system/{unit} >/dev/null; '
        override += ('sudo -n systemctl daemon-reload; sudo -n systemctl stop dbus.service dbus.socket; '
                     'sudo -n systemctl start dbus.socket dbus.service; sleep 2; '
                     'systemctl is-active --quiet systemd-networkd && echo CHECK_NETWORKD_OK; '
                     'systemctl is-active --quiet dbus && echo CHECK_DBUS_OK; '
                     'systemctl is-active --quiet kiki-ai-console@tty1 && echo CHECK_CONSOLE_OK; ')
    try:
        while time.monotonic() - started < args.timeout:
            select.select([process.stdout], [], [], 0.5)
            chunk = process.stdout.read() or b''
            transcript.extend(chunk)
            if chunk:
                with (output / 'serial.log').open('ab') as live_log:
                    live_log.write(chunk)
            text = transcript.decode(errors='replace')
            if process.poll() is not None or 'Kernel panic' in text or 'Cannot mount installed root.' in text:
                break
            if args.mode == 'uefi' or args.expect_rejected:
                if time.monotonic() - started >= 65:
                    if args.expect_rejected:
                        checks['firmware_rejected_unsigned'] = any(
                            marker in text for marker in ['Access Denied', 'Security Violation'])
                        checks['kernel_not_started'] = 'Linux version ' not in text and 'login:' not in text
                    break
                continue
            if phase == 0 and 'login:' in text:
                process.stdin.write(b'kiki\n'); process.stdin.flush(); phase = 1
            elif phase == 1 and 'Password:' in text:
                # This credential is defined by the isolated autoinstall lab path,
                # never guessed against an existing user VM.
                process.stdin.write((args.lab_password + '\n').encode()); process.stdin.flush(); phase = 2
            elif phase == 2 and ('kiki:~$' in text or 'kiki:~ $' in text or 'kiki@' in text or '$ ' in text.split('Password:')[-1]):
                script = ("stty -echo; printf '\\n'; "
                          "uname -r; uname -r | grep -qx '6.1.187-kiki-vm' && echo CHECK_KERNEL61_OK; "
                          "systemctl is-active --quiet systemd-networkd && echo CHECK_NETWORKD_OK; "
                          "systemctl is-active --quiet dbus && echo CHECK_DBUS_OK; "
                          "ip -4 addr show scope global | grep -q inet && echo CHECK_IPV4_OK; "
                          "ip -4 route | grep -q '^default' && echo CHECK_ROUTE_OK; "
                          "timeout 15 getent ahostsv4 example.com >/dev/null && echo CHECK_DNS_OK; "
                          "systemctl --failed --no-legend --no-pager >/tmp/kiki-failed-units && test ! -s /tmp/kiki-failed-units && echo CHECK_NO_FAILED_UNITS_OK; "
                          "test $(wc -l </proc/swaps) -gt 1 && echo CHECK_SWAP_OK; "
                          "systemctl is-active --quiet kiki-ai-console@tty1 && echo CHECK_CONSOLE_OK; "
                          "systemctl --failed --no-pager; "
                          "networkctl status --no-pager; "
                          "cat /proc/swaps; ip -br addr; ip route; "
                          "sudo -S -p CHECK_SUDO_PASSWORD /usr/bin/id -u && echo CHECK_SUDO_OK; "
                          "sudo -n -i /usr/bin/true && echo CHECK_SUDO_LOGIN_OK; "
                          + ("sudo -n od -An -t u1 -j 4 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | tr -d '[:space:]' | grep -qx 1 && echo CHECK_SECURE_BOOT_OK; "
                             if args.mode == 'secureboot' else "")
                          + override
                          + ("sudo -n resolvectl dnssec enp0s2 no; sudo -n resolvectl flush-caches; "
                             "timeout 15 getent ahostsv4 example.com && echo CHECK_DNS_WITHOUT_DNSSEC_OK; "
                             if args.dnssec_test_off else "")
                          + ("sudo -n journalctl -b --no-pager | grep -i -E 'dbus|bus connection|systemd1|permission'; "
                             "sudo -n systemctl status dbus systemd-networkd --no-pager; "
                             "sudo -n busctl --system list --no-pager; "
                             "ls -ld /var/run /run/dbus; ls -l /usr/libexec/dbus-daemon-launch-helper; "
                             "cat /etc/resolv.conf; resolvectl status --no-pager; "
                             "sudo -n journalctl -b -u systemd-resolved --no-pager; "
                             "timeout 15 resolvectl query example.com; "
                             "timeout 10 busybox nslookup example.com 10.0.2.3; "
                             "timeout 10 busybox nslookup example.com 1.1.1.1; "
                             if args.diagnose else "")
                          + ("sudo -n /usr/bin/kiki-ai-console --wait-local-runtime 60s --once Hello >/tmp/ai-hello 2>&1; cat /tmp/ai-hello; "
                             "grep -q 'No commands were executed.' /tmp/ai-hello && ! grep -q 'Planning error:' /tmp/ai-hello && echo CHECK_AI_HELLO_OK; "
                             "sudo -n /usr/bin/kiki-ai-console --once 'Explain what DHCP means. Do not run any commands.' >/tmp/ai-explain 2>&1; cat /tmp/ai-explain; "
                             "grep -qi 'Dynamic Host Configuration Protocol' /tmp/ai-explain && grep -q 'No commands were executed.' /tmp/ai-explain && echo CHECK_AI_EXPLAIN_OK; "
                             "sudo -n /usr/bin/kiki-ai-console --once 'Show the current kernel version using uname -r.' >/tmp/ai-plan 2>&1; cat /tmp/ai-plan; "
                             "grep -q 'Exact commands to execute:' /tmp/ai-plan && grep -q 'uname -r' /tmp/ai-plan && ! grep -q 'Planning error:' /tmp/ai-plan && echo CHECK_AI_PLAN_OK; "
                             if args.ai else "")
                          + "echo CHECK_FINISHED; stty echo\n")
                # Turn echo off in a separate command before emitting markers.
                process.stdin.write(b'stty -echo\n'); process.stdin.flush()
                time.sleep(0.5)
                process.stdin.write(script.encode()); process.stdin.flush(); phase = 3
            elif phase == 3 and 'CHECK_SUDO_PASSWORD' in text and not sudo_password_sent:
                process.stdin.write((args.lab_password + '\n').encode()); process.stdin.flush(); sudo_password_sent = True
            elif phase == 3 and 'CHECK_FINISHED' in text.replace('\r', '').splitlines():
                lines = text.replace('\r', '').splitlines()
                for name in ['NETWORKD', 'DBUS', 'IPV4', 'ROUTE', 'DNS', 'NO_FAILED_UNITS', 'SWAP', 'CONSOLE', 'SUDO', 'SUDO_LOGIN']:
                    checks[name.lower()] = f'CHECK_{name}_OK' in lines
                checks['kernel_61'] = 'CHECK_KERNEL61_OK' in lines
                if args.ai:
                    for name in ['AI_HELLO', 'AI_EXPLAIN', 'AI_PLAN']:
                        checks[name.lower()] = f'CHECK_{name}_OK' in lines
                if args.mode == 'secureboot':
                    checks['secure_boot_enabled'] = 'CHECK_SECURE_BOOT_OK' in lines
                if args.dnssec_test_off:
                    checks['dns_without_dnssec'] = 'CHECK_DNS_WITHOUT_DNSSEC_OK' in lines
                break
        if qmp_path.exists() and process.poll() is None:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(10); sock.connect(str(qmp_path))
                sock.recv(4096)
                qmp(sock, 'qmp_capabilities')
                qmp(sock, 'screendump', {'filename': str(output / 'screen.ppm')})
                if args.mode == 'uefi':
                    qmp(sock, 'human-monitor-command', {'command-line': 'sendkey ctrl-alt-f2'})
                    time.sleep(2)
                    qmp(sock, 'screendump', {'filename': str(output / 'tty2.ppm')})
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        transcript.extend(process.stdout.read() or b'')
        (output / 'serial.log').write_bytes(transcript)
    report = {'mode': args.mode, 'checks': checks,
              'expect_rejected': args.expect_rejected,
              'secure_uki': str(args.secure_uki) if args.secure_uki else None,
              'test_dnssec_disabled': args.dnssec_test_off,
              'test_unit_override': str(args.dbus_unit_override) if args.dbus_unit_override else None,
              'success': bool(checks) and all(checks.values()),
              'scope': {'direct': 'direct kernel runtime test',
                        'uefi': 'UEFI default boot screenshot; manual review required',
                        'secureboot': 'isolated self-signed UKI firmware test; not production trust enrollment'}[args.mode],
              'seconds': round(time.monotonic() - started, 1), 'base_disk_unchanged': str(disk)}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['success'] or args.mode == 'uefi' else 1


if __name__ == '__main__':
    raise SystemExit(main())
