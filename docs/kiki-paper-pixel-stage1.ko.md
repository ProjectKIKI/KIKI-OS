# KIKI Paper Pixel 1단계 후보와 검증

작성일: 2026-11-05. [1~4단계 실행 계획](kiki-server-shell-roadmap.ko.md)의 1단계 작업 기록이다.
기존 설치기·패키지·ISO·일반 GNOME 프로필을 유지하고 별도 후보에 구현한다.

## 현재 상태

**최신: 배경·관리자 복귀·셸 내부 보완은 [r6 UI/UX 검증 기록](kiki-paper-pixel-ui-r6.ko.md)을 따른다.**
아래 r3 상태와 미적용 목록은 보완 전 이력이다. 현재 별도 후보 프로필은 r6으로 고정되어 있다.

- GNOME 운영 확장, 전용 세션, 분리된 사용자 설정 DB, 관리자 앱 범위의 픽셀 디자인을 구현했다.
- `paper-pixel-20261105-r3`의 225개 패키지 바이트를 조립하고 SHA와 Ed25519 서명을 검증했다.
- 전용 후보 VM에서 실제 로그인·라이트/다크·Polkit 사용자 인증·재부팅·일반 GNOME 복귀를 검증했다.
  화면 잠금·암호 잠금 해제도 확인했다. 최종 후보는 픽셀 운영 개요 화면으로 돌려놓았다.
  전체 Stage 3 릴리즈 완료와 새 ISO 설치 통과를 의미하지는 않는다. UI·런타임 잔여 항목은 아래에 기록한다.
- 4,039개 원본 파일과 원본 GA 디스크 체크포인트 체인 3개의 SHA가 이전 기록과 같음을 확인했다.
- 기존 ISO를 변경하거나 새 ISO를 만들지 않았다. 이번 VM은 기존 GA 설치 디스크의 독립 변환본이다.

## 픽셀 UI/UX 적용 범위 재점검 — r3 보완 전 이력

2026-11-05 추가 확인: 사용자의 왼쪽 Windows 화면·입력 장치를 사용하지 않고, SSH의 게스트 접근성
입력과 VMMS 가상 Enter로 기존 운영 세션의 잠금을 해제했다. `LockedHint=no`, Wayland 활성,
`--mode=kiki-ops`, 확장 ACTIVE, 관리자 서비스 active를 확인했다. 설치된 관리자 7개·세션 19개
파일의 SHA·권한도 r3 패키지 명세와 일치한다. **런타임 적용 확인과 전체 픽셀 디자인 완성은 별도다.**

| 영역 | 현재 적용 상태 | 남은 UI/UX |
| --- | --- | --- |
| 상단 운영 메뉴 | 픽셀 서버 아이콘·상태·관리자/로그/앱 연결, 색·테두리 적용 | 기존 GNOME 상태 아이콘은 기본 형태 |
| 관리자 앱 | Paper 색상, 사각형 창·카드·버튼, 단색 그림자 적용 | 둥근 기존 앱 아이콘, 기본 글꼴·레이아웃, 보조 창 중복 제목과 빈 완료 본문 |
| 바탕화면 배경 | 픽셀 SVG 경로는 선택됨 | 실제 1024×768에서는 모서리 장식이 보이지 않음. `picture-options=zoom`으로 1920×1080 배경의 좌우 장식이 잘리는 것으로 판단 |
| 빠른 설정·달력 | 팝업 외곽 색·테두리만 적용 | 내부 알약 형태 버튼·토글·아이콘은 기본 GNOME. 현재 빠른 설정 화면에서 직접 확인 |
| Activities·앱 목록·검색·도크 | 즐겨찾기 앱 지정 | 전용 픽셀 배치·내부 스타일은 구현하지 않음. 라이트 상단 대비 문제도 남음 |
| 알림·OSD·인증 대화상자 | 기본 GNOME 기능 재사용 | 전용 픽셀 디자인 없음. Polkit의 정상 인증 동작과 외형 적용을 구분 |
| GDM·잠금 해제 | 전용 세션 등록, 암호 인증 동작 | 기본 계정 아바타·암호 입력 UI 유지. 이번 잠금 해제 화면에서도 직접 확인 |
| Console·Nautilus·Settings | 기존 앱을 실행하는 연결 | 앱 내부의 전용 픽셀 스타일 없음. 기존 앱·호환성을 보존하는 현재 구현 범위 |
| 글꼴·아이콘·커서 | Adwaita Sans 11 / Adwaita Mono 11 / Adwaita 아이콘·커서 | 픽셀 전용 체계 없음. 현재 토큰도 시스템 한국어 산세리프와 글자 확대 존중을 명시 |
| 운영 데스크톱 배치 | 상단 메뉴와 GNOME 즐겨찾기 | 항상 보이는 운영 런처·바탕화면 서비스 위젯은 구현하지 않음 |

