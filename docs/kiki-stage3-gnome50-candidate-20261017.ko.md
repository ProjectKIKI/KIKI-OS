# Stage 3 GNOME 50 로그인 후보 검증 — 2026-10-17

이 작업은 기존 설치기·원본 패키지를 유지하고 별도 후보에서 수행했다.
후보 디렉터리는 `dist/ki2/stage3-6.1.187-gnome50-candidate-20261017`이다.
최소 로그인 후보이며 배포 최종본으로 승인한 상태는 아니다.

## 보존 범위

- 원본 패키지 247개, 기존 ISO 및 고정 입력·메타데이터를 포함한 280개 파일의 SHA-256이 보존 기준과 일치했다.
- PNG 로더를 검증했던 기존 설치기 r19 실행 파일과 번들은 그대로 사용한다.
- 호스트 `/usr`와 기존 빌드 캐시를 변경하지 않고 WSL의 별도 SDK·Python 가상 환경에서 빌드했다.
- VM은 기존 디스크를 부모로 하는 후보 세션 VM과, 새 32GiB 디스크의 설치 검증 VM으로 구분했다. 원본 부모 VM 디스크는 변경하지 않았다.
- 테스트 계정 복구용 비공개 ISO는 배포용 `release-iso`에 포함하지 않는다.

## 수정한 실행 문제

| 문제 | 후보 수정 및 확인 |
|---|---|
| 대화형 Bash에서 잘못된 로캘을 사용하면 충돌 | Bash 5.2 공식 패치 37개를 적용해 5.2.37로 구성. GNU 서명 확인. 실제 사용자 PTY에서 잘못된 로캘과 위 화살표 히스토리 재실행을 검사해 종료 코드 0 확인 |
| 오프라인 부팅 시 네트워크 대기 | KIKI 네트워크가 명시적으로 OFF일 때만 wait-online을 건너뛴다. DHCP·고정 IP는 기존 대기를 유지한다. 실제 재부팅에서 실패 유닛 0개 확인 |
| 사용자 세션의 XDG_RUNTIME_DIR·D-Bus 누락 | PAM을 포함한 systemd 255.7과 Linux-PAM 1.7.2, Shadow 4.15.1을 구성. `systemd-user` PAM에 `pam_systemd`를 포함하고 사용자 D-Bus socket/service 제공 |
| UPower 샌드박스·사용자 네임스페이스 EPERM | 설치된 initramfs가 루트를 chroot만 하던 문제를 MS_MOVE 후 chroot로 수정. 사용자 네임스페이스와 UPower의 기존 PrivateUsers 설정을 유지한 채 정상 실행 확인 |
| GNOME 구성요소에서 빌드 SDK 경로 참조 | ELF RPATH, GJS 실행기, Mutter typelib, GWeather 위치 DB, GNOME Desktop 데이터 경로를 대상 `/usr` 경로로 수정 |
| `su` 호환 PAM 이름 누락 | `system-auth` include를 추가. 기존 `su`의 wheel 제한은 바이트 단위로 유지 |
| 확장된 ISO 인덱스 잘림 | 후보 설치 백엔드의 인덱스 읽기를 128KiB에서 4MiB로 확대. C 선택 배열과 Python 의존성 검증기의 한도를 512개로 통일. 검증된 178개 의존성 목록과 일치 확인 |
| 인덱스 필드 순서와 정적 설치기 호환 | `ki2repo.write_json`의 표준 정렬 형식으로 별도 인덱스를 생성하고 181개 모든 파일명 검색 및 아카이브 SHA 대조 |
| 보존한 GTK 서버 프로필의 추가 도구 | `socat` 원본 아카이브의 SHA를 유지해 별도 설치 저장소에 추가. 기존 네이티브 루트에서 실행·의존성·파일 충돌 검사 통과 |
| 설치 마지막 단계의 systemd-tmpfiles 실패 | 설치 대상에 `/proc`·`/dev`·`/sys`를 일시 마운트한 뒤 계정·캐시 준비를 실행하고 역순으로 해제. 해당 환경에서 준비 명령 종료 코드 0 확인 |
| Shadow의 지원되지 않는 기본 암호 방식 경고 | 실제 생성 암호는 PAM의 SHA-512임을 확인했다. 후보 설치 시 `login.defs`와 `chpasswd`의 방식을 명시적으로 SHA-512로 맞춰 DES 대체 경고를 제거 |

