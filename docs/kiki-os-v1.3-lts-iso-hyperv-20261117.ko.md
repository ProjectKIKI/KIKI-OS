# KIKI OS v1.3 LTS 후보 설치기 — 새 ISO·Hyper-V 실설치 검증

작업: 2026-11-16 시작, 2026-11-17 완료 (한국 시간).

**판정: 후보 설치기를 넣은 새 ISO 생성, GUI→TUI→CLI 폴백, 오프라인 GUI 설치,
ISO 분리 후 부팅, 정상 GDM 암호 로그인·Wayland 세션, 재부팅 후 재로그인 통과.**
GNOME+Hyper-V 구성에 대한 결과다. v1.3 GA 승격, 6.12 커널 전환, 전체 OS의
x86-64-v2 인증 또는 업데이트·복구 전체 인수가 끝났다는 뜻은 아니다.

## 산출물과 입력

| 항목 | 값 |
|---|---|
| 로컬 증거 경로 | `artifacts/kiki-v1.3-lts/20261116-stage2-iso` |
| 새 ISO | `kiki-v13-installer-r29-20261116.iso` |
| ISO 크기 | 1,379,115,008바이트 |
| ISO SHA-256 | `1707c31eb18815f587dc52650346e4b9bbc8a448def09f9229f6ff94403f3b45` |
| 후보 설치기 | C/GTK4 `kiki-installer-gtk-0.1.0-29.x86_64.ki2` |
| 설치기 SHA-256 | `ae62cd08f0ab10c778d2117901efae6593d39da2c8f6bdb36a5f65e9eb13911e` |
| 커널 | 보존 기준선 `linux-6.1.187-4`, 실행 버전 `6.1.187-kiki-vm` |
| GNOME/GDM | GNOME Shell 50.4-6 / GDM 50.2-4 |
| 공용 GTK | GTK 4.22.4-2 / Libadwaita 1.9.3-2 / VTE 0.84.1-1 |
| ISO 패키지 | 236개, 모두 실물 SHA·페이로드 명세 확인 |
| 실제 설치 집합 | `desktop-gnome` + `vm-hyperv`, 216개 |
| 저장소 서명 | 새 독립 Ed25519 후보 키, 서명·인덱스 정합성 통과 |

서버 산출물은 다음 별도 경로에 있다.

`/build-kikios/kiki-build/candidates/installer-v13-iso-20261116-r1`

서버의 완성 ISO와 다운로드 후 재구성한 로컬 ISO의 전체 SHA를 대조했다.
SFTP·스트림 전송 조각은 전체 파일 SHA 확인 전에는 VM에 연결하지 않았다.
후보 서명 개인키는 서버의 격리된 `keys` 디렉터리에만 두며 ISO·공개 증거에 넣지 않았다.
저장소 서명과 Secure Boot는 다르다. 실제 시험은 **UEFI·Secure Boot Off**다.
BIOS 부팅 카탈로그는 확인했지만 BIOS 방식 디스크 설치를 시험한 것은 아니다.

소스는 1단계의 `source-attempt7.tar`와 `candidate-inputs.json`을 기준으로 복사했다.
새 ISO의 내부 빌드 커밋은 Git 아카이브 작업본이어서 `unknown`으로 표시된다.
정확한 소스 아카이브·입력 파일 SHA와 설치기 런타임 명세의 기준 커밋은 별도 증거로 고정돼 있다.
정식 RC에서는 ISO 내부에도 이 입력 식별자를 전달해야 한다.

## 실제 VM과 조작 경계

- 설치 VM: `kiki-v13-installer-r29-20261116`.
- VM ID: `9b2034c5-244a-4d7e-93e9-d263ed98d790`.
- Hyper-V Generation 2, 4GiB RAM, 2 vCPU, 새 동적 32GiB VHDX 한 개.
- 기존 VHDX·차등 디스크·설치된 GNOME VM은 연결하거나 시작하지 않았다.
- 원격 화면 앱·호스트 마우스·키보드·클립보드를 조작하지 않았다.
  VM ID를 검사한 Hyper-V 가상 입력 API와 VM 전용 직렬 포트만 사용했다.
- 자동 GUI 부팅 확인용 VM은 `kiki-v13-default-boot-probe-20261117`이며,
  쓰기 디스크 없이 같은 ISO만 연결했다. 확인 후 이 진단 VM은 Off로 두었다.
