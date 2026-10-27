"""Prepare self-signed UKIs and private OVMF variables for disposable VM tests.

Never enrolls host firmware, modifies a real VM, or places keys in an ISO.
The SDK must be an already verified, extracted set of distribution packages.
This is a development trust chain, not a production Secure Boot release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--ukify', type=Path, required=True)
    parser.add_argument('--stub', type=Path, help='explicit verified/build-from-source EFI stub')
    parser.add_argument('--media-root', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    sdk = args.sdk.resolve(strict=True)
    media = args.media_root.resolve(strict=True)
    root = args.rootfs.resolve(strict=True)
    ukify = args.ukify.resolve(strict=True)
    stub = args.stub.resolve(strict=True) if args.stub else sdk / 'usr/lib/systemd/boot/efi/linuxx64.efi.stub'
    required = [stub, ukify, media / 'boot/vmlinuz-kiki',
                media / 'boot/initramfs-kiki-installed.img', root / 'etc/os-release',
                sdk / 'usr/bin/sbsign', sdk / 'usr/bin/sbverify', sdk / 'usr/bin/virt-fw-vars']
    for path in required:
        if not path.is_file():
            parser.error(f'missing regular input: {path}')
    output = args.output_dir.resolve()
    old_umask = os.umask(0o077)
    try:
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        key = output / 'development-only.key'
        certificate = output / 'development-only.crt'
        unsigned = output / 'kiki-unsigned.efi'
        signed = output / 'kiki-signed.efi'
        variables = output / 'OVMF_VARS.private.fd'
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(sdk / 'usr/lib/python3.9/site-packages'),
                   PATH=f'{sdk / "usr/bin"}:/usr/bin:/bin')
        with (output / 'prepare.log').open('x') as log:
            def run(command):
                subprocess.run([str(p) for p in command], check=True, env=env,
                               stdout=log, stderr=subprocess.STDOUT)
            run(['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-sha256',
                 '-nodes', '-days', '30', '-subj', '/CN=KIKI isolated VM development ONLY/',
                 '-keyout', key, '-out', certificate])
            run([sys.executable, ukify, 'build', '--linux', media / 'boot/vmlinuz-kiki',
                 '--initrd', media / 'boot/initramfs-kiki-installed.img', '--stub', stub,
                 '--cmdline', 'console=tty0 console=ttyS0,115200n8 root=/dev/vda3 rw init=/init kiki.boot=installed',
                 '--os-release', f'@{root / "etc/os-release"}', '--uname', '6.1.187-kiki-vm',
                 '--output', unsigned])
            run(['sbsign', '--key', key, '--cert', certificate, '--output', signed, unsigned])
            run(['sbverify', '--cert', certificate, signed])
            run(['virt-fw-vars', '--input', '/usr/share/edk2/ovmf/OVMF_VARS.fd',
                 '--output', variables, '--enroll-cert', certificate,
                 '--add-db', str(uuid.uuid4()), certificate,
                 '--no-microsoft', '--microsoft-kek', 'none', '--secure-boot'])
        report = {'scope': 'isolated development UKI; no production trust enrollment',
                  'stub': str(stub), 'ukify': str(ukify),
                  'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [stub, certificate, unsigned, signed, variables]},
                  'private_key_in_iso': False, 'boot_test_completed': False}
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
    finally:
        os.umask(old_umask)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