## 후보 패키지와 로그인 구성

GNOME Shell 50.4, Mutter 50.4, gnome-session 50.1, GDM 50.2를 구성했다.
공용 네이티브 스택은 GLib 2.88.3, GTK 4.22.4, Libadwaita 1.9.3,
GJS 1.88.1, mozjs 140.1.0 등을 사용한다.

기존 세션 VM의 네이티브 검증 구성은 178개다. 보존한 GTK 서버 프로필에 필요한 `socat`을
추가한 새 설치 대상은 179개이며, ISO에는 라이브 설치기 패키지 2개를 더한 181개가 있다.
설치기 번들 GTK/X11 런타임은 설치된 GNOME 공용 라이브러리 공급자로
사용하지 않는다. 런타임 의존성·파일 소유권 검사와 ELF 공급자 감사에서 미해결 항목은 0개다.
후보 저장소는 별도 Ed25519 키로 서명하고 공개키로 검증했다.

GDM의 내부 greeter 계정과 사람의 비밀번호 로그인을 구분한다.
일반 사용자는 PAM 비밀번호 인증을 거치며 자동 로그인과 root 그래픽 로그인은 허용하지 않는다.
Polkit은 sudo 관리자 그룹의 실제 인증을 사용한다.

## 실제 세션 VM에서 통과한 항목

- 잘못된 GDM 비밀번호 거절, 올바른 비밀번호 로그인.
- UID 1000 / seat0 / `Service=gdm-password` / `Type=wayland` / `Active=yes` 확인.
- GNOME Extensions의 GTK4·Libadwaita 창 실행.
- 그래픽 Polkit 비밀번호 대화상자와 승인 후 UID 0 명령 실행 확인.
- 로그아웃 후 두 번째 비밀번호 로그인.
- ISO를 제거한 디스크 단독 재부팅 후 세 번째 비밀번호 로그인.
- 사용자 D-Bus, logind, Polkit, UPower, 사용자 systemd 정상 실행과 실패 시스템 유닛 0개.
- 잘못된 로캘에서 대화형 Bash 히스토리 재실행 및 일반 사용자 네임스페이스 검사.

근거는 후보의 `validation/gnome-vm-runtime.json`,
`validation/desktop-clean-runtime.json`, `validation/desktop-root-elf-suppliers.json`과
`artifacts/gnome50-session-vm-20261017`의 실제 화면·직렬 로그에 저장했다.
이 세션 VM의 성공만으로 빈 디스크 설치까지 통과했다고 간주하지 않는다.

## 빈 디스크 설치 검증

별도의 새 32GiB 디스크 VM에서 **통과했다**. 첫 시도의 읽기 용량 문제,
GTK 프로필의 `socat`, 정적 설치기 인덱스 형식, 설치 마지막 단계의 가상 파일시스템
누락을 실제 설치에서 확인해 후보 입력에서 수정했다. 중간 후보 ISO는 보존하되 검증된 최종
후보 카탈로그에는 포함하지 않는다.

최종 r6 ISO는 수동 복구 없이 179개 설치 완료 화면에 도달했다. ISO를 분리하고 설치기의
재부팅 버튼으로 디스크만 부팅한 뒤, 한국어 GDM 비밀번호 로그인과 한국어 Extensions
GTK4·Libadwaita 창 실행을 확인했다. 콘솔 로그인·sudo PAM 인증과 그래픽 Polkit 인증 후
`id -u`의 0 출력도 확인했다.

