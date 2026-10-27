"""Capture the real network TUI in a disposable installed KIKI OS VM."""
import argparse
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import time
from ki2bootsmoke import qmp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-result', type=Path, required=True)
    parser.add_argument('--media-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = args.install_result.resolve(strict=True)
    installed = json.loads(result.read_text())
    disk = Path(installed['disk']).resolve(strict=True)
    if not installed.get('success') or disk.parent != result.parent or disk.name != 'install-test.qcow2' or not disk.is_file():
        parser.error('requires a successful isolated install-smoke disk')
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    overlay = out / 'preview.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(disk), str(overlay)], check=True)
    payload = out / 'payload.img'
    with payload.open('xb') as f:
        f.truncate(128 * 1024 * 1024)
    subprocess.run(['mformat', '-i', str(payload), '-F', '::'], check=True)
    source = Path(__file__).resolve().parents[1] / 'distro/sources/kiki-netconfig/usr/bin/kiki-netconfig'
    subprocess.run(['mcopy', '-i', str(payload), str(source), '::/kiki-netconfig'], check=True)
    sockpath = out / 'qmp.sock'
    media = args.media_root.resolve(strict=True)
    command = ['/usr/libexec/qemu-kvm', '-machine', 'q35,accel=kvm', '-cpu', 'host', '-m', '1536', '-smp', '2',
               '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-qmp', f'unix:{sockpath},server=on,wait=off',
               '-netdev', 'user,id=n', '-device', 'virtio-net-pci,netdev=n,addr=0x2', '-no-reboot',
               '-drive', f'file={overlay},format=qcow2,if=none,id=os', '-device', 'virtio-blk-pci,drive=os,addr=0x3',
               '-drive', f'file={payload},format=raw,readonly=on,if=none,id=data', '-device', 'virtio-blk-pci,drive=data,addr=0x4',
               '-kernel', str(media / 'boot/vmlinuz-kiki'), '-initrd', str(media / 'boot/initramfs-kiki-installed.img'),
               '-append', 'console=tty0 console=ttyS0,115200n8 root=/dev/vda3 rw init=/init kiki.boot=installed']
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    os.set_blocking(proc.stdout.fileno(), False)
    transcript = bytearray()
    def send(text):
        proc.stdin.write((text + '\n').encode()); proc.stdin.flush()
    def until(marker, timeout=120):
        start = time.monotonic()
        buf = bytearray()
        while time.monotonic() - start < timeout:
            select.select([proc.stdout], [], [], .25)
            chunk = proc.stdout.read() or b''
            transcript.extend(chunk); buf.extend(chunk)
            if marker in buf.decode(errors='replace'):
                return
            if proc.poll() is not None:
                break
        raise RuntimeError('Timed out waiting for ' + marker)
    try:
        until('login:'); send('kiki')
        until('Password:'); send('kiki')  # Isolated autoinstall lab credential only.
        until('$ '); send('stty -echo')
        time.sleep(.5)
        send('sudo -S -p LAB_PASSWORD true && echo LAB_AUTH_OK')
        until('LAB_PASSWORD'); send('kiki'); until('LAB_AUTH_OK')
        send('sudo -n mkdir -p /mnt/netconfig-lab && sudo -n mount -o ro /dev/vdb /mnt/netconfig-lab && sudo -n systemctl stop kiki-ai-console@tty1 && sudo -n systemd-run --unit=netconfig-preview -p StandardInput=tty -p StandardOutput=tty -p StandardError=tty -p TTYPath=/dev/tty1 -p TTYReset=yes --setenv=TERM=linux /usr/bin/python3 /mnt/netconfig-lab/kiki-netconfig tui --dry-run && echo LAB_TUI_STARTED')
        until('LAB_TUI_STARTED')
        time.sleep(2)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10); sock.connect(str(sockpath)); sock.recv(4096)
            qmp(sock, 'qmp_capabilities')
            def keys(text):
                for char in text:
                    key = {'.': 'dot', '/': 'slash', '\n': 'ret'}.get(char, char)
                    qmp(sock, 'human-monitor-command', {'command-line': 'sendkey ' + key})
                    time.sleep(.12)
            qmp(sock, 'human-monitor-command', {'command-line': 'sendkey ctrl-alt-f1'})
            time.sleep(1)
            qmp(sock, 'screendump', {'filename': str(out / 'select.ppm')})
            keys('1\n2\n10.0.2.15/24\n10.0.2.2\n10.0.2.3\n')
            time.sleep(1)
            qmp(sock, 'screendump', {'filename': str(out / 'review.ppm')})
        print('Captured real guest TUI preview: ' + str(out / 'review.ppm'))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        transcript.extend(proc.stdout.read() or b'')
        (out / 'serial.log').write_bytes(transcript)


if __name__ == '__main__':
    main()