추가 UX 확인: 관리자를 최소화한 뒤 CLI의 `--page overview`를 호출하면 창이 전면으로 돌아오지 않고
GNOME의 “앱이 준비되었습니다” 알림만 표시되는 경우가 있었다. VM 가상 Alt+Tab으로 창을 복원했다.
메뉴의 관리자 호출도 현재 `Gio.Subprocess` 방식이므로, 최소화된 기존 창을 여는 경우의 Wayland 활성화
전달을 별도 보완·검증해야 한다. 원인 경로의 후보이며 모든 메뉴 호출의 실패로 일반화하지 않는다.

`tokens.json`은 자산에 포함되지만 현재 GTK/Shell CSS를 생성하는 공통 경로에는 연결되지 않았다.
따라서 공통 디자인 체계가 전체 화면을 자동으로 바꾸는 구조는 아직 아니다. 기능 검증 통과를
전체 테마 구현 완료로 표현하지 않는다. 이번 점검에서는 테마·패키지·인증 정책을 바꾸지 않았다.

후속 구현 우선순위는 배경 크롭·상단 대비 → 관리자 아이콘·보조 창·완료 상태 →
Shell 내부 컴포넌트·운영 런처 → 별도 GDM/잠금/Polkit 외형과 인증 회귀 검증 순서로 둔다.
기존 GNOME 앱의 기본 디자인 유지는 전체 픽셀 디자인 범위와 별도로 명시한다.

증거: `candidate/login-request-unlocked.json`, `candidate/pixel-scope-runtime.json`,
`candidate/pixel-scope-inspect.json`, `candidate/pixel-scope-installed-files.json`,
`candidate/pixel-scope-background-options.log`, `candidate/pixel-scope-desktop.png`,
`candidate/pixel-scope-wallpaper.png`, `candidate/login-request-current.png`,
`candidate/pixel-scope-restored.png`, `candidate/pixel-scope-audit.json`.
추가 앱 목록 캡처용 D-Bus `ShowApplications`는 기본 권한 검사로 거부됐다. 이 호출을 허용하도록
정책이나 Shell unsafe 모드를 바꾸지 않았으며, 해당 캡처를 앱 목록 검증 증거로 사용하지 않는다.

## 구현

| 대상 | 위치와 동작 |
| --- | --- |
| GNOME 확장 | `desktop/gnome/kiki-ops/`: GNOME Shell 50, GJS/St. 전용 `kiki-ops` 모드에서만 상태·실행 메뉴 제공 |
| 상태 조회 | 기존 `kiki-adminctl snapshot`을 비동기로 호출. 조회 실패·부분 응답을 정상/실패 0개로 처리하지 않음 |
| 메뉴 | 관리자, 실패 서비스·로그 화면, GNOME Console, Nautilus, incident-ai 연결, 상태 다시 확인 |
| GDM 세션 | `distro/sources/kiki-session-gnome-ops/`: 별도 세션·Shell 인스턴스·사용자 systemd 단위 |
| 사용자 설정 | 전용 dconf 프로필과 `kiki_paper_pixel` DB. 일반 GNOME의 기본 설정 파일은 수정하지 않음 |
| 디자인 | `assets/desktop/paper-pixel/`: 라이트·다크, 픽셀 서버 아이콘·배경, 사각형 테두리·단색 그림자 |
| 관리자 | `cmd/kiki-admin/pixel.h`: `KIKI_PAPER_PIXEL=1` 프로세스에만 적용. 고대비에서는 사용자 색상 유지 |
| 화면 진입 | `kiki-admin --page overview|packages|repositories|diagnostics`. 알 수 없는 값 거부 |
| 권한 | 기존 계획 검토·고정 Polkit helper·`auth_admin` 정책 유지. 셸은 서비스 재시작을 직접 실행하지 않음 |

확장은 GNOME 내부 메서드를 대체하지 않는다. 종료 시 타이머·상태 조회 프로세스·스타일 클래스를
정리한다. 로그인 세션 래퍼는 설정 환경을 적용하고 정상 종료 시 이전 사용자 서비스 환경으로 복구한다.
비정상 세션 종료와 복귀 후 환경 정리도 별도 검증 대상으로 둔다.

## 후보와 보존 기준