실제 세션은 UID 1000, seat0, `gdm-password`, Wayland, Active=yes다.
GDM·시스템 D-Bus·logind·Polkit·UPower·user@1000은 모두 active이고 실패 시스템 유닛은 0개다.
일반 사용자 네임스페이스, 잘못된 로캘의 대화형 Bash 히스토리 재실행, 사용자 D-Bus,
관리자 암호 SHA-512 및 root 잠금, 명시적 OFF 네트워크 대기 건너뛰기까지 통과했다.
설치된 인덱스 SHA는 ISO의 서명된 공급 인덱스와 일치한다.

`systemd-analyze`는 kernel 307ms + userspace 3.504s, graphical.target 3.489s를 기록했다.
이는 펌웨어·GRUB·GDM 화면 준비 시간을 모두 합한 측정값이 아니다.
두 검증 VM은 결과 수집 후 정상 종료했으며 부모 원본 VM 디스크는 유지했다.

근거는 `validation/gnome-fresh-install-runtime.json`과
`artifacts/gnome50-install-vm-20261017`의 실제 화면·직렬 로그다.
검증된 표준 디렉터리는 `validated-candidate/{repo,packages/x86_64,iso}`다.
최종 ISO는 `kiki-6.1.187-gnome50-login-candidate-r6.iso`이며 SHA-256은
`b1c12568ee9fe551016c41ace853d8e7f872e2374358ea44aed0a46fe9b3ce26`이다.

## 남아 있는 배포 범위

- Mesa는 기존 검증 라이브러리와 일치하는 GBM 모듈을 사용한 bootstrap 패키지다. 전체 Mesa 네이티브 소스 빌드는 완료하지 않았다.
- gnome-settings-daemon은 현재 스키마·열거형만 제공한다. 전체 설정 데몬과 Settings 앱 제공 완료를 뜻하지 않는다.
- PipeWire·WirePlumber·GStreamer 화면 공유, Xwayland 및 GTK3 앱은 이번 검증 범위가 아니다.
- Extensions GTK4 앱은 검증했지만 터미널·파일·로그·시스템 감시 앱 전체의 패키징·실행 검증은 별도 단계다.
- Hyper-V의 최소 로그인 결과이며 실제 GPU·전원 장치·다중 모니터·오디오·보안 부팅 검증은 남아 있다.
- Hyper-V 소프트웨어 렌더링 경로의 EGL/Zink 경고와 RealtimeKit 부재 경고가 남는다. 화면·인증 성공과 경고 없는 전체 하드웨어 지원은 구분한다.
- 보존한 라이브 설치기에는 C 로캘 대체·라이브 세션 D-Bus 경고가 남지만 PNG 로더 오류는 없었다. 설치된 대상의 한국어 GNOME와 사용자 D-Bus는 별도 검증을 통과했다.
- 빌드의 Rust 1.94와 Meson 1.9.2는 격리했다. 호스트 C 빌드는 GCC 11.5를 사용했으며 GCC 14.4 대상 툴체인 완성을 주장하지 않는다.

따라서 `release_ready=false`를 유지한다. 기존 배포 저장소를 이 후보로 대체하지 않는다.

## 최종 재확인과 Stage 3 파이널 판정

r6 ISO로 완료한 실제 오프라인 설치·디스크 단독 로그인 기록을 다시 대조했다.
이번 재확인은 동일한 ISO의 SHA, 전체 181개 후보 아카이브, 원본 280개 파일,
공개키와 저장소 Ed25519 서명, 직렬 로그·화면·런타임 보고서의 연결을 검사한 것이다.
동일 ISO를 새 디스크에 다시 설치한 별도 시험으로 중복 계산하지 않는다.
모두 통과했고 설치 검증 VM은 종료 상태다.