- 설치 VM은 재부팅 검증 후 정상 GNOME 로그인 상태로 유지했다.

입력 API 참고: [Microsoft 가상 키보드](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-keyboard),
[VM 합성 마우스](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-syntheticmouse).

## 시험 순서와 결과

| 시험 | 실제 확인 |
|---|---|
| 기본 ISO 부팅 | 별도 무디스크 VM에서 메뉴 선택·키 입력 없이 GTK 언어 선택 화면 표시 |
| GUI 실행 | 설치 VM의 직렬 로그를 추가한 GUI 부팅에서 한국어/영어 GTK 화면 표시 |
| GUI→TUI | 설치 전 실제 GUI 닫기 버튼 클릭 → GUI 종료 코드 0 → 전체 화면 TUI 실행 |
| TUI→CLI | TUI `q` → 종료 코드 0 → 안전 CLI 메뉴 진입 |
| 폴백의 비파괴성 | 설치 요청 파일 없음, 새 `/dev/sda`에 파티션 없음 |
| GUI 설정 | 한국어·kr·Asia/Seoul, 새 `/dev/sda`, DHCP eth0, kiki 계정, GNOME+Hyper-V, AI off |
| 오프라인 설치 | VM NIC를 스위치에서 분리한 상태로 로컬 미디어만 사용, 216/216개 완료 |
| 재부팅 동의 | 완료 화면에서 ISO 분리 후 `확인 후 재부팅` 클릭, 직렬 로그에 명시적 승인 기록 |
| 설치된 디스크 부팅 | DVD 비운 상태, VHDX를 첫 부팅 장치로 지정, GDM 표시 |
| 첫 로그인 | 설치 때 만든 암호로 정상 GDM 로그인, `Service=gdm-password`, `Type=wayland`, `Active=yes` |
| 기존 앱 | GNOME Console과 Nautilus를 실제 실행, 사용자 D-Bus 활성화 동작 |
| 두 번째 부팅 | 정상 `systemctl reboot` 후 같은 암호로 GDM/Wayland 재로그인 |
| 유지 확인 | machine-id 동일, boot-id 변경, 패키지 216개 집합·기록된 SHA 동일 |

첫 설치 부팅 ID: `b047cb68-c709-41f5-8886-a6364773a2ae`.
두 번째 부팅 ID: `9fb0b4bc-ec4f-4e61-a69b-c26491d3cb8d`.

두 부팅 모두 root 잠금, 자동 로그인 비활성, graphical.target,
GDM·SSH·NetworkManager·D-Bus·logind·Hyper-V KVP/VSS 데몬 활성 확인.
실패한 시스템 서비스는 0개다. 설치된 216개 패키지의 DB SHA뿐 아니라
GDM·GNOME Shell·Console·Nautilus·GTK·Libadwaita·VTE 주요 파일 **7개의 실제 SHA**도
해당 원본 KI2 파일 명세와 직접 대조해 일치했다.

SSH는 VM의 IP·MAC을 Hyper-V에서 확인한 후, Console의 정상 sudo 인증을 거쳐
VM 전용 직렬 포트로 출력한 **공개 호스트 키**를 고정했다. 자동 키 수락을 사용하지 않았다.
시험 암호는 로컬 `guest-secret.json`에만 저장하며 로그·보고서·소스에 값이 없는지 확인했다.
이 파일에는 현재 Windows 사용자만 접근하도록 ACL을 설정했다. 암호는 ISO에 포함하지 않았다.

## 보존 재검증

| 대상 | 최종 결과 |
|---|---|
| 로컬 보호 파일 | 5,534개 경로 존재·크기·mtime 변경/누락 0 |
| 기존 제품 소스 | 16개 원본 파일 SHA 변경 0 |
| 기존 남은 ISO | 5개 전체 SHA 재계산, 모두 기존 값 일치 |
| 이전 승인 삭제 ISO | 22개 부재 유지, 복원·추가 삭제 없음 |
| 서버 보호 파일 | 15,208개 경로 존재·크기·mtime 변경 0 |
| 기존 설치기 release 28 | 서버에서 SHA 재계산, `efdcbea8d944cdece14d4000237bde0e51c6b2ed091858b86da23452ba7c7814` 유지 |
| 기존 VM | 5대 모두 Off, ID·디스크 연결 유지 |
| 빌드 웹 | 기존 서비스 4개 active, Git API·공개 HTTPS 로그인 HTTP 200 |

