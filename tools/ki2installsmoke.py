"""Install verified ISO payloads into a NEW isolated VM disk (no networking)."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--media-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    iso = args.iso.resolve(strict=True)
    media = args.media_root.resolve(strict=True)
    kernel = (media / 'boot/vmlinuz-kiki').resolve(strict=True)
    initrd = (media / 'boot/initramfs-kiki.img').resolve(strict=True)
    output = args.output_dir.resolve()
    # Never accept or reuse a pre-existing disk or output directory.
    output.mkdir(parents=True, exist_ok=False)
    disk = output / 'install-test.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(disk), '20G'], check=True)
    log = output / 'serial.log'
    command = [
        '/usr/libexec/qemu-kvm', '-machine', 'accel=kvm', '-cpu', 'host', '-m', '2048', '-smp', '2',
        '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
        '-no-reboot', '-drive', f'file={disk},format=qcow2,if=virtio',
        '-cdrom', str(iso), '-kernel', str(kernel), '-initrd', str(initrd),
        '-append', 'console=ttyS0,115200n8 loglevel=3 kiki.autoinstall=erase '
                   'kiki.target=/dev/vda kiki.profile=server-core kiki.timezone=Asia/Seoul '
                   'kiki.hostname=kiki-install-test kiki.ai=local',
    ]
    success = False
    reason = 'timeout'
    started = time.monotonic()
    with log.open('xb') as stream:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT)
        try:
            while time.monotonic() - started < args.timeout:
                text = log.read_text(errors='replace')
                if 'Guided install finished.' in text:
                    success, reason = True, 'installer completed and unmounted target'
                    break
                if 'Kernel panic' in text or process.poll() is not None:
                    reason = 'guest stopped before installer completion'
                    break
                if 'Required system configuration failed.' in text or 'Account setup failed.' in text:
                    reason = 'installation post-configuration failed'
                    break
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    report = {'success': success, 'reason': reason, 'iso': str(iso), 'disk': str(disk),
              'log': str(log), 'seconds': round(time.monotonic() - started, 1), 'qemu_exit_code': process.returncode,
              'scope': 'serial unattended install; not GUI or installed UEFI boot validation'}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
