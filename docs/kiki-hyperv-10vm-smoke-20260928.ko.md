# Rocky-9 WSL 및 KIKI OS Hyper-V 10대 시험 (2026-09-28)

## 범위

- Rocky Linux ISO는 사용하지 않았다. 기존 Rocky-9 WSL에서 KIKI KI2 대상 ABI
  테스트(`systemd-journal-gatewayd`, `systemd-journal-transport`) 2개와
  `systemd-journal-gatewayd`의 임시 루프백 HTTP `/machine` 응답 시험 1개가 통과했다.
  이는 KIKI VM의 실제 systemd 소켓 단위나 원격 업로드 TLS 검증이 아니다.
- Hyper-V 호스트에 `kiki-iso-lab-01`부터 `10`까지 별도 Generation 2 VM을
  `F:\hyper-v\kiki-iso-lab-20260928`에 만들었다. 각 VM은 별도 16GiB 동적
  VHDX와 기존 `kiki-stage3-v3-installer-x86_64-20260928-r20.iso`를 사용한다.
  캡처는 `artifacts/hyperv-lab`에 있다. 종료 시 10대 모두 Off다.
- ISO는 이번 KI2 패키지 재빌드보다 앞서 생성된 r20이다. 따라서 이번 VM
  부팅 결과가 새 `kiki-installer-gtk` 등 패키지의 ISO 통합 검증을 뜻하지 않는다.

## ISO GUI 부팅 결과

| VM | 조건 | 관찰 |
| --- | --- | --- |
| 01 | 2GiB, 2 vCPU, Default Switch | GUI 인스톨러 디스크 선택 화면 |
| 02 | 1GiB, 2 vCPU, Default Switch | 90초에도 검은 화면; 원인 미확인 |
| 03 | 4GiB, 2 vCPU, Default Switch | GUI 인스톨러 디스크 선택 화면 |
| 04 | 2GiB, 1 vCPU, Default Switch | GUI 인스톨러 디스크 선택 화면 |
| 05 | 2GiB, 4 vCPU, Default Switch | 90초에 GUI 인스톨러 디스크 선택 화면 |
| 06 | 2GiB, 2 vCPU, NIC 연결 없음 | GUI 인스톨러 디스크 선택 화면 |
| 07 | 2GiB, 2 vCPU, StaticNATSwitch | 90초에 GUI 인스톨러 디스크 선택 화면 |
| 08 | 2GiB, 2 vCPU, internal switch | 90초에 GUI 인스톨러 디스크 선택 화면 |
| 09 | 2GiB, 2 vCPU, Secure Boot On | ISO 부팅 실패 후 PXE 시도 화면 |
| 10 | 2GiB, 2 vCPU, 동적 메모리 1–4GiB | GUI 인스톨러 디스크 선택 화면 |

GUI 표시까지만 시험했다. 디스크 선택 이후 설치, 재부팅, 네트워크 DHCP,
로그인, journal 서비스 활성화는 아직 검증하지 않았다. VM 09의 PXE 화면만으로
서명 부재가 단독 원인이라고 확정할 수는 없지만, 이 ISO는 Secure Boot On에서
부팅되지 않았다. VM 02의 검은 화면 역시 메모리 부족 여부를 추가 확인해야 한다.

## 재현 및 후속

- `tools/hyperv_iso_lab.ps1`은 기존 시험 VM만 부팅·캡처·종료한다. 사용자
  `kiki-os-test`와 `crc` VM은 변경하지 않는다.
- 최신 KI2 네 패키지를 서명 저장소와 새 ISO에 반영한 뒤 같은 매트릭스로
  다시 시험해야 한다.
- VM 02의 부팅 로그 및 1GiB 최소 메모리 요구를 조사하고, 별도 VM에서
  실제 설치·재부팅·저널 소켓·TLS 전송을 검증해야 한다.