원본 전체 패키지를 다시 전수 재해시했다는 뜻은 아니다. 이번 ISO에 들어간 236개는
전체 SHA·페이로드 검사했고, 원본 보존 목록은 메타데이터 비교, 기존 ISO 5개와 원본
설치기·주요 소스는 위와 같이 실제 SHA를 다시 계산했다. 원본 저장소 인덱스·설치기·
패키지·ISO·GNOME 환경에 후보 파일을 덮어쓰지 않았다. Git 커밋·푸시·공식 채널 승격은 하지 않았다.

## 발견 사항과 남은 LTS 항목

1. Hyper-V의 빠른 `TypeText`/순간 키 입력에서 누락이 있었다. 시험 도구를 키 누름·해제와
   대기 간격이 있는 방식으로 바꿔 실제 계정 생성·GDM·sudo·SSH 인증까지 확인했다.
   Alt+F4 한 번의 무반응을 키보드 장애로 판단하지 않는다. 실제 닫기 버튼으로 폴백을 검증했다.
2. 중간 ISO 재시작에서 검은 화면을 한 번 관찰했으나 원인을 확정하지 않았다.
   새 무디스크 VM의 무입력 기본 부팅은 GTK 화면까지 통과했고, 설치된 OS의 두 부팅·로그인은 통과했다.
   RC 인수에서는 ISO 재시작 반복·실패 시 직렬 로그 수집을 추가한다.
3. 저장된 InstallPlan은 실제 대상·216개 패키지·AI off를 반영하지만 `source.channel`은
   레거시 `stage2-v2`, `generated_by`는 `kiki-stage1-tui`로 남는다. 실제 ISO 후보 채널·GUI 경로와
   추적 메타데이터를 맞추는 작업이 남았다. 패키지 SHA·실제 설치 결과 불일치는 관찰되지 않았다.
4. Hyper-V 관리 화면의 KVP/VSS 프로토콜 버전 경고는 남아 있다. 데몬 활성·IP 보고는 확인했으나
   VSS 백업·프로덕션 체크포인트의 호환성을 인증한 것은 아니다.
5. 6.12 LTS 정확한 패치·설정 평가와 전체 OS의 v2 제한 CPU 검증은 별도다.
   이번 ISO는 기존 6.1 기준선을 유지해 설치기 변경을 검증했다.
6. 서버 구성의 별도 신규 설치, TUI/CLI/무인 설치별 실제 설치 결과 대조,
   업데이트 중단·전원 차단·복구·Secure Boot·물리 서버 검증은 이 결과에 포함하지 않는다.
7. incident-ai 자동 수신·자동 채우기·자동 전송은 계속 보류한다. 이번 시험에서도 배포·활성화하지 않았다.

## 재개할 때 사용할 증거

- `validation-summary.json`: 요청 범위 최종 판정.
- `iso-result.json`, `iso-manifest.json`, `boot-catalog.txt`, `SHA256SUMS.txt`.
- `install-start.json`, `install-completed.json`, `serial.log`.
- `guest-first.json`, `guest-reboot.json`: 로그인·서비스·패키지 상태.
- `critical-files.json`, `critical-file-origins.json`, `critical-files-result.json`.
- `preservation-local.json`, `preserved-vms-after.json`, `server-preservation.jsonl`.
- `default-cold-boot.png`, `install-review.png`, `install-progress-mid.png`,
  `gdm-first-display.png`, `final-wayland-apps.png`.

1단계의 원래 증거는 덮어쓰지 않는다. [1단계 기록](kiki-os-v1.3-lts-stage1-installer-20261116.ko.md)과
함께 읽고, 다음 단계에서는 위 추적 메타데이터와 LTS 입력 기준선부터 정리한다.


## 2026-11-17 추적 메타데이터 및 보존 기준 후속

설치기 추적 메타데이터 보완과 실제 오프라인 설치·GDM/Wayland 검증을 별도 후보에서 완료했다. 사용자 승인에 따라 구형 미사용 ISO를 정리하고 최신 후보·직전 정상 복구용을 보존한다. 기존 패키지·설치기·GNOME 환경은 유지한다. 상세 SHA·보존 예외·검증 범위는 [후속 기록](kiki-os-v1.3-lts-installer-metadata-20261117.ko.md)을 따른다. 이 문서의 이전 검증 결과와 기준선은 당시의 역사 기록으로 남긴다.
