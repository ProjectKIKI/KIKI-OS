# 격리 VM 자체 서명 Secure Boot 검증

## 승인 및 범위

사용자는 실제 `kiki-os-test`의 키와 Secure Boot 설정을 변경하지 않고,
격리 VM의 자체 서명부터 검증하는 방식을 선택했다.
실제 Hyper-V VM, 호스트 UEFI, 호스트 systemd에는 변경하지 않았다.
개발용 개인 키는 ISO 및 작업 공간으로 복사하지 않았다.

## 구현

- `tools/ki2securebootlab.py`: 새 0700 디렉터리와 0077 umask에서 30일 개발용 RSA 키/인증서,
  unsigned/signed UKI, 자체 PK/KEK/db만 등록한 OVMF 변수 파일 생성.
- `tools/ki2bootsmoke.py --mode secureboot`: 설치 시험 디스크의 새 qcow2 overlay와
  복사된 변수 파일만 사용. 별도 FAT ESP 파일을 읽기 전용으로 연결.
  SMM 및 pflash secure 설정을 사용하고 네트워크/디스크 PCI 슬롯을 고정한다.
- `--expect-rejected`: firmware의 Access Denied/Security Violation과 커널 미실행을 검사.
- 기존 키 디렉터리 덮어쓰기 및 잘못된 Secure Boot 옵션 차단 테스트 3개 통과.

도구는 Rocky/EPEL 서명 RPM을 확인한 뒤 `/tmp/kiki-secureboot-lab/sdk`에만 추출했다.
초기 Rocky 252 stub의 PE 경고를 피하기 위해, 이미 SHA-256 검증된 systemd 255.7 소스로
별도 최소 EFI 빌드를 수행했다. 최종 시험은 이 255.7 stub과 255.7 ukify를 사용했다.
이는 정식 ki2 EFI stub 패키지 및 배포 서명 파이프라인을 완성했다는 의미가 아니다.

## 결과

- `/tmp/kiki-secureboot-lab/positive255`: 자체 서명 UKI가 firmware 검사를 통과하고
  6.1.187로 OS 로그인 및 서비스 검사 실행. EFI 변수에서 **SecureBoot=1** 확인.
- 커널, networkd, D-Bus, DHCP/경로, swap, 콘솔, sudo 및 실패 서비스 없음 확인.
- 기본 DNS 검사는 실패했고, 시험 overlay에서 DNSSEC를 끈 비교 조회만 성공했다.
  따라서 이 결과 JSON의 전체 `success`는 **false**이며 전체 OS 배포 승인으로 취급하지 않는다.
- `/tmp/kiki-secureboot-lab/negative255`: 동일 신뢰 설정에서 unsigned UKI와 기존 unsigned GRUB이
  **Access Denied**로 차단되고 커널이 실행되지 않음을 확인. 두 검사 통과, `success=true`.
- 최종 255.7 stub 시험에서는 초기 PE 섹션 중첩 경고가 나타나지 않았다.

증거는 `build/validation/20260910-r14/secureboot-*-result.json` 및 같은 이름의 로그에 보존했다.
개발용 키/변수/UKI는 WSL `/tmp/kiki-secureboot-lab/artifacts255`에만 있다.
재실행 시 기존 출력 디렉터리를 재사용하지 않고 새 이름을 지정해야 한다.

## 아직 하지 않은 작업

- Microsoft 신뢰 체인, shim 배포 승인, 실기기 키 등록.
- 배포용 키의 보관/회전/폐기 및 dbx/SBAT 취소 정책.
- 정식 ISO 및 설치된 OS의 서명 업데이트 통합.
- Secure Boot 환경에서 모듈 서명, lockdown, GPU 드라이버까지 포함한 전체 정책 검증.
- 실제 `kiki-os-test`에서 Secure Boot 활성화.

**현재 공개 ISO를 Hyper-V에서 Secure Boot ON으로 바로 설치할 수 있다는 의미가 아니다.**
DNS 정책과 일반 ISO 안정화를 마무리한 후 배포 신뢰 체인을 별도 결정해야 한다.

## 참고

2026-09-13: r15의 승인된 DNSSEC 기본값 변경 이후 별도 UKI를 다시 생성하여 검증했다.
`positive-r15`는 임시 설정 변경 없이 DNS·SecureBoot=1 포함 12개 검사를 통과했고,
`negative-r15`도 unsigned 차단과 커널 미실행 검사를 통과했다. 양쪽 모두 `success=true`다.
증거는 `build/validation/20260913-r15/`에 있다. 공개 ISO 자체의 Microsoft 신뢰 체인 통합이나
실제 Hyper-V Secure Boot 활성화까지 완료한 것은 아니다.

- [systemd v255 ukify 문서](https://github.com/systemd/systemd/blob/v255/man/ukify.xml)
- [virt-firmware upstream](https://gitlab.com/kraxel/virt-firmware)
- [QEMU UEFI 변수 보호 설명](https://www.qemu.org/docs/master/devel/uefi-vars.html)