| 항목 | 내용 |
| --- | --- |
| 원래 프로필 | `distro/profiles/desktop-gnome.toml`, 기존 r4 후보 고정 유지 |
| 새 프로필 | `distro/profiles/desktop-gnome-ops.toml` |
| 새 전체 후보 | `dist/ki2/paper-pixel-20261105-r3` |
| 인덱스 SHA-256 | `1f3839c0be930d6076e057f01c45f69e708dda36eb7bcf6a3b4449b404a4ec05` |
| 실험 공개키 SHA-256 | `22122bb259fb1d61c21bf0db35c439cedbf631cb2f1c5cc8af07ef23e3a24f2f` |
| 관리자 | `kiki-admin 0.1.0-7`; 기존에 네이티브 빌드한 아카이브 바이트 재사용 |
| 관리자 아카이브 SHA-256 | `fb29c2fb0779514515b454fb81aacdbac3b8aa592b5656baced848aaa4eb7a2f` |
| 운영 세션 | `kiki-session-gnome-ops 0.1.0-3`; Linux 빌드 서버의 새 작업 경로에서 보완 소스 재패키징 |
| 운영 세션 아카이브 SHA-256 | `42702989218e838dc481e59fb74f7664a0ab8fcff5dfceacba1ac132e0ae2136` |

r1·r2는 덮어쓰지 않고 보존한다. r3는 r2의 실험 서명 키로 서명하며 키는 서버의 비공개 경로에만 둔다.
이번 재개 작업에서는 WSL이 `Wsl/Service/0x8007274c`로 응답하지 않아 강제 재시작하지 않았다.
관리자 C 바이너리를 다른 컴파일러로 재생성하지 않고, 검증한 SHA의 동일 바이트를 재사용했다.

## Hyper-V 검증 구성

- 원본 GA VM: `kiki-build-v1-ga-hyperv-20261101`. 전원 종료 상태와 디스크 체인 유지.
- 별도 기준선 VM: `kiki-paper-pixel-baseline-20261105`.
- 별도 후보 VM: `kiki-paper-pixel-candidate-20261105`.
- 두 복제본은 독립 VHDX이며 원본 디스크를 쓰기 대상으로 연결하지 않는다.
- 설치된 MAC 기반 네트워크 설정을 유지하므로 원본과 복제본 중 하나만 실행하도록 도구가 검사한다.
- 2 vCPU·고정 4 GiB·Hyper-V Gen2. Secure Boot 서명 검증은 이 작업의 범위가 아니다.

원래 프로필 후보는 224개 패키지지만 실제 GA 디스크의 설치 집합은 220개이며 커널·KI2 등 일부가
더 새롭다. 이를 낮추지 않기 위해 GA 설치 인덱스 SHA와 설치 패키지 SHA를 대조한 뒤 **검증용 thin
오버레이**를 사용했다. 첫 설치는 관리자와 운영 세션만 바꿨고, r2 갱신은 세션 패키지만 바꿨다.
이 오버레이는 기존 GA가 정확히 설치돼 있어야 하며 ISO 공급 저장소로 사용할 수 없다.

### GDM 세션 선택 보완

