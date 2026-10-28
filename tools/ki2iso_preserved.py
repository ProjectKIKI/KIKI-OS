#!/usr/bin/env python3
"""Use an explicitly pinned preserved installer with the current ISO generator.

Only the cosmetic display-name policy is adapted. Archive SHA and every payload
file must match before the original GUI runtime can enter new candidate media.
"""
import argparse
from pathlib import Path
import sys


def preserved_guard(original, expected_file, expected_sha, file_sha, audit):
    def verify(package):
        if package.name != expected_file or file_sha(package) != expected_sha:
            return original(package)
        result = audit(package)
        if result['errors'] or result.get('name') != 'kiki-installer-gtk':
            raise ValueError('보존 설치기 파일 명세가 일치하지 않습니다.')
        print('PRESERVED_INSTALLER_SHA_AND_PAYLOAD_VERIFIED', expected_sha, flush=True)
    return verify


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-installer-file',required=True)
    parser.add_argument('--expected-installer-sha256',required=True)
    parser.add_argument('--repo-root',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    sys.path.insert(0,str(args.repo_root/'tools'))
    import ki2bootiso
    from ki2integrity import audit_payload,sha256_file
    ki2bootiso.verify_installer_display_name=preserved_guard(ki2bootiso.verify_installer_display_name,args.expected_installer_file,args.expected_installer_sha256,sha256_file,audit_payload)
    return ki2bootiso.main(['--repo-root',str(args.repo_root),*remaining])


if __name__=='__main__':raise SystemExit(main())