판정은 **오프라인 설치·GNOME 로그인 후보 합격 / 운영 데스크톱을 포함한 Stage 3 파이널 보류**다.
실패 유닛 0개는 제공한 최소 구성의 결과이며, 아직 패키징하지 않은 기능까지 정상이라는 뜻은 아니다.

| 우선순위 | 남은 항목 | 완료 기준 |
|---|---|---|
| P0 | Mesa bootstrap을 네이티브 소스 빌드로 이관 | 기존 설치기 라이브러리에 의존하지 않는 Mesa·GBM·EGL 공급자를 고정하고, 소프트웨어 렌더링 및 지원 GPU에서 GTK·Mutter 실행 검증. EGL/Zink 경고의 원인과 지원 범위를 명시 |
| P0 | 운영용 GNOME 구성 완성 | 스키마만 있는 gnome-settings-daemon을 필요한 실제 데몬으로 구성하고 Settings 앱, 터미널·VTE, 파일, 로그, 시스템 감시 앱의 패키징·실행·권한·한국어 입출력 검증 |
| P0 | 시험용 프로필을 정식 설치 선택으로 분리 | 현재 후보는 `server-core`에 GNOME을 추가한다. 파이널은 기본 서버 설치와 선택형 GNOME/Wayland 운영 데스크톱을 분리하고, 각 설치 계획·의존성·부팅 목표를 검증 |
| P0 | 설치 백엔드와 빌드 경로를 재현 가능하게 정리 | 현재 통과한 인덱스는 정적 백엔드의 `file`→`name` 순서 제약에 맞춘 형식이다. 검증된 파일 매핑을 사용하는 방식으로 제약을 제거하거나 형식 변경을 차단하는 검증을 정식 빌드에 포함. 후보 레시피·잠금·소스 SHA·격리 도구를 새 환경에서 재빌드하고 설치 회귀 확인 |
| P1 | 툴체인 계획과 실제 빌드 기준 일치 | Rust 1.94·Meson 1.9.2 격리 결과와 GCC 11.5 호스트 사용을 구분해 기록. 앞서 계획한 GCC 14.4 대상 툴체인은 별도 완성·검증하거나 최종 기준 변경을 명시 |
| P1 | 지원 환경과 운영 회귀 검증 | OFF·DHCP·고정 IP·연결 끊김, 저장소 장애, 재부팅·로그아웃, 디스플레이·입력 장치 및 지원할 실기기/하이퍼바이저 범위를 정하고 확인. 네트워크 관리 주체는 하나로 유지 |
| P1 | 정식 배포 승격 | 위 항목을 통과한 산출물만 정식 서명·채널·설치 메뉴에 반영. 기존 설치기/원본 보존 SHA와 복구 경로를 유지하고 파이널 체크를 실행 |

기존 `systemd-networkd`를 유지할 때 GNOME Settings의 NetworkManager 전용 패널을
그대로 제공해 정상 작동한다고 표시하지 않는다. 기존 KIKI 네트워크 도구와의 역할을 정리하고,
지원하지 않는 패널은 비활성화하거나 지원 범위를 명시한다.

PipeWire·WirePlumber·화면 공유, Xwayland·GTK3, Bluetooth·색 관리·Secure Boot는
제공하기로 한 범위에 따라 추가 검증한다. 서버 운영 데스크톱의 파이널을 위해 모든 멀티미디어
기능을 반드시 포함할 필요는 없다. 작은 GTK 로컬 관리자와 incident-ai 연결은 별도 애플리케이션
작업으로 관리하며, 이번 OS 로그인 검증의 완료 조건과 혼동하지 않는다.

최종 재확인 근거는 후보의 `validation/current-artifact-recheck.json`,
`validation/original-preservation-current.json`, `validation/gnome-fresh-install-runtime.json`이다.
검증된 ISO·패키지는 계속 별도 `validated-candidate`에 두며 `release_ready=false`를 유지한다.
