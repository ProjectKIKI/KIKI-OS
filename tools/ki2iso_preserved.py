#!/usr/bin/env python3
"""Use an explicitly pinned preserved installer with the current ISO generator.

Archive SHA and every payload file must match before the original GUI runtime
can enter new candidate media. The selected package catalogue and the current
network-plan writer are shared with the rebuilt installer frontends.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import ki2installcatalog
import ki2cloudseed


def preserved_guard(original, expected_file, expected_sha, file_sha, audit):
    def verify(package):
        if package.name != expected_file or file_sha(package) != expected_sha:
            return original(package)
        result = audit(package)
        if result['errors'] or result.get('name') != 'kiki-installer-gtk':
            raise ValueError('보존 설치기 파일 명세가 일치하지 않습니다.')
        print('PRESERVED_INSTALLER_SHA_AND_PAYLOAD_VERIFIED', expected_sha, flush=True)
    return verify


def current_media_verifier(original):
    def add(root, packages_dir, public_key):
        original(root,packages_dir,public_key)
        # The preserved backend carries its original helper. Ship the current
        # network-plan writer with the current frontends in new media.
        shutil.copy2(Path(__file__).with_name('ki2network.py'),root/'usr/lib/kiki-installer/ki2network.py')
        public=ki2cloudseed.public_key_path()
        if public.is_file():
            # Empty-disk protection must use the real util-linux probe, with
            # the same libblkid ABI already restored by the frozen backend.
            import ki2bootiso
            ki2bootiso.extract_package_members(ki2bootiso.latest_package(packages_dir,'util-linux'),root,{'sbin/blkid','usr/sbin/blkid'})
            if not any((root/name).is_file() for name in ['sbin/blkid','usr/sbin/blkid']):
                raise ValueError('cloud installer requires the signed util-linux blkid tool')
            shutil.copy2(Path(__file__).with_name('ki2cloudseed.py'),root/'usr/lib/kiki-installer/ki2cloudseed.py')
            (root/'etc/ki2/trust').mkdir(parents=True,exist_ok=True)
            shutil.copy2(public,root/'etc/ki2/trust/cloud-install.ed25519.pub')
    return add


def kernel_guard(original, expected_file, expected_sha, file_sha, audit):
    if Path(expected_file).name != expected_file or not expected_file.endswith('.ki2'):
        raise ValueError('invalid pinned kernel filename')
    def find(rootfs_dir, packages_dir, work_dir, requested=None, pinned_filename=None):
        package=packages_dir/expected_file
        if requested is not None or not package.is_file() or file_sha(package)!=expected_sha:
            raise ValueError('snapshot kernel package SHA mismatch or missing')
        result=audit(package)
        if result['errors'] or result.get('name')!='linux':
            raise ValueError('snapshot kernel payload mismatch')
        return original(rootfs_dir,packages_dir,work_dir,pinned_filename=expected_file)
    return find


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-installer-file',required=True)
    parser.add_argument('--expected-installer-sha256',required=True)
    parser.add_argument('--expected-kernel-file',required=True)
    parser.add_argument('--expected-kernel-sha256',required=True)
    parser.add_argument('--repo-root',type=Path,required=True)
    parser.add_argument('--catalog-file',type=Path)
    parser.add_argument('--catalog-sha256')
    args,remaining=parser.parse_known_args()
    if bool(args.catalog_file) != bool(args.catalog_sha256):parser.error('catalog file and SHA-256 must be supplied together')
    if args.catalog_file:
        path=args.catalog_file.resolve(strict=True)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=args.catalog_sha256:raise ValueError('설치 그룹 카탈로그 해시 불일치')
        ki2installcatalog.load(path)
        os.environ['KI2_PACKAGE_GROUPS_FILE']=str(path)
    sys.path.insert(0,str(args.repo_root/'tools'))
    import ki2bootiso
    public=ki2cloudseed.public_key_path()
    if public.is_file():ki2bootiso.INIT_C=ki2cloudseed.inject_init(ki2bootiso.INIT_C)
    from ki2integrity import audit_payload,sha256_file
    ki2bootiso.verify_installer_display_name=preserved_guard(ki2bootiso.verify_installer_display_name,args.expected_installer_file,args.expected_installer_sha256,sha256_file,audit_payload)
    ki2bootiso.add_media_verifier=current_media_verifier(ki2bootiso.add_media_verifier)
    ki2bootiso.find_kernel=kernel_guard(ki2bootiso.find_kernel,args.expected_kernel_file,args.expected_kernel_sha256,sha256_file,audit_payload)
    return ki2bootiso.main(['--repo-root',str(args.repo_root),*remaining])


if __name__=='__main__':raise SystemExit(main())
