# r15 DNS 호환성 수정 (2026-09-13)

## 변경 및 보안 차이

사용자가 DNSSEC 기본값 해제를 승인했다. base-files 0.1.0-22와 인스톨러의
설치 대상 설정 생성기를 `DNSSEC=no`로 변경했다. 기존 사용자 VM 설정은 변경하지 않는다.
이 변경은 DNSSEC 구현 자체의 완전한 수정이 아니라 현재 환경의 호환성 문제를 피하는 기본 정책이다.

DNSSEC는 DNS 응답의 출처와 무결성을 서명으로 검증한다. DNS 조회 내용을 암호화하는 기능은 아니다.
서명된 DNS 데이터 위조를 탐지해야 하는 환경에서는 사용할 이유가 있지만, 인터넷 연결의 필수 조건은 아니다.
끄면 이 시스템의 로컬 resolver가 DNSSEC 서명을 검증하지 않는다. HTTPS 인증서 검증이나
UEFI Secure Boot 설정에는 영향을 주지 않는다.

r14 시험에서는 일반 DNS 서버에 직접 질의한 응답은 정상이었지만 resolved의 DNSSEC 처리에서
`failed-auxiliary` 오류와 조회 지연이 발생했다. 같은 시험 VM에서 DNSSEC를 끄면 즉시 조회됐다.
이 결과를 모든 NAT 환경에서 DNSSEC가 동작하지 않는다는 의미로 일반화하지 않는다.

## 관리자가 다시 켜는 방법

DNSSEC를 지원하는 resolver, 시스템 시각 및 네트워크를 먼저 확인한다.
`/etc/systemd/resolved.conf.d/90-local-dnssec.conf` 파일에 다음 설정을 저장한다.

```ini
[Resolve]
DNSSEC=yes
```

그다음 `sudo systemctl restart systemd-resolved`로 적용하고,
`resolvectl status`, `resolvectl query example.com`으로 조회와 검증 상태를 확인한다.
엄격한 검증 실패 시 DNS 조회가 차단될 수 있다. 되돌릴 때는 본인이 만든 해당 drop-in의
값을 `DNSSEC=no`로 바꾸고 서비스를 다시 시작한다. 다른 네트워크별 override가 있으면 함께 검토한다.

## 배포/검증 상태

수정 패키지와 r15 ISO를 새 스냅샷으로 빌드했다.

- base-files 0.1.0-22, 커널 6.1.187-2. 다른 패키지는 검증된 r14 구성을 유지한다.
- 부팅 서비스 회귀 10개, ISO 생성 회귀 35개, rootfs 계약 3개, 시험 도구 안전성 3개 통과.
- 실제 ISO 재추출에서 패키지 74개와 initramfs/rootfs 각 45개 선택 파일 검증 통과.
- 새 20GB 폐기형 디스크 설치 41.3초 완료.
- 직접 부팅: 커널, networkd, D-Bus, IPv4, 기본 경로, DNS, 실패 서비스 없음,
  swap, AI 콘솔, sudo, sudo 로그인 셸 11개 검사 통과(8.4초). 임시 override 없음.
- 실제 OVMF/설치 GRUB 부팅 화면을 검토하여 영문 AI 콘솔과 Ctrl+Alt+F2 로그인 화면 정상 확인.
  UEFI 도구는 자동 화면 수집만 하므로 원본 JSON의 `success=false`는 자동 판정 미실시를 뜻한다.
  화면의 수동 검토 결과를 이 문서에 별도로 기록했다.
- 별도 자체 서명 UKI: SecureBoot=1 및 DNS 포함 12개 검사 통과(10.6초).
  동일 신뢰 설정에서 unsigned UKI는 Access Denied로 차단, 커널 미실행 확인(65.5초).
- 증거: `build/validation/20260913-r15/`의 JSON, 로그 및 UEFI PNG 화면.

자체 서명 Secure Boot 시험용 UKI는 공개 ISO와 분리하며, 실제 Hyper-V 시험 시 공개 ISO의
Secure Boot는 OFF로 유지한다.

실제 사용자 Hyper-V VM을 재설치하거나 변경하지 않았다. 사용자가 수행할 최종 실환경 시험은 남아 있다.

## 전달 파일

- ISO: `E:\dev\KIKI-OS\dist\iso\kiki-stage3-v3-installer-x86_64-20260913-r15.iso`
- 크기: 4,154,488,832 bytes.
- SHA-256: `60a26cfb0389e3379253986a6a9277215e394e81b9ee274516e75c6167f7aeef`
- WSL 원본과 Windows 배포 폴더 복사본의 SHA-256 일치를 각각의 로컬 파일 시스템에서 확인했다.
- Hyper-V 2세대 / Default Switch 환경에서 새 ISO를 연결하여 최종 시험한다. Secure Boot OFF.
- 검증된 설치 시험 디스크/개발용 서명 키는 배포하지 않는다. GUI 설치에서 직접 설정한 계정을 사용한다.
- 기존 공개 r12 ISO와 해당 SHA-256 파일은 r15 검증 및 사용자 시험 VM 미연결 확인 후 Windows 휴지통으로 이동했다. 휴지통에서 복구할 수 있다. WSL 내부의 과거 후보/진단 자료는 이번 정리 대상이 아니다.

## 참고

- [systemd DNSSEC 설정](https://www.freedesktop.org/software/systemd/man/247/org.freedesktop.resolve1.html)
- [Fedora의 systemd-resolved 기본 정책 설명](https://fedoraproject.org/wiki/Changes/systemd-resolved)