최초 로그인에서는 일반 `gnome-session@gnome.target`과 `gnome-shell --mode=user`가 실행됐다.
시험 계정에 `XSession=kiki-ops`만 지정한 것이 원인이었다. GDM 50은 AccountsService의
`Session`과 `SessionType`을 읽는다([공식 소스](https://github.com/GNOME/gdm/blob/50.0/daemon/gdm-session-settings.c)).
후보 복제 VM의 시험 계정에만 `SetSession(kiki-ops)`와 `SetSessionType(wayland)`을 적용했다.
실제 배포에서는 GDM 세션 선택 메뉴를 사용하며, 패키지 설치로 기존 사용자의 기본 세션을 바꾸지 않는다.

Windows의 왼쪽 작업 화면을 보호하기 위해 이후 검증은 SSH로 진행한다. 게스트의 정상 AT-SPI
암호 필드 입력은 가능했지만 현재 GNOME의 Cally `activate` 액션은 assertion 오류를 냈고,
접근성 Return 합성도 실제 PAM 제출로 이어지지 않았다. 후보 커널에는 `uinput` 모듈도 없다.
이 제약 때문에 첫 전용 로그인 제출은 사용자의 VM 내부 Enter 입력으로 확인했다. 이후에는
Hyper-V의 VMMS 가상 키보드 API를 사용했다. 이는 Windows 창·SendInput·클립보드·호스트 포커스를
사용하지 않고 후보 Linux VM의 가상 키보드에만 Enter를 전달한다. 암호는 기존 비공개 시험 설정에서
SSH stdin을 통해 정상 게스트 암호 필드에만 입력하고, GDM·Polkit의 PAM 인증을 그대로 통과했다.

### r3 런타임 보완

r2의 DB 이름 `kiki-paper-pixel`은 dconf writer의 D-Bus 객체 경로에 사용할 수 없는 하이픈을 포함했다.
실제 설정 저장이 대기하고 Shell에 객체 경로 assertion이 기록됐다. r3는 `kiki_paper_pixel`로 바꾸고
이 이름의 회귀 검사를 추가했다. 라이트 패널 버튼의 글자색을 명시해 대비를 복구했으며, 확장 재활성화
직전 조회의 비동기 콜백이 새 조회의 타이머·표시를 정리하지 않도록 실행 세대를 구분했다.
기존 네이티브 관리자 바이트는 그대로 유지했다.

## 검증 증거와 미완료 항목

결과 경로: `artifacts/server-shell/20261105-stage1/`.

| 증거 | 내용 |
| --- | --- |
| `baseline-audit.json` | 기존 r4의 Ed25519 서명, 224개 패키지 SHA·파일 명세, 207개 런타임 의존성 |
| `baseline/runtime-validation.json` | 독립 GA 복제 VM의 220개 설치 SHA, D-Bus·실패 유닛·관리자 상태 |
| `baseline/ui-test.log`, `baseline/overview.png` | 기존 관리자 네 화면·검색·검토 취소·작은 창·작업 중 닫기 보호 |
| `candidate-build-r2.json` | 225개 후보·208개 런타임 의존성, 새 두 패키지의 파일 명세와 SHA |
| `candidate-build-r3.json`, `candidate/final-archive-audit-r3.json` | 최종 r3 전체 공급·Ed25519·225개 SHA와 208개 런타임 의존성 |
| `candidate/install-r2.log` | 서명·설치 전 상태·변경 계획 검사 후 세션 r2만 갱신, 기존 220개 패키지 유지 |
| `candidate/normal-before.json` | 일반 GNOME 세션 파일·사용자 설정의 비교 기준 |
| `candidate/final-archive-audit.json` | r2의 225개 아카이브 SHA·Ed25519 서명 재검증과 변경 패키지 파일 명세 검사 |
| `candidate/installed-pixel-files.json` | VM 내 관리자 7개·운영 세션 19개 파일의 SHA·권한이 패키지 명세와 일치 |
| `candidate/installed-pixel-files-r3.json` | 최종 설치 r3의 동일한 파일 SHA·권한 검사 |
| `preservation-after.json` | 원본 4,039개 파일의 SHA 동일 |
| `original-vhd-sha-after.json` | 원본 디스크 체인 3개 SHA 동일 |
| `original-vhd-sha-final.json` | 재부팅·복구 검증 중 원본 체인 3개 최종 SHA 동일 |

실행한 회귀 검사는 기존 Linux 관리자 테스트 14개와 입력/보존 경계 테스트 4개다.
Windows에서 발생한 관리자 테스트의 아키텍처·파일 잠금 차이는 Linux 재실행 결과와 구분한다.
정적 JS 모듈·Python 문법 검사도 통과했다. 사용자 세션이 없는 상태의 첫 systemd 검증에서 나온
private socket 안내는 통과로 기록하지 않았다. 이후 별도의 임시 런타임을 지정한 정적 단위 검증은
종료 코드 0·오류 출력 없음으로 통과했다. 이는 실제 로그인·사용자 서비스 실행 검증과 구분한다.

다음은 실제 VM 결과다. 묶음 판정과 파일별 SHA는 `candidate/final-validation.json`에 기록한다.

- [x] 전용 세션의 실제 GDM 암호 로그인, 확장 활성화와 관리자 자동 실행.
- [x] 라이트·다크·고대비·글자 125% 확대와 실제 GTK/Wayland 화면. 시험 후 접근성 값 복구.
- [x] 운영 메뉴의 진단 페이지 연결, 터미널·파일 앱 실행. 관리자 자동 실행과 CLI 페이지 전달도 확인.
- [x] 시험용 실패 서비스의 GUI 계획 검토·실제 Polkit 사용자 인증·재시작·systemd 결과 확인. 완료 창 본문 문제는 아래에 별도 기록.
- [x] 확장 INACTIVE·ACTIVE 전환과 비활성화 중 관리자 독립 실행.
- [x] 재부팅 후 전용 세션 재로그인, 일반 GNOME 복귀와 설정·환경·단위 정리.
- [x] 정상 화면 잠금 후 암호 인증으로 해제. `LockedHint=no`, ScreenSaver 비활성 확인.

실제 인증·복구 증거는 `candidate/recovery-validation.json`이다. 시험용 서비스의 의도적인 실패 후
GUI의 고정 helper가 실제 Polkit 암호 인증으로 실행됐고 `Result=success`, `ExecMainStatus=0`을 확인했다.
서비스와 시험 flag는 정리했으며 journal은 보존했다. 실제 운영 서비스는 재시작하지 않았다.

`candidate/runtime-reboot-login.json`은 새 boot ID의 `--mode=kiki-ops`, 확장 ACTIVE, 관리자 active,
시스템·사용자 실패 유닛 없음을 기록한다. `candidate/runtime-standard-recovery.json`은 일반
`--mode=user`, 픽셀 환경변수 없음, 전용 확장 비활성, 관리자 자동 실행 유닛 inactive를 기록한다.
일반 GNOME에서 Console·Nautilus·관리자 실행 시에도 픽셀 환경변수는 없었다.
운영 세션 전후의 일반 dconf/user와 GNOME 세션 파일 SHA는 동일하다.

확인한 한계는 다음과 같다. Stage 3 전체 완료나 새 ISO 설치 통과로 확대 해석하지 않는다.

- 기존 관리자 완료 창은 명령 stdout이 없으면 빈 본문을 표시하고 보조 창 제목 표시줄도 중복된다.
  복구 성공 자체는 UI의 실패 목록 제거와 systemd·Polkit journal로 확인했다. 후속 관리자 UI 보완이 필요하다.
- 라이트 모드의 Activities 화면에서는 일부 기본 상단 표시 색상이 다시 밝아져 대비 조정이 필요하다.
  일반 운영 화면의 상단 대비 보완과 구분한다.
- 기본 HTTPS 브라우저가 없어 incident-ai 웹 화면은 열리지 않는다. 운영 메뉴 실행 후 브라우저 연결 안내가
  Shell journal에 기록됨을 확인했다. 브라우저 설치·기본 앱 선정은 남아 있다.
- 기존 GNOME 런타임의 portal Inhibit, Gst typelib 누락, iso-codes 빌드 SDK 경로 참조와
  Hyper-V 소프트웨어 렌더링/EGL 경고는 별도 런타임 보완 과제다. 이번 후보를 GPU 가속 통과로 표시하지 않는다.
- 새 후보 ISO는 만들지 않았다. 검증 대상은 독립 GA 설치 디스크 복제본에 새 두 패키지를 적용한 환경이다.
- Hangul 엔진 파일과 IBus 엔진 등록은 확인했지만 실제 한글 조합 타이핑은 아직 검증하지 않았다.
  SSH에서 `WAYLAND_DISPLAY` 없이 실행한 첫 IBus 조회 실패는 엔진 누락으로 판정하지 않는다.

## incident-ai 연결

기본 주소는 사용자가 제공한 `https://incident-ai.lab.terminal-lab.kr/`이다.
호스트에서 HTTPS 200 응답을 확인했다. 사용자 설정은 `~/.config/kiki/incident-ai.json`,
시스템 기본값은 `/etc/kiki/incident-ai.json`의 `url`로 읽는다.

HTTPS 기본 주소만 허용하고 인증 정보·쿼리·fragment·제어 문자를 거부한다.
로그·토큰·사용자 정보는 URL로 전송하지 않는다. 기존 GNOME 기준선에는 HTTPS 기본 브라우저가
없으므로 브라우저 미설치 안내와 실제 웹 화면 접속을 구분한다. 브라우저 설치 완료로 표시하지 않는다.

## 실행 도구

- `tools/ki2pixelcandidate.py`: 기준 감사, 새 후보 빌드, 세션 보완 재패키징, GA 전용 오버레이, 보존 SHA 대조.
- `tools/hyperv_pixel_lab.ps1`: 원본이 꺼진 상태에서 독립 VM 생성·식별자 검사·한 번에 한 복제본 실행.
- `tools/ki2pixelguest.py`: 전용 VM ID·NIC·IP·SSH 호스트 키를 확인하는 시험 전송 도구.
  기존 비공개 시험 계정 설정을 읽으며 암호·개인키·인증 DB를 보고서에 복사하지 않는다.

검증 완료 후에도 새 후보를 원래 프로필·기본 로그인·정식 릴리즈로 자동 승격하지 않는다.
