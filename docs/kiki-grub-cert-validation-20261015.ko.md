# KIKI OS GRUB UEFI 인증서 격리 검증 (2026-10-15)

## 범위

기존 Hyper-V VM, 호스트 UEFI 키, 배포 ISO, OpenStack 이미지는 변경하지 않았다.
Rocky-9 WSL의 `/tmp/kiki-grub-cert-F9JubR`에서만 30일짜리 개발용 RSA-3072
인증서와 개인키를 만들었다. 이 키는 배포용이 아니며 작업 공간이나 ISO에 넣지 않았다.

## 확인한 사실

- r26 추출 미디어의 `kiki/bootloader/EFI/BOOT/BOOTX64.EFI`는 x86-64 PE32+ EFI
  실행 파일이다. SHA-256은
  `a1ee056d22766805d1825fef98fdceee93794c0174c527253eb6789764c9ed71`이다.
- `objdump -p`의 PE Security Directory가 주소 0, 크기 0이다. 현행 GRUB EFI에는
  UEFI Authenticode 서명이 없다.
- 시험용 X.509 인증서는 `openssl verify`를 통과했다. 인증서의 공개키와 개인키에서
  추출한 공개키가 일치했고, `codeSigning` 용도가 확인됐다.
- 인증서 SHA-256 지문은
  `D1:EC:BD:56:FC:83:E6:32:41:AE:BD:92:6F:57:25:80:FF:B9:C3:65:F6:50:7A:D2:29:B6:E6:49:DB:8B:14:04`다.
  유효기간은 2026-10-15 02:06:33 UTC부터 2026-11-14 02:06:33 UTC까지다.
- 시험 디렉터리는 0700, 개인키는 0600이다. 인증서 공개 부분의 DER 파일을 생성했다.
- OpenSSL로 GRUB 파일 바이트의 SHA-256에 대한 **원시 RSA 서명**을 만들고
  검증했다. 같은 서명을 커널 파일에 적용한 음성 검사는 예상대로 실패했다.
- `tools/test_boot_lab_safety.py`의 세 안전장치 테스트가 모두 통과했다.

## 아직 검증하지 못한 것

원시 RSA 서명은 PE/COFF Authenticode 서명이 아니므로 펌웨어가 이 GRUB을
신뢰한다는 뜻이 아니다. 이번 실행에서는 `sbsigntools`와 `python3-virt-firmware`
RPM을 Rocky/EPEL 공식 미러에서 다운로드하려 했으나 HTTPS 연결이 시간 초과됐다.
따라서 `sbsign`/`sbverify`, OVMF `db` 등록, 서명된 GRUB 부팅 허용,
미서명 GRUB 거부를 **아직 실행하지 못했다**. 기존 배포 ISO의 Secure Boot는 계속
미지원이다. 인증서만 EFI 시스템 파티션에 복사해서도 신뢰 체인이 만들어지지 않는다.

## 재개 조건과 순서

1. 검증 가능한 배포판 RPM `sbsigntools`와 `python3-virt-firmware`를 시험 환경에서
   사용할 수 있게 한다. 패키지 서명 및 파일 해시를 확인하고, 호스트 설치 대신
   격리 SDK에 추출한다.
2. 새 시험 디렉터리에서 GRUB EFI에 PE/COFF 서명을 적용하고 `sbverify`로 검증한다.
3. 새 OVMF 변수 파일의 `db`에 시험 공개 인증서만 등록한다. 기존 변수 파일을
   덮어쓰지 않는다.
4. 복제한 설치 디스크와 별도 EFI 파티션을 사용해 SecureBoot=1에서 서명된 GRUB의
   펌웨어 허용과 미서명 GRUB의 차단을 각각 확인한다.
5. GRUB 이후 커널·initramfs·설정까지의 신뢰 체인을 별도로 검증한다.
   현행 ISO 빌드의 `--disable-shim-lock` 경로를 그대로 배포용 Secure Boot로
   간주하지 않는다.

2026-09-13에 성공한 별도 자체 서명 UKI 시험은
`secureboot-isolated-lab-20260910.ko.md`를 참고한다. 그 결과를 현행 r26 GRUB
EFI 또는 현재 배포 ISO의 Secure Boot 성공으로 대체하지 않는다.
