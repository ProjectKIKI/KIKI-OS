# 선택형 GNOME 데스크톱

운영자 선택은 GNOME이다. GTK 설치기는 유지하고 서버 기본 설치에 GNOME을
강제로 포함하지 않는다. 현재 상태는 의존성 조사와 기반 패키지 구현이며 GNOME 제공 완료가 아니다.

## GNOME 50 Wayland 설치 목표 (2026-09-28)

사용자 선택에 따라 GNOME 50은 Xorg 런타임 그룹과 별개의 Wayland 세션으로
구성한다. 현재 서명된 r20 저장소에는 `gnome-shell`, Mutter, GDM,
`gnome-session`이 없으며 GUI 인스톨러에 GNOME 선택지를 표시하지 않는다.
`tools/ki2gnomereadiness.py`는 최소 핵심 패키지의 레시피·저장소 포함 여부를
검사해 현재 미준비 상태를 실패로 반환한다. 이 최소 검사를 통과해도 전체
의존성 폐쇄, 서명 검증, 격리 VM의 GDM→GNOME Wayland 로그인 검증이 필요하다.

다음 구현 순서는 GTK/그래픽 기반과 GJS, Mutter, GNOME Shell,
GNOME Session, GDM의 독립 KI2 패키지 구성이다. 이후 사용자 세션·입력·로그인
동작을 VM에서 확인하고, 그때 별도 `gnome-wayland` 그룹 및 GUI 선택 항목을 연다.
현재 Xorg 런타임만 선택해도 GNOME이 설치되는 것으로 표시하지 않는다.

### 서명 패키지 감사 (2026-09-28)

`tools/ki2gnomereadiness.py`로 r20 서명 저장소를 다시 검사했다.
`gnome-foundation.toml`의 26개 기존 KI2는 모두 존재하고, Ed25519
메타데이터 서명·인덱스 SHA-256·각 패키지 SHA-256 검증을 통과했다.
이 26개는 **기반 라이브러리**이며 GNOME 데스크톱 패키지가 아니다.
GNOME Shell, Mutter, GDM, GNOME Session, gnome-desktop,
gnome-settings-daemon, GJS, GTK, Mesa, PipeWire, WirePlumber의
레시피와 KI2가 모두 없어 GNOME 세션 생성·서명은 미완료다.

### 첫 GNOME 50 구성요소 패키지 (2026-09-28)

공식 `gnome-build-meta 50.4`에서 고정한 `gnome-backgrounds 50.0` 소스를
별도 KI2 레시피와 검증용 프로필로 빌드했다. Linux 파일시스템의
`/tmp/kiki-gnome-native`를 빌드 디렉터리로 사용했고, 이미지와 배경화면
선택 XML, 원본 `COPYING`을 담은 KI2 파일을 생성했다. 기존 r20 서명
저장소를 바꾸지 않고 `dist/ki2/gnome-candidate-01`에 패키지 2개의
후보 저장소를 구성했다. 기존 Stage 3 Ed25519 키로 메타데이터를
서명하고 공개키 검증 및 패키지 SHA-256 대조를 통과했다.

GNOME Session의 직접 의존성인 UPower 1.91.3도 동일한 후보에 추가했다.
공식 GNOME 빌드 메타데이터와 같은 버전의 Debian 원본 소스를 SHA-256으로
고정해 빌드했다. GLib·libgudev·libimobiledevice·polkit을 KIKI sysroot에서
연결했다. polkit ITS 번역 규칙을 sysroot gettext 경로로 지정해 빌드를
완료했다. 데몬·CLI·공유 라이브러리의 대상 로더 연결과 RPATH 부재,
서비스·D-Bus·정책·원본 라이선스 포함을 임시 sysroot에서 검증했다.
실제 전원 장치나 D-Bus 데몬을 이용한 동작 시험은 아직 수행하지 않았다.

이 후보는 배경화면과 전원 관리 구성요소를 제공하지만 GNOME Shell·GDM·Wayland 세션을
제공하지 않는다. 단독 설치 가능한 완전한 배포 채널도 아니며, GNOME
설치 메뉴와 ISO에 추가하지 않았다. 다음은 GTK·Mesa·PipeWire 등
세션 필수 라이브러리를 패키징하고 의존성 전체를 검증하는 작업이다.

기존 기반 프로필 전체 재빌드는 Windows 드라이브에서 glibc 압축 해제 중
파일 I/O가 지나치게 느려 중단했다. 기존 서명 파일과 패키지는 보존했다.
기반 패키지의 전체 네이티브 재빌드는 아직 수행하지 않았다. 인스톨러의
GNOME 메뉴와 새 ISO는 만들지 않았다.

## 확인한 소스 기준

### JPEG SIMD 빌드 도구 준비 (2026-09-09)

GTK 4.22.4 소스의 JPEG/TIFF/gdk-pixbuf/epoxy 의존성을 다시
확인했다. libjpeg-turbo 3.2.0 공식 배포 tar.gz를 확보하고 SHA-256을
gnome-desktop-sources.toml에 고정했다. JPEG 라이브러리는 아직
레시피 구현/빌드 완료 상태가 아니다.

현재 호스트에 nasm/yasm이 없어 SIMD 빌드를 위한 NASM 3.02-1
레시피와 assembler-foundation 프로필을 추가했다. BSD-2-Clause
라이선스 원문과 nasm/ndisasm을 패키지에 포함했다. 첫 빌드의 zlib.h
누락을 zlib 의존성 명시로 해결했다. 호스트 /usr에는 설치하지 않았다.
/tmp/kiki-nasm-NHCANxi7에서 빌드 종료 코드 0을 확인했다.

test_nasm_runtime 1개가 9.180초에 통과했다. 실제 패키지와 대상
로더를 임시 chroot에서 사용해 SSE pxor/AVX vpxor 등의 출력
기계어를 고정 기대 바이트와 비교했다. 역어셈블, 잘못된 명령의
오류 반환, 두 실행 파일의 로딩 및 RPATH/RUNPATH 부재도 검사했다.
생성한 SIMD 코드를 CPU에서 실행한 시험은 아니며 전체 NASM
upstream 시험도 실행하지 않았다. 독립 소스 서명 검증은 미수행이다.

```sh
KIKI_TEST_NASM=1 PYTHONPATH=tools python3 -B -m unittest test_nasm_runtime -v
```

다음 단계는 대상 NASM 실행 래퍼와 JPEG 라이브러리 구성이다.
이 개발용 패키지는 TUI11 ISO에 포함하지 않았다. 실제 ISO 시험용
VM 이름/접속 방법/초기화 가능한 디스크는 사용자에게 확인 요청했으며,
임의의 VM이나 디스크는 변경하지 않는다.

### 입력 라이브러리 공식 시험 실행 환경 (2026-09-09)

기존 빌드에서 공식 Meson 시험 27개를 실행했다. 23개가 통과했고
4개가 실패했다. x11/x11comp는 Xvfb가 없어 exit 99였으며,
Python 시험 두 개는 호스트 Python 3.9의 타입 문법 지원 부족과
대상 바이너리를 호스트 libc로 실행한 문제였다.

0002-python-test-exe-wrapper.patch로 두 Python 시험이
MESON_EXE_WRAPPER를 shlex로 해석해 하위 명령 앞에 전달하도록
수정했다. 대상 Python 3.12 래퍼를 시험 전용 PATH에 연결했다.
시험의 기대값이나 제품 라이브러리 코드를 바꾼 것은 아니다.

수정 후 X11 suite를 제외한 25개가 통과했다(Ok 25, Fail 0).
키 심볼, Unicode, 키맵/규칙 파싱, 상태, Compose, registry,
Python 도구 옵션 및 XF86Macro23 시험이 포함된다. Compose 시험은
upstream fixture를 사용하므로 시스템 Compose 데이터 제공 완료를
의미하지 않는다. 도구 시험 내부의 환경별 생략 가능 항목 및
upstream의 타임아웃 처리까지 실제 세션 기능 검증으로 해석하지 않는다.

레시피에 Python 빌드 의존성, 패치, 시험 전용 실행 환경을 기록했고
25개 시험을 패키징 전 필수 단계로 추가했다. X11 지원 자체는
계속 활성화한다. X11 시험 2개와 실제 GUI/VM 시험은 미완료이며
시험 대상에서 제외했다는 이유로 성공으로 계산하지 않는다.
전체 129개 레시피 구조 검증은 통과했다.

필수 시험을 연결한 실제 재빌드도 /tmp/kiki-xkb-nKMwr4Go에서
종료 코드 0으로 완료했다. 최종 testlog는 Ok 25, Fail 0이다.
그 안의 Python 도구 옵션 시험은 Ran 20 tests, OK (skipped=66)를
보고했다. 이 66개 생략 항목을 실행·통과 항목으로 계산하지 않는다.
해당 기록은 ISO 재빌드나 실제 데스크톱 세션 시험이 아니다.

### 키맵 입력 라이브러리 준비 (2026-09-09)

libxkbcommon 1.13.2-1을 keyboard-foundation 및 graphics-foundation에
연결했다. X11 라이브러리, Wayland 도구, xkbregistry를 활성화했다.
공식 태그 아카이브의 SHA-256을 고정했으며 독립 서명 검증은
수행하지 않았다. /tmp/kiki-xkb-nKMwr4Go에서 최종 빌드가 종료
코드 0으로 완료됐다. 라이선스 원문을 설치 패키지에 보존했다.

통합 과정에서 두 가지 실제 구성 오류를 수정했다.

- xkeyboard-config의 절대경로 호환 링크가 안전한 tar 추출에서
  거부됐다. 2.46-2로 올리고 ../xkeyboard-config-2 상대 링크로
  바꿨다. 추출 보호는 유지했다. 실제 패키지 추출 후 링크 해석까지
  추가한 test_keyboard_data_package가 2.714초에 통과했다.
- cross pkg-config가 확장한 sysroot 경로가 libxkbcommon의
  DFLT_XKB_LEGACY_ROOT에 들어갔다. KIKI 교차 빌드 패치로
  /usr/share/X11/xkb를 사용하도록 수정했다. 기본 데이터 경로는
  /usr/share/xkeyboard-config-2이며 확장/설정 경로도 명시했다.

test_xkb_runtime 1개가 11.771초에 통과했다. 실제 패키지를 임시
chroot에서 로드하여 한국어 키맵 컴파일, HNGL/HJCV의 Hangul 및
Hangul_Hanja 키 심볼, Shift에 따른 a/A 변환, 키맵 직렬화·재파싱,
존재하지 않는 레이아웃 거부를 확인했다. 라이브러리 로딩과
RPATH/RUNPATH 부재, 런타임 키맵 경로에 임시 sysroot 부재도 검사했다.

처음 경로 검사는 libc 시작 오브젝트의 기존 소스 진단 경로까지
검출했다. 이를 실제 키맵/설정 경로와 구분하도록 수정했다.
바이너리 전체에서 빌드 경로가 제거됐다는 의미는 아니다.

```sh
KIKI_TEST_XKB=1 PYTHONPATH=tools python3 -B -m unittest test_xkb_runtime -v
```

upstream 테스트는 빌드했지만 전체 실행은 아직 하지 않았다.
Xvfb/xkbcomp가 없어 X11 연동 시험도 미수행이다. Compose 로케일
데이터와 실제 한글 조합 입력기, 물리 키보드/Wayland 세션 시험은
남아 있다. GTK/GNOME 통합, ISO 재빌드와 VM 시험 역시 미완료다.

### XCB 통신 라이브러리 준비 (2026-09-09)

libxcb 1.17.0-1을 x11-foundation에 추가했다. 공식 배포 tar.xz의
SHA-256을 고정하고 대상 Python 3.12/xcbgen, xorgproto 및
libXau로 빌드했다. /tmp/kiki-xcb-bqUna4J6에서 종료 코드 0으로
완료됐다. XKB와 DRI3를 명시적으로 활성화했으며 나머지 확장은
upstream 기본값을 따른다. HAVE_SENDMSG와 USE_POLL을 확인했다.
설치 라이브러리 RPATH/RUNPATH 부재와 라이선스 원문을 보존했다.
독립 소스 서명 검증은 수행하지 않았다.

test_xcb_runtime 1개가 10.641초에 통과했다. 실제 패키지의
공유 라이브러리 25개를 임시 chroot의 대상 로더로 로딩했다.
별도 socketpair/fork 시험 상대와 X11 초기 연결 및 GetInputFocus
32회 요청·응답을 교환하고 순서 번호와 응답 값을 확인했다.
리소스 ID 할당, DISPLAY 문자열 파싱과 잘못된 문자열 거부,
잘못된 파일 디스크립터 연결 오류도 확인했다.

첫 시험은 응답 C 구조체(12바이트)를 전송 프레임(32바이트)과
혼동했다. 패딩을 추가하고, 최종 응답 소비 전에 시험 상대가
연결을 닫지 않도록 수정한 뒤 통과했다. 제품 라이브러리가 아닌
시험 코드의 수정이다. 외부 X 서버나 사용자 인증 데이터는 사용하지
않았으며 실제 X 서버 상호운용성이나 그래픽 출력 검증은 아니다.

```sh
KIKI_TEST_XCB=1 PYTHONPATH=tools python3 -B -m unittest test_xcb_runtime -v
```

upstream Check 기반 단위 시험은 의존성 미구성으로 실행하지 않았다.
XDM 인증 확장(HASXDMAUTH)은 libXdmcp가 없어 비활성 상태이며
일반 libXau 인증 지원과 구분한다. GNOME 통합 전에 필요한 기능을
재검토해야 한다. libxkbcommon, 실제 GUI/VM 시험과 ISO 재빌드는
여전히 남아 있다.

### X11 인증 파일 라이브러리 준비 (2026-09-09)

libxau 1.0.12-1과 x11-foundation 프로필을 추가했다. 공식 X.Org
libXau 소스의 SHA-256을 레시피에 고정하고 대상 libc 및 xorgproto
헤더로 교차 빌드했다. /tmp/kiki-xau-ji5sVcjM에서 패키지 빌드가
종료 코드 0으로 완료됐다. 스레드 지원, 라이선스 원문 보존,
설치 라이브러리 RPATH/RUNPATH 부재를 확인했다. 독립 소스 서명
검증은 수행하지 않았다. 전체 카탈로그 127개 구조 검증도 통과했다.

공식 meson autest는 실행됐지만 Autest.c 마지막 반환식에 대입
`return (state = 1) ? 0 : 1;`이 있어 작업 실패를 검출하지 못한다.
따라서 그 종료 코드를 라이브러리 기능 정상의 증거로 사용하지 않는다.
해당 upstream 테스트 코드는 이번 변경에서 수정하지 않았다.

별도 test_xau_runtime 1개가 10.022초에 통과했다. 실제 패키지를
임시 chroot에 풀고 대상 로더로 실행하여 다음을 검증했다.

- NUL을 포함한 16바이트 가상 쿠키의 인증 파일 쓰기·읽기와 EOF
- XAUTHORITY 경로 적용, 일치하는 주소 조회 및 불일치 거부
- 잠금/해제 및 잠금 보조 파일 제거
- 마지막 쿠키 바이트를 제거한 파일의 읽기 거부
- 대상 libXau 동적 링크와 RPATH/RUNPATH 부재

첫 시험은 XauUnlockAuth 성공 반환값을 LOCK_SUCCESS로 잘못
가정했다. 원본의 boolean 성공값 1로 수정했다. 파일 절단 시험도
기존 stdio 버퍼를 피하도록 닫고 다시 열어 검증한 뒤 통과했다.
이 실패들은 시험 코드 수정 사항이며 제품 라이브러리 수정은 아니다.
호스트의 실제 Xauthority나 사용자 쿠키는 접근하지 않았다.

```sh
KIKI_TEST_XAU=1 PYTHONPATH=tools python3 -B -m unittest test_xau_runtime -v
```

시험은 Linux root 권한의 임시 chroot를 요구한다. 실제 X 서버
접속·인증, libxcb/libxkbcommon 연결, GNOME 통합 및 VM 시험은
아직 미수행이며 ISO도 이번 변경으로 다시 생성하지 않았다.

### X11/XCB 프로토콜 기반 준비 (2026-09-09)

libxkbcommon의 X11 지원을 끄지 않고 구성하기 위해 선행 의존성인
xorgproto 2025.1-1과 xcb-proto 1.17.0-1을 추가했다. 전용 프로필은
distro/profiles/xorg-protocols.toml이다. X 서버나 입력 라이브러리
구성이 완료됐다는 뜻은 아니다.

공식 X.Org 배포 소스를 사용하며 레시피에 SHA-256을 고정했다.
독립 서명 검증은 수행하지 않았다. xorgproto는 헤더 데이터 패키지로
런타임 의존성이 없고, 모든 COPYING-* 원문 37개를 보존한다.
xcb-proto는 대상 Python 3.12용 xcbgen을 설치하며 Python 런타임에
의존한다. 대상 libxml2의 xmllint로 upstream check-local과 동일한
src/*.xml 전체 스키마 검증을 수행하며 실패하면 패키징을 중단한다.

빌드 완료(각 종료 코드 0):

- xorgproto: /tmp/kiki-xorgproto-uuJYw9G9
- xcb-proto: /tmp/kiki-xcbproto-Ro55MebT

test_xorg_protocol_packages 2개가 2.538초에 통과했다. 설치 헤더
129개 중 원본 제공 헤더를 바이트 대조하고 생성 Xpoll.h는 별도
템플릿 치환 여부만 확인했다. 라이선스 37개 전부를 원본 대조했다.
XCB XML/XSD 33개와 Python 소스 7개는 목록과 바이트 전체를
대조했다. pkg-config 경로와 버전도 확인했다. 처음 시험은 정상적인
pkg-config 변수 경로를 리터럴 경로로 가정해 실패했으며, 변수 연결을
검사하도록 수정한 뒤 재실행했다. 패키지 경로 자체의 오류는 아니었다.

```sh
KIKI_TEST_XORG_PROTOCOLS=1 PYTHONPATH=tools python3 -B -m unittest test_xorg_protocol_packages -v
```

xorgproto의 공식 evdev-keysym-check는 호스트 Python libevdev
모듈이 없어 exit 77로 건너뛰어졌다(Ok 0, Fail 0, Skipped 1).
이를 통과로 계산하지 않는다. libXau/libxcb, libxkbcommon 및
Compose 로케일 데이터, 한글 입력기와 실제 입력 시험은 남아 있다.
이번 기반 패키지를 포함한 ISO 재빌드와 실제 VM 시험은 하지 않았다.

### 키보드 데이터 2.46 준비 (2026-09-09)

xkeyboard-config 2.46-1 레시피와 keyboard-data 빌드 프로필을 추가했다.
호스트 Python 3.9에서 strenum 모듈이 없어 첫 빌드가 실패했다.
빌드 전용 의존성으로 KIKI Python 3.12를 연결하고 기존 대상 실행
래퍼를 사용하여 해결했다. 호스트 Python 패키지는 변경하지 않았다.
데이터 패키지 자체의 런타임 의존성에는 Python을 추가하지 않는다.

/tmp/kiki-xkeyboard-82FYqc5P에서 빌드가 종료 코드 0으로 완료됐다.
test_keyboard_data_package 1개가 1.542초에 통과했다. 고정 소스
SHA-256, 한국어 symbols/kr 원문 일치, base/evdev 규칙 존재와
XML의 kr 등록, pkg-config 버전/경로, 라이선스 원문, 일반 파일
권한 및 소유권을 확인했다. 소스의 독립 서명 검증은 수행하지 않았다.

실제 데이터 경로는 /usr/share/xkeyboard-config-2이며 기존
/usr/share/X11/xkb는 그 위치를 가리키는 심볼릭 링크로 제공된다.
이후 libxkbcommon 구성에서도 이 경로를 일치시켜야 한다.

```sh
KIKI_TEST_KEYBOARD_PACKAGE=1 PYTHONPATH=tools python3 -B -m unittest test_keyboard_data_package -v
```

upstream pytest는 빌드 환경에 없어 실행되지 않았다. 이번 검증은
키맵 컴파일·실제 키 입력·한글 조합 입력기 검증을 대체하지 않는다.
libxkbcommon 및 GTK/GNOME 통합, 실제 VM 시험은 남아 있으며
이 변경을 포함한 ISO는 아직 다시 생성하지 않았다.

### Wayland Protocols 1.49 준비 (2026-09-09)

패키지 내용 검증: test_wayland_protocols_package 1개가 0.425초에
통과했다. 고정 소스 해시를 확인하고 배포 패키지 XML 58개의 목록과
바이트를 원본 stable/staging/unstable XML 전체와 대조했다. 생성 enum
헤더 64개의 목록·내용 존재, pkg-config 버전/경로, 라이선스 원문,
파일 권한 0644 및 root 소유권도 확인했다.

소스에 포함된 experimental/xx-fractional-scale-v2는 upstream의
experimental_protocols 테이블에 등록되지 않아 생성 헤더 대상이
아니다. 이를 명시적으로 검사하며 설치 누락으로 잘못 판정하지 않는다.
나머지 experimental 헤더는 upstream대로 포함하고 experimental XML은
upstream대로 설치하지 않는다. 헤더 바이트의 재생성 대조는 이 시험에
포함하지 않으며 생성물 C/C++ 검증은 앞선 공식 테스트 결과를 따른다.
graphics-foundation에 wayland-protocols를 연결했다.

```sh
KIKI_TEST_PROTOCOLS_PACKAGE=1 PYTHONPATH=tools python3 -B -m unittest test_wayland_protocols_package -v
```

최종 빌드 결과: /tmp/kiki-protocols-c3KVvFHM에서 1.49-1 패키지
생성이 종료 코드 0으로 완료됐다. 공식 meson test 결과는 Ok 191,
Fail 0이다. XML strict 스캔 및 프로토콜별 C99/C++ 생성물 테스트를
실행했다. 실제 로그에서 C++ 시험이 ki2-target-run을 통해 실행된
것도 확인했다. sanitizer 환경 변수 출력은 sanitizer 빌드를 수행했다는
뜻이 아니다. 설치 결과의 xdg-shell XML 존재를 확인했다. 패키지 전체
내용 대조와 GTK 통합, 실제 compositor/VM 시험은 별도로 남아 있다.

레시피 연결: wayland-protocols 1.49-1과 전용 시험 프로필을 추가했다.
빌드 전용 sysroot의 wayland-scanner를 대상 실행 래퍼로 교체하고
원본 ELF는 해당 빌드 디렉터리에 보존한다. 설치 패키지의 스캐너를
바꾸는 작업은 아니다. C/C++ 대상 교차 설정을 사용하고 공식
meson test가 실패하면 설치·패키지 생성을 진행하지 않도록 연결했다.
Wayland·linux-headers·libstdcxx는 빌드 의존성이며 프로토콜 데이터
패키지에는 런타임 실행 의존성을 추가하지 않았다.

123개 레시피 검증 통과. /tmp/kiki-protocols-c3KVvFHM에서 빌드를
시작했으며 이 기록 시점에는 빌드와 공식 테스트 완료를 확인하지
않았다. 생성 헤더·XML 설치 및 GTK 통합은 완료 후 별도로 검증한다.

후속 결과: Wayland 1.26.0-1 빌드가 종료 코드 0으로 완료됐다.
새 패키지의 test_wayland_runtime 1개도 9.750초에 통과했다. 소켓
요청·응답 64회, strict scanner 헤더·C 코드 생성, 생성 코드 컴파일,
잘못된 XML 거부를 다시 확인했다. Protocols 자체 빌드와 공식 전체
테스트, GPU 화면 출력은 아직 완료하지 않았다.

공식 릴리스의 wayland-protocols-1.49.tar.xz를 받았으며 로컬 SHA256은
ec4c8f74942d6dff7ace8b4ce4764f0ef9ff618a935d974ea77edee2ad240b14다.
meson.build에서 tests=true일 때 scanner >=1.25.0을 요구함을 확인했다.
tests/meson.build는 XML strict 스캔, 코드 생성, C99/C++ 헤더 빌드와
프로토콜 의존 코드 연결을 검사한다. 이 테스트는 아직 실행하지 않았다.

기존 Wayland 1.24를 1.26.0-1로 올렸다. 공식 소스의 로컬 SHA256은
64176eaa46e4969903e286f8e5ef8331affc17fdf03ac9b58381d2b23162b7a3다.
독립 서명 검증은 미완료다. 기존 target scanner 선택 패치의 문맥이
유지됨을 확인했고 /tmp/kiki-wayland126-rWAVr91V에서 빌드를 시작했다.
test_wayland_runtime의 버전 기대값도 갱신했다. 새 패키지 빌드 및
회귀 실행 결과는 아직 확인하지 않았으며 이전 1.24의 통과 결과와
구분한다. Protocols 패키지 레시피와 스캐너 래퍼 연결은 다음 단계다.

### Wayland 네이티브 빌드 연결 (2026-09-09, 검증 진행 중)

후속 런타임 결과: test_wayland_runtime 1개가 9.797초에 통과했다.
실제 패키지와 런타임 의존성을 임시 chroot에 추출하고 대상 헤더·
라이브러리에 연결한 C 프로그램을 실행했다. 외부 소켓 경로나 GPU
없이 socketpair로 클라이언트와 서버를 연결하여 wl_display.sync
요청·콜백 응답 64회를 확인하고 연결을 정리했다.

패키지 scanner 1.24.0으로 공식 wayland.xml에서 strict 모드의
클라이언트 헤더·서버 헤더·private C 코드를 생성했다. 생성 C 코드를
대상 헤더로 컴파일했고 DTD에 없는 요소를 포함한 XML의 실패 반환도
확인했다. graphics-foundation 개발 프로필에 Wayland를 연결했다.

```sh
KIKI_TEST_WAYLAND=1 PYTHONPATH=tools python3 -B -m unittest test_wayland_runtime -v
```

이 검사는 wl_surface/실제 compositor/GPU/키보드 입력 또는 공식 전체
테스트 실행이 아니다. ISO와 실제 VM 화면 검증은 여전히 미완료다.

후속 결과: /tmp/kiki-wayland-cpp-SkDTWZ2b 재빌드가 종료 코드 0으로
완료됐다. scanner·라이브러리 설치와 RPATH 검사도 통과했다. 공식
테스트 프로그램은 빌드했지만 실행하지 않았으므로 테스트 통과로
간주하지 않는다. 패키지 런타임 검증은 다음 단계다.

wayland 1.24.0-1 레시피와 wayland-foundation 프로필을 추가했다.
클라이언트·서버·cursor·EGL 라이브러리와 scanner, DTD 검증 및 테스트를
활성화했다. libffi/Expat/libxml2는 대상 패키지를 사용한다.
Meson 패치는 교차 빌드라도 exe_wrapper로 대상 바이너리를 실행할 수
있으면 같은 빌드의 scanner를 선택하도록 변경한다. 실행 불가능한
교차 환경의 기존 native scanner 경로는 유지한다.

첫 빌드 /tmp/kiki-wayland-84KRTqqy는 공식 tests/meson.build에서
C++ 컴파일러가 교차 파일에 없다는 오류로 종료됐다. 테스트를 끄지
않고 기존 C/C++ 교차 파일과 대상 CXXFLAGS를 연결했다.
/tmp/kiki-wayland-cpp-SkDTWZ2b에서 수정 후 빌드를 시작했다.
122개 레시피 검증은 통과했으나 패키지 빌드 완료, 스캐너 생성물,
클라이언트/서버 런타임 및 공식 테스트 통과는 아직 확인하지 않았다.
ISO와 실제 VM 검증 상태는 변경하지 않았다.

### Wayland 준비 및 libxml2 (2026-09-09, 빌드 성공)

후속 결과: test_libxml2_runtime 1개가 8.636초에 통과했다. 실제
libxml2 런타임 패키지를 임시 chroot에 추출하여 xmllint 버전 21504,
정상 DTD 검증, 한글 XPath 문자열 조회, 잘못된 DTD 문서의 종료 코드
3과 구문이 깨진 XML의 종료 코드 4를 확인했다. 고정 해시를 확인한
Wayland 1.24.0 소스의 protocol/wayland.xml도 동봉 wayland.dtd로
검증했다. 초기 테스트의 chroot PATH 및 예상 진단 메시지·코드는
실제 실행 결과에 맞춰 수정했다. 오류를 성공으로 처리한 것은 아니다.

```sh
KIKI_TEST_LIBXML2=1 PYTHONPATH=tools python3 -B -m unittest test_libxml2_runtime -v
```

이 시험은 전체 XML 적합성·보안 감사 또는 Wayland 클라이언트/서버
실행 검증을 대신하지 않는다. Wayland 스캐너 및 라이브러리 빌드는
다음 단계이며 GTK·GNOME·실제 VM 완료 상태는 변경하지 않았다.

공식 Wayland 1.24.0 릴리스 소스를 받았다. XZ 형식을 확인했고
로컬 SHA256은 82892487a01ad67b334eca83b54317a7c86a03a89cfadacfef5211f11a5d0536이다.
독립 서명 검증은 아직 수행하지 않았다. 소스에서 스캐너가 Expat을
사용하고 DTD 검증에는 libxml2가 필요함을 확인했다. 교차 빌드는
동일 버전의 빌드용 scanner 의존성을 별도로 조회하므로 스캐너 실행
경로를 명시해야 한다. Wayland 레시피 및 실행 검증은 아직 미완료다.

libxml2 2.15.4 공식 소스를 sha256sum 파일과 대조해 일치를 확인했다:
98087fd181d9070724f3fbc65c7377db03038eb92bd882374daff44940138821.
libxml2 레시피와 xml-foundation 프로필을 추가했고 121개 레시피
검증을 통과했다. 대상 sysroot, iconv, zlib와 DTD 검증을 활성화하고
/tmp/kiki-xml-Qy9bLCbi에서 빌드 종료 코드 0을 확인했다. xmllint 설치와
RPATH 검사도 통과했다. 정상/잘못된 DTD 실행 시험은 위 후속 결과를 참고한다.
Python 바인딩·readline·문서 생성은 이번 패키지에 포함하지 않는다.
MIT Copyright 파일을 설치하도록 구성했다. GTK·GNOME·ISO·실제 VM
완료 상태는 변경하지 않았다.

### Graphene 빌드와 GTK 필수 의존성 재확인 (2026-09-09)

후속 실행 결과: test_graphene_runtime 1개가 15.317초에 통과했다.
현재 레시피의 실제 패키지를 임시 chroot에 추출하고 해당 헤더와
라이브러리에 연결한 C 시험을 대상 로더로 실행했다. 이동 행렬의
예상 좌표, 역변환 왕복, 특이 행렬의 역행렬 실패 반환, 벡터 내적·
외적, 사각형 교차 영역 및 비교차 결과를 확인했다. 실제 라이브러리
로더 경로·RPATH 검사와 Graphene typelib의 Matrix/Vec3/Rect 타입
조회도 통과했다. graphics-foundation 및 gnome-foundation에 연결했다.

```sh
KIKI_TEST_GRAPHENE=1 PYTHONPATH=tools python3 -B -m unittest test_graphene_runtime -v
```

이는 제한된 수치 연산 통합 회귀 시험이며 모든 SIMD 경로, 공식 전체
단위 테스트 또는 GTK/VM 화면 검증을 의미하지 않는다.

Graphene 1.10.8-1 레시피와 graphene-foundation 프로필을 추가했다.
공식 GNOME 배포 서버의 sha256sum과 소스가 일치했다:
a37bb0e78a419dcbeaa9c7027bcff52f5ec2367c25ec859da31dfde2928f279a.
MIT LICENSE.txt를 패키지에 보존한다. 대상 sysroot·GObject·GIR를
사용하여 /tmp/kiki-graphene-FH8AG4ez에서 빌드 종료 코드 0을 확인했다.
Graphene typelib 설치와 라이브러리 RPATH/RUNPATH 검사도 통과했다.
대상 수치 연산 및 typelib 실행 회귀 검증은 위 후속 결과를 참고한다.

tests=true이지만 upstream tests/meson.build는 mutest-1을 선택적으로
찾으며 없으면 단위 테스트를 생성하지 않는다. 그러므로 빌드 성공을
공식 테스트 통과로 간주하지 않는다. mutest 및 실행 검증은 후속 과제다.

GTK 4.22.4 공식 소스를 다운로드했고 SHA256이 기존 고정 메타데이터의
51bd9f60c7d23a665a556c7364c21fb2e4e282566b3e7e092455e8f910330893과
일치했다. meson.build에서 GLib >=2.84, Pango >=1.56, HarfBuzz >=8.4,
Cairo >=1.18.2, Graphene >=1.10, GI >=1.84 요구를 확인했다.
추가로 gdk-pixbuf, TIFF/JPEG, epoxy, Linux libdrm 및 Wayland 경로의
wayland >=1.24·protocols >=1.44·xkbcommon이 필요하다. 기본 미디어
백엔드는 GStreamer >=1.24를 요구하며, 배포판은 WebM 지원을 제공하라는
upstream 안내가 있다. 단순히 옵션을 꺼서 GTK 완성으로 처리하지 않는다.
GTK 자체 빌드, GNOME 세션, ISO 및 VM 검증은 아직 완료하지 않았다.

### Pango 한글 대상 실행 검증 (2026-09-09)

test_pango_runtime 1개가 17.621초에 통과했다. 현재 레시피가 가리키는
실제 패키지와 의존성을 임시 chroot에 추출하고 대상 라이브러리에
연결한 C 프로그램을 대상 로더로 실행했다. 시험 글꼴은 기존 설치기
번들의 NotoSansCJK-Regular.ttc를 임시 루트에 복사했다.

- Pango 1.57.1, Noto Sans CJK 글꼴 선택 및 한글 샘플의 누락 글리프 0
- 한글 문장의 실제 크기 계산, 좁은 폭의 여러 줄 배치와 한 줄 말줄임
- 정상 한글 마크업 해석과 잘못 닫힌 마크업의 오류 반환
- dark-blue 배경에 Cairo 렌더링, 변경 픽셀 수 및 Cairo 오류 상태 확인
- PNG 생성 및 시그니처, Pango/PangoCairo/PangoFc/PangoFT2/PangoOT typelib 로딩

```sh
KIKI_TEST_PANGO=1 PYTHONPATH=tools python3 -B -m unittest test_pango_runtime -v
```

Pango를 graphics-foundation과 gnome-foundation 개발 프로필에 연결했다.
이 검사는 화면 육안 판독, 전체 글꼴/언어/복잡한 레이아웃, GTK UI 또는
실제 VM 시험이 아니다. PNG 시그니처 검사는 독립 디코더 검증을 뜻하지
않는다. 시험 글꼴 복사도 최종 GNOME 글꼴 패키지 구성을 대신하지 않는다.
네이티브 GTK 및 GNOME 세션 통합, ISO 재빌드와 실제 VM 검증은 남아 있다.

### Pango 레시피 및 HarfBuzz GIR 확장 (2026-09-09)

후속 결과: HarfBuzz 14.4.0-2 빌드가 종료 코드 0으로 완료되었고,
확장한 test_harfbuzz_runtime 1개가 16.940초에 통과했다. 실제 패키지
chroot에서 한글 11,172자의 완성형/분해형 글리프·advance 일치,
FreeType 자동 힌팅, 라이브러리·CLI ELF 의존성 및 RPATH 검사를
다시 수행했다. HarfBuzz typelib을 로드하여
aat_layout_has_positioning의 C 심볼도 확인했다.

초기 GIR 검사 실패는 잘못된 테스트 함수 선택이었다. version_string은
생성 GIR에 없고 blob_destroy는 introspectable=0으로 제외되어 있었다.
생성 GIR에서 조회 가능한 함수를 확인한 뒤 테스트를 수정했다.
단순 버전 문자열 확인은 직접 C 호출로 별도 유지한다. 전체 공식
HarfBuzz 테스트 실행이나 모든 바인딩 함수 검증 완료를 뜻하지 않는다.

Pango 1.57.1-1도 /tmp/kiki-pango-k0nb0nzh에서 종료 코드 0으로
빌드되었다. Cairo·Thai·Fontconfig 및 introspection 활성화를 확인했고
Pango/PangoCairo typelib 설치와 라이브러리 RPATH 검사도 통과했다.
Pango 대상 환경의 한글 레이아웃·렌더링 실행 검증은 아직 미완료다.
아래는 빌드 시작 당시의 경위이며 최신 결과는 이 문단을 따른다.

Pango 1.57.1 소스의 pango/meson.build를 확인한 결과 GIR 생성에
HarfBuzz-0.0 타입 정보가 필요하다. 기존 HarfBuzz release 1은 GIR가
꺼져 있었으므로 release 2에 gobject-introspection 의존성 및 대상
스캐너·컴파일러·실행 래퍼를 연결하고 introspection을 활성화했다.
/tmp/kiki-hb-gir-lx0W7YGA에서 실제 재빌드를 시작했고 컴파일 진행을
확인했다. 이 기록 시점에는 빌드 성공이나 타입 정보 실행 검증이
완료되지 않았다. 이전 release 1의 한글 회귀 결과를 release 2의
검증 결과로 간주하지 않는다.

Pango 레시피와 pango-foundation 프로필을 추가했다. Cairo·FreeType·
Fontconfig·libthai 및 introspection을 명시적으로 켜고 테스트와
예제도 빌드하도록 구성했다. C/C++ 교차 설정은 기존
harfbuzz-cross.ini를 재사용한다. Xft는 비활성화되어 있으며 X11
지원 완료를 의미하지 않는다. Pango 빌드는 HarfBuzz GIR 완료 후
실행해야 한다. 레시피 카탈로그 119개와 Pango 의존성 검증은 통과했다.
ISO, GNOME 세션 및 실제 VM 검증 상태는 변경하지 않았다.

### Pango 선행 libthai·libdatrie (2026-09-09)

libdatrie 0.2.14-1과 libthai 0.1.30-1을 추가했다. 소스는
https://linux.thai.net/pub/thailinux/software/libthai/ 공식 배포본이며
로컬 SHA256을 레시피에 고정했다. 독립 서명 검증은 수행하지 않았다.
각 패키지의 LGPL COPYING 원문을 보존한다.

- libdatrie 소스 SHA256: f04095010518635b51c2313efa4f290b7db828d6273e39b2b8858f859dfe81d5
- libthai 소스 SHA256: ddba8b53dfe584c3253766030218a88825488a51a7deef041d096e715af64bdd

/tmp/kiki-thai-LFjBwhVl에서 두 패키지 빌드가 성공했다. 명시적
sysroot로 대상 libc에 연결하고 정적 라이브러리·libtool la 파일을
제외했다. libthai 사전은 끄지 않고 패키지 libdatrie의 trietool을
대상 로더로 실행하여 생성했다. /usr/share/libthai/thbrk.tri가
비어 있지 않은지 확인하고 라이브러리 RPATH/RUNPATH를 거부한다.
thai-foundation 시험 프로필과 graphics-foundation에 연결했다.

test_thai_runtime 1개, 공식 C 테스트 드라이버 8종이 10.253초에
통과했다. 고정 소스 해시를 재확인하고 문자 분류·문자 셀·입력·
렌더링 데이터·문자열·와이드 문자·일반/와이드 단어 분리 드라이버를
실제 패키지 라이브러리에 연결하여 임시 chroot에서 실행했다.
단어 분리 테스트는 패키지의 기본 사전 경로를 사용한다.

```sh
KIKI_TEST_THAI=1 PYTHONPATH=tools python3 -B -m unittest test_thai_runtime -v
```

이는 공식 전체 테스트 모음(별도 정렬 시험 등)이나 Pango·GTK 화면
시험 완료를 의미하지 않는다. Pango 자체 빌드 및 GNOME 세션 통합은
다음 단계다. ISO와 실제 VM 설치 검증 상태는 변경하지 않았다.

### GIR 대상 libc 전환 (2026-09-09, 빌드 및 대상 실행 검증 통과)

최종 결과: /tmp/kiki-gi-single-Tldno3bH에서 gobject-introspection
1.84.0-7 빌드가 종료 코드 0으로 완료되었다. 아래 초기 실패 기록은
수정 경위이며 현재 빌드 상태를 의미하지 않는다.

test_introspection_runtime 1개가 15.538초에 통과했다. 현재 레시피의
실제 런타임 의존 패키지를 임시 chroot에 추출하여 대상 Python에서
g-ir-scanner --version을 실행하고, 패키지의 GLib GIR를 실제
g-ir-compiler로 다시 컴파일했다. 대상 glibc 2.39에서 이 새 typelib과
GObject/Gio typelib을 읽고 타입 항목이 존재하는지 검사했다.
GLib typelib 로딩 경로가 재컴파일한 /tmp 파일인지도 확인했다.

```sh
KIKI_TEST_INTROSPECTION=1 PYTHONPATH=tools python3 -B -m unittest test_introspection_runtime -v
```

이 테스트는 Linux root의 임시 chroot 전용이며 장치·서비스 설정을
변경하지 않는다. 스캐너의 독립적인 C 헤더 전체 분석 회귀 시험이나
GNOME 세션·GTK 화면·VM 설치 검증을 대신하지 않는다. GIR 생성 자체는
이번 패키지 빌드에서 수행되었다. 기존 ISO는 변경하지 않았다.

후속 결과: 재빌드 Python 패키지의 test_python_runtime 1개가
통과했다(11.488초). 임시 chroot에서 Python 3.12.4와 대상 glibc
2.39를 확인하고 ctypes의 C 함수·libffi 콜백, SSL 모듈 import,
SHA256, JSON/XML 한글 및 zlib/lzma 왕복을 검사했다. TLS 연결이나
인증서 검증 시험은 아니다.

```sh
KIKI_TEST_PYTHON=1 PYTHONPATH=tools python3 -B -m unittest test_python_runtime -v
```

첫 GI 빌드는 스캐너 단계에서 실패했다. 빌드 도구의 command_env로
환경을 정확히 복원한 재현에서 GI_CROSS_LAUNCHER와
gi_cross_binary_wrapper가 함께 적용되어 셸 래퍼를 ELF로 실행하려는
중복 호출을 확인했다. 일부 경로를 생략한 초기 수동 재현의 libc
오류와 구분한다. 명시적 gi_cross_binary_wrapper 옵션을 제거하고
GI_CROSS_LAUNCHER만 유지했다. /tmp/kiki-gi-single-Tldno3bH에서
수정 후 재빌드를 수행했으며 성공·typelib 실행 결과는 위에 기록했다.

Pango 1.57.1의 meson.options와 기존 gobject-introspection 레시피를
검사했다. 기존 GI 레시피에도 sysroot_exclude: [glibc]가 남아 있어
GLib release 2와 같은 대상 ABI 전환이 필요하다. Pango 바인딩을
끄는 대신 gobject-introspection 1.84.0 release 7에서 이 제외를
제거하고 linux-headers 및 명시적 sysroot·Meson 교차 설정을 추가했다.

스캐너의 Python, GIR 컴파일러와 생성된 임시 바이너리는 기존
KIKI 대상 로더 래퍼를 이용하도록 구성했다. GI 및 GLib 내부 빌드
라이브러리 경로는 호스트 LD_LIBRARY_PATH가 아닌 대상 로더용
변수에 전달한다. GLib GIR 생성 단계도 동일 교차 설정을 사용한다.
스캐너·컴파일러·교차 설정 파일은 레시피 입력 해시에 포함했다.

introspection-foundation 프로필을 추가했고 116개 레시피 검증과
변경 파일 공백 검사는 통과했다. /tmp/kiki-gi-target-Z7L03v2B에서
초기 빌드를 실행했고 Python 의존성 재빌드 이후 위 중복 래퍼 오류를
수정했다. release 7의 최종 재빌드와 실행 검증은 위 결과를 참고한다.
기존 ISO는 변경하지 않았다.

### Pango 선행 FriBidi 검증 (2026-09-09)

Pango 1.57.1 공식 소스를 받아 SHA256
e65d6d117080dc3aeeb7d8b4b3b518f7383aa2e6cfce23117c623cd624764c2f가
고정 GNOME 메타데이터와 일치함을 확인했다. 소스에서 FriBidi >=1.0.6,
GLib >=2.82, HarfBuzz >=8.4.0, Fontconfig >=2.17.0,
Cairo >=1.18.0 요구를 확인했다. Pango 자체 빌드는 아직 하지 않았다.

FriBidi 1.0.16-1 레시피와 fribidi-foundation 시험 프로필을 추가하고
graphics-foundation에 연결했다. 공식 GitHub 릴리스 아카이브의
로컬 SHA256은 1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c다.
독립 서명 검증은 수행하지 않았다. LGPL COPYING 원문을 보존한다.
116개 레시피 검증과 /tmp/kiki-fribidi-Th9LAVkH 빌드 성공.
패키지 63,892바이트, SHA256
5423e53efaa49525d1f159eb4788ba9e04864d0d47b07b0bffa9e6352e25a4c5.

test_fribidi_runtime 1개(공식 CLI 회귀 사례 6종) 통과, 8.375초.
고정 해시를 재확인한 소스 아카이브에서 입력·정답만 읽어 실제
KIKI 패키지의 CLI를 임시 chroot에서 실행했다. CapRTL의
explicit/implicit/isolate, ISO8859-8 hebrew, UTF-8 persian/
reordernsm 출력이 공식 정답과 바이트 단위로 일치한다. 대상 로더
의존성, 버전, 라이브러리 RPATH/RUNPATH 부재도 확인했다.

```sh
KIKI_TEST_FRIBIDI=1 PYTHONPATH=tools python3 -B -m unittest test_fribidi_runtime -v
```

전체 Unicode 적합성 데이터셋 시험이나 Pango의 한글 혼합 문장
배치·줄바꿈·실제 GTK 화면 검증은 아니다. 다음 작업은 Pango의
추가 의존성과 GIR 요구를 충족한 뒤 통합 빌드·시험하는 것이다.
이번 작업에서 기존 ISO는 변경하지 않았다.

### Cairo 기본 통합 검증 (2026-09-09)

고정 GNOME 메타데이터와 같은 버전의 Cairo 1.18.4를 공식 배포
아카이브로 받아 레시피와 cairo-foundation 프로필을 추가했다.
소스 SHA256은 445ed8208a6e4823de1226a74ca319d3600e83f6369f99b14265006599c32ccb이며
로컬 계산 값이다. 독립 서명 검증이나 GNOME의 Git commit과
아카이브 내용 전체 일치 검증은 하지 않았다. COPYING 및 LGPL/MPL
원문, 보조 util 소스의 고지를 패키지에 보존한다.

115개 레시피 검증과 /tmp/kiki-cairo-ayItnBG9 빌드에 성공했다.
패키지 크기 1,063,174바이트, SHA256
0d868fec056eaadec404371e9eba7c7a2b557b4ab21a976e46ba0a31ef43b38f.
Pixman/FreeType/Fontconfig/PNG/zlib/GLib를 연결했다. Xlib/XCB,
LZO, Spectre, 심볼 조회는 비활성이고 upstream 전체 시험은
의존성 순환을 피하는 GNOME 메타데이터처럼 비활성이다.
특히 X11 관련 소비 패키지의 요구 충족은 아직 확인하지 않았다.

test_cairo_runtime 1개 통과(12.031초): 실제 패키지 의존성을
임시 chroot에 풀어 dark-blue(#002060) 픽셀 값, PNG 저장 후
재읽기 픽셀 일치, 기존 Noto CJK 글꼴을 이용한 한국어 문자열의
비어 있지 않은 렌더링, PDF/SVG 출력의 Cairo 성공 상태와 파일
시그니처를 검사했다. 문서 전체 파싱·뷰어 렌더링 검증은 아니다.
RPATH/RUNPATH 부재와 대상 로더 의존성도 확인했다.

```sh
KIKI_TEST_CAIRO=1 PYTHONPATH=tools python3 -B -m unittest test_cairo_runtime -v
```

graphics-foundation에 연결했다. GTK4 창 표시, 복합 문자 배치,
실제 VM 화면/설치, 기존 소비 패키지와 ISO 통합은 별도 미완료
항목이다. 이번 작업에서 기존 ISO는 변경하지 않았다.

### Pixman CPU 합성 기반 (2026-09-09)

Pixman 0.46.4-1 레시피와 pixman-foundation 시험 프로필을 추가하고
graphics-foundation에 포함했다. 공식 cairographics.org/releases
아카이브의 SHA512가 배포된 .sha512 파일과 일치한다. 레시피의
SHA256은 a098c33924754ad43f981b740f6d576c70f9ed1006e12221b1845431ebce1239다.
서명 파일에 대한 독립 키 검증은 수행하지 않았다. COPYING 고지를
패키지에 보존했다.

114개 레시피 검증 및 /tmp/kiki-pixman-8cZAJhtK 빌드 성공.
패키지 320,450바이트, SHA256
6f5f211ccbab630744b517df1a67169bdf52c0165b4769fc0811c1485af558f5.
test_pixman_runtime 1개 통과(9.524초): 실제 패키지를 임시 chroot에
풀어 반투명 OVER 합성값, 2x2 클리핑, 행 패딩 sentinel 보존,
불투명 dark-blue(#002060) SRC 합성과 버전을 확인했다. 대상 로더
의존성과 RPATH/RUNPATH 부재도 검사했다.

```sh
KIKI_TEST_PIXMAN=1 PYTHONPATH=tools python3 -B -m unittest test_pixman_runtime -v
```

이 검증은 작은 CPU 메모리 표면에 대한 정확성 시험이다. upstream
시험 프로그램은 빌드했지만 전체 시험 실행, Cairo/GTK 표시,
VM의 화면·가속 경로는 아직 검증하지 않았다. 다음 선행 구성은
Cairo이며 고정 GNOME 메타데이터가 참조하는 버전은 1.18.4다.
기존 ISO는 변경하지 않았다.

### HarfBuzz 대상 링크·한글 조합 검증 완료 (2026-09-09)

with_libstdcxx=false라는 upstream 기본 C 링크 방식으로 수정한
HarfBuzz 14.4.0-1 빌드가 /tmp/kiki-harfbuzz-clink-lTn5FIn0에서
성공했다. 이전 실패 빌드와 구분한다. OpenType, GLib/GObject,
FreeType, subset 및 기본 raster/vector/GPU 라이브러리 빌드는
유지했다. GIR/Cairo/ICU 등 앞서 명시한 통합 잔여 항목은 그대로다.

test_harfbuzz_runtime 1개 통과(12.134초). 실제 패키지와 의존성을
임시 chroot에서 실행해 한글 11,172자의 완성형과 분해 자모가 같은
단일 글리프와 양의 동일 advance를 만드는지 확인했다. FreeType
자동 힌팅 호출도 성공했다. 이는 기존 Noto CJK 글꼴 한 가지에 대한
결과이며 모든 글꼴·스크립트의 품질을 입증하지 않는다.

패키지의 libharfbuzz*.so* 및 hb-* ELF 각각을 대상 로더의 --list로
확인했고 RPATH/RUNPATH가 없음을 검사했다. hb-shape --version도
14.4.0으로 확인했다. 이 검사에서는 호스트 파일 시스템의 라이브러리를
로드할 수 없도록 chroot를 사용했다. upstream 시험 프로그램은
빌드했지만 전체 upstream 시험을 실행한 것은 아니다.

```sh
KIKI_TEST_HARFBUZZ=1 PYTHONPATH=tools python3 -B -m unittest test_harfbuzz_runtime -v
```

검증한 FreeType/HarfBuzz/Fontconfig를 gnome-foundation에 연결했다.
이는 개발 프로필이며 GNOME 전체 제공 완료가 아니다. 변경된 GLib
기반의 GIR·다른 소비 패키지와 rootfs/ISO 통합 검증도 남아 있다.
이번 작업에서 기존 ISO는 변경하지 않았다.

### Fontconfig 준비 (2026-09-09, 빌드·기본 실행 검증 통과)

후속 결과: Fontconfig 2.18.3-1 빌드 성공. graphics-foundation에
포함했다. test_fontconfig_runtime 1개 통과(46.116초): 실제
패키지 의존성만 임시 chroot에 풀어 빈 검색 결과, Noto CJK 글꼴
추가, fc-cache 생성, lang=ko 검색과 반복 일치, 임시 글꼴 제거 후
캐시 갱신 및 빈 검색 결과 복귀를 확인했다. 실제 /etc/fonts 설정을
사용했고 설정 파일의 임시 빌드 경로 혼입과 라이브러리 RPATH도
검사했다. 제거한 것은 시험용 글꼴 복사본뿐이며 기존 글꼴은 보존했다.

```sh
KIKI_TEST_FONTCONFIG=1 PYTHONPATH=tools python3 -B -m unittest test_fontconfig_runtime -v
```

이 시험은 글꼴 검색·캐시 기본 동작이며 전체 upstream 시험이나
GUI의 실제 한글 표시 검증을 대신하지 않는다. HarfBuzz는 C++
런타임 의존성 빌드를 마치고 본체의 한글 shaper 등 소스 컴파일에
진입했다. 아직 HarfBuzz 실행 시험은 수행하지 않았다.

추가 확인: HarfBuzz 빌드는 이후 본체 링크 단계에서 실패했다.
__isoc23_strtol / __isoc23_strtoul 미해결 참조를 단일 작업으로
재현했다. C++ 링크 명령에 /usr/lib64 등 호스트 경로가 대상 경로보다
먼저 들어가 있다. 명시적으로 활성화한 with_libstdcxx 옵션은
src/meson.build에서 C++ 링커를 선택하며, upstream 기본값 false는
C 링커를 사용한다. 다음 작업에서 대상 경로 격리와 공식 기본 링크
방식을 확인해 수정하고 전체 빌드·실행을 재검증한다. 현재 빌드는
종료됐으며 더 이상 진행 중이 아니다. 성공한 Fontconfig 결과와
구분하고 HarfBuzz 완성으로 간주하지 않는다.

공식 GitLab generic package 경로에서 Fontconfig 2.18.3 소스를
받았다. SHA256 4f7b554a38cdf78c033f666c8871f3749e14a094f65a07f630c91ed0b43d35e3가
같은 공식 경로의 .sha256sum과 일치한다. 독립 서명 검증은 아니다.
소스의 옵션 파일은 meson_options.txt가 아닌 meson.options다.

fontconfig.toml과 fontconfig-foundation 검증 프로필을 추가했다.
FreeType·Expat 대상 라이브러리를 사용하며 번역과 CLI 도구를
활성화한다. 빌드 중 외부 시험 글꼴 다운로드와 설치 시 캐시 생성을
비활성화하고 /etc/fonts, /usr/share/fonts, /var/cache/fontconfig
대상 경로를 사용한다. 기존 호스트의 글꼴 캐시는 변경하지 않는다.
COPYING에 포함된 저작권·라이선스 고지를 패키지에 보존한다.

113개 레시피 검증 통과. 별도 /tmp/kiki-fontconfig-w0SNqLQ6에서
빌드를 시작했으며 완료·실행 검증은 아직 하지 않았다. 다음 검증은
임시 대상 루트에서 한글 글꼴 검색, 캐시 생성, 재검색 및 실제 설정
경로 확인이다. HarfBuzz 빌드도 기존 경로에서 중단 없이 진행 중이다.

### HarfBuzz 구성과 GLib 재빌드 오류 수정 (2026-09-09, 검증 진행 중)

후속 결과: GLib 2.84.4-2 패키지 빌드 성공. 새로 추가한
test_glib_runtime 1개 통과(38.442초). 실제 대상 패키지 의존성을
임시 chroot에 풀어 g_cclosure_marshal_generic을 사용하는
GObject 시그널 호출의 int/UTF-8 문자열 전달·정수 반환을 검사했다.
한글 NFC/NFD 왕복, idle 콜백과 GMainLoop 종료, GIO 경로 객체도
확인했다. GLib/GObject/GIO 공유 라이브러리에 RPATH/RUNPATH가
없고 대상 libffi가 연결됨을 검사한다. 실제 파일 생성이나 서비스
변경은 하지 않았다. 모든 GLib 기능·전체 upstream 시험을 수행한
것은 아니며, GIR 및 설치기 연동 회귀 시험은 별도로 필요하다.

```sh
KIKI_TEST_GLIB=1 PYTHONPATH=tools python3 -B -m unittest test_glib_runtime -v
```

HarfBuzz 빌드 프로세스는 같은 임시 경로에서 계속 실행 중이며,
의존성인 libgcc 재빌드를 위해 GCC를 컴파일하는 단계까지 확인했다.
HarfBuzz 패키지 성공이나 한글 조합 시험 통과로 판정하지 않는다.

HarfBuzz 14.4.0 레시피와 test_harfbuzz_runtime을 추가했다.
공식 https://github.com/harfbuzz/harfbuzz/releases 배포 아카이브의
로컬 SHA256은 2357ed966c6ced7bfa720b0640c0231065af01158fbea215093ffa15aed44371이다.
GNOME build-meta 내부 직접 항목이 아닌 별도로 고정한 릴리스다.
독립 서명 검증은 하지 않았다. GLib/GObject/FreeType 연동을 활성화하며
GIR, Cairo, ICU 연동은 아직 비활성이다. 전체 데스크톱 완성 판정 전
소비 패키지 요구에 맞춰 보완한다.

첫 빌드는 /tmp/kiki-harfbuzz-IhAJS2tb에서 GLib 단계에 실패했다.
libffi.so.8의 __isoc23_sscanf@GLIBC_2.38 미해결 참조를 재현했다.
GLib 기존 레시피가 glibc를 sysroot에서 제외하고 호스트 libc로
링크하는 것이 원인이다. GLib release 2에 대상 glibc 포함,
linux-headers 빌드 의존성, 명시적 sysroot 및 Meson 교차 설정을
추가했다. 레시피 112개 검증은 통과했다.

수정 후 빌드는 /tmp/kiki-harfbuzz-target-CiXR7fJ9에서 시작했다.
아직 빌드와 실행 성공으로 판정하지 않는다. 준비한 시험은
임시 chroot에서 한글 11,172자의 완성형/분해 자모 글리프와 폭
일치 및 FreeType 자동 힌팅 호출을 검사한다. 실행 결과는 추후 기록한다.
GLib 릴리스 변경으로 후속 패키지·rootfs·ISO 재검증도 필요하다.
기존 배포 ISO는 이번 작업에서 변경하지 않았다.

### FreeType 한글 래스터화 기반 (2026-09-09)

graphics-foundation에 FreeType 2.14.3-1 네이티브 패키지를 추가했다.
공식 출처는 https://freetype.org/download 이며 다운로드 아카이브의
SHA256은 36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f다.
해시는 로컬 계산 값이며 독립 서명을 검증하지 않았다.
이 소프트웨어는 FreeType Project(https://freetype.org)의 FreeType을
사용한다. 패키지에 LICENSE.TXT, FTL.TXT, GPLv2.TXT와 src 원문의
제3자 저작권·라이선스 고지를 보존했다.

111개 레시피 검증과 빌드에 성공했다. 작업 경로는
/tmp/kiki-freetype-AZIhX73Q이며 패키지는 2,087,649바이트,
SHA256 eb468bbb1d200cf615503b81346181db3dedd6c9f56d6ae55839fa9385c88766이다.
PNG와 외부 zlib를 사용하고, HarfBuzz는 상호 의존성 준비를 위한
동적 로딩으로 설정했다. Brotli/WOFF2와 bzip2 압축 글꼴 지원은
아직 비활성이다. 이것은 개발용 기반 단계이며 최종 GNOME 글꼴
스택의 기능을 이 범위로 축소하지 않는다. HarfBuzz 패키지 연동,
압축 확장 활성화 및 통합 시험을 완료 전 필수 잔여 항목으로 둔다.

test_freetype_runtime 1개 통과(10.485초). 실제 패키지 의존성을
임시 chroot에 추출하고 대상 헤더/라이브러리로 만든 C 시험 프로그램을
KIKI 로더로 실행했다. 호스트 HarfBuzz가 동적 로딩되지 않도록
chroot 내부만 사용하며 서비스·디스크·마운트는 변경하지 않는다.
기존 설치기 NotoSansCJK-Regular.ttc를 시험 입력으로 복사해
U+AC00..U+D7A3 한글 11,172자를 24픽셀로 래스터화하고 각 글리프의
존재, 렌더링 성공, 비어 있지 않은 비트맵을 검사했다.
잘못된 4바이트 글꼴 입력 거부와 FreeType 버전, ELF RPATH 부재도
확인했다. 글꼴의 데스크톱 패키징·시각적 품질·실제 GTK 출력 및
커널 VT에서의 한글 표시를 검증한 것은 아니다.

```sh
# 임시 chroot를 만들기 위해 Linux root 권한 필요
KIKI_TEST_FREETYPE=1 PYTHONPATH=tools python3 -B -m unittest test_freetype_runtime -v
```

기존 ISO와 설치기 호스트 GTK 묶음은 이 작업에서 변경하지 않았다.

### 네이티브 PNG 기반 패키지 (2026-09-09)

libpng 1.6.58-1 레시피와 graphics-foundation 검증 프로필을 추가하고
gnome-foundation에 포함했다. 공식 배포 아카이브 SHA256은
28eb403f51f0f7405249132cecfe82ea5c0ef97f1b32c5a65828814ae0d34775다.
해시는 다운로드 파일에서 계산했으며 독립 서명 검증은 하지 않았다.
출처: https://www.libpng.org/pub/png/libpng.html
PNG Reference Library License 원문을 패키지에 보존한다.

레시피 110개 검증 및 패키지 빌드 성공. test_png_runtime 1개 통과
(9.125초): 대상 헤더로 C 시험 프로그램을 빌드하고 실제 KIKI 로더로
실행해 2x2 RGBA 메모리 PNG 왕복의 색상·알파 일치, 잘린 입력과
손상된 서명 거부, 런타임 버전을 확인했다. 로더가 해결한 라이브러리는
임시 대상 루트 내부이며 libpng RPATH/RUNPATH가 없음을 검사한다.

```sh
KIKI_TEST_PNG=1 PYTHONPATH=tools python3 -B -m unittest test_png_runtime -v
```

이번 빌드 작업 디렉터리는 셸 인자 전달 문제로 의도한 /tmp 대신
저장소의 x86_64 아래 생성됐다. 산출물은 보존했으며 자동 삭제하지
않았다. 다음 빌드는 명시적인 임시 경로로 실행한다.
이 검증은 전체 PNG 적합성·취약점 검사나 GUI 표시 시험이 아니다.
기존 ISO는 변경하지 않았으며 GNOME 전체 제공/실기 검증은 미완료다.

### GNOME Session 네이티브 의존성 재확인

gnome-session-50.1.tar.xz를 공식 GNOME 배포 서버에서 받아 기존 잠금
해시 6289b6afa44d3e4c999ce5761ff8b2c10ba309f55f9425f2b13f98208c81f6fb와
일치함을 확인했다. 공식 sha256sum 파일과도 일치한다.
소스 meson.build는 GLib >=2.82, gnome-desktop-4, libsystemd >=209,
systemd 사용자 유닛 설치 경로를 요구한다. 사용자 유닛 경로는 Polkit과
마찬가지로 빌드 sysroot가 설치 경로에 섞이지 않도록 명시해야 한다.

고정된 gnome-build-meta 50.4에서 gnome-desktop 44.5와 GTK 4.22.4
소스/해시를 추출해 계획 잠금 목록에 추가했다. gnome-desktop 44.5는
다운로드 후 SHA256이 잠금 값
20e0995a6e3a03e8c1026c5a27bc3f45e69ffcc392ad743dcab6107a541d232f와
일치함을 확인했다. GTK 4.22.4는 아직 다운로드 검증 전이며 두 패키지
모두 빌드·실행 검증 전이다. 메타데이터의 gnome-desktop 의존성은
GLib/GSettings 외에 GTK3/GTK4, gdk-pixbuf, iso-codes 등을 포함한다.
현재 설치기의 호스트 기반 GTK4.12 런타임은 네이티브 GNOME 스택을 대신하지
않는다. 세션 패키지와 전체 데스크톱은 여전히 미완료다.

gnome-desktop 44.5의 meson.build와 libgnome-desktop/meson.build를
직접 확인한 결과, gnome-desktop-4 생성은 build_gtk4=true 조건 안에
있다. 이 옵션을 끄면 세션에 필요한 라이브러리도 생성되지 않는다.
기본 라이브러리의 직접 링크 의존성과 별개로 최상위 구성은 GTK >=4.4를
요구하고 gnome-bg/gnome-rr도 함께 구성한다. GTK를 끄는 방식으로
세션만 먼저 완성했다고 판정하지 않는다. legacy_library=false는
GTK3 기반 구형 라이브러리를 제외하는 별도 선택지다.

추가 필수 구성에는 gdk-pixbuf >=2.36.5, fontconfig,
xkeyboard-config, iso-codes, Linux에서 libseccomp가 있다.
xkbregistry는 선택 의존성이며 systemd/udev는 명시적으로 활성화할
대상이다. 향후 레시피에서는 pkg-config에서 읽는 cachedir, xkb_base,
iso-codes prefix가 임시 sysroot 경로로 바이너리에 삽입되지 않는지도
검사해야 한다. 이 경로들은 실제 컴파일 매크로에 사용된다.

다음 순서는 네이티브 그래픽·데이터 의존성 준비, GTK4 빌드 검증,
gnome-desktop, gnome-session이다. 설치기용 호스트 GTK 묶음을
네이티브 빌드 의존성으로 간주하지 않는다.

새 ISO의 실제 GUI/TUI/CLI 설치 시험을 위해 VM 이름·접근 방법·초기화할
가상 디스크와 실행 승인을 요청했다. 확인되지 않은 디스크 작업은 하지 않는다.

### install-info 대상 패키지 준비 (2026-09-09)

대상 실행기 후처리 시험: test_ki2ctl_target_hooks는 ki2ctl의 실제
패키지 의존성만 임시 chroot에 풀고 KIKI Python 3.12 및 ki2ctl CLI로
hooks apply를 실행한다. 시험 1개 통과(13.632초).

```sh
KIKI_TEST_TARGET_HOOKS=1 PYTHONPATH=tools python3 -B -m unittest test_ki2ctl_target_hooks -v
```

dry-run이 대기 기록을 변경하지 않는지, 실제 install-info가 두 문서의
인덱스를 만들고 applied로 전환하는지 확인했다. 임시 복사본의 도구를
잠시 다른 이름으로 바꿔 누락 오류를 일으킨 결과 failed 상태와 기존
인덱스 보존을 확인했고, 복원 후 재시도에서 applied와 last_error 제거,
동일 인덱스 결과를 확인했다. 호스트 파일/서비스는 변경하지 않았다.

후처리 대기 기록과 문서는 시험 fixture로 생성했다. 이 시험은
대상 Python·실제 후처리 실행의 검증이며, 부팅·전체 설치 트랜잭션·
실제 디스크 작업을 수행한 것은 아니다. /dev/null에는 장치 대신
임시 빈 일반 파일을 사용했으며 마운트/장치 노드는 생성하지 않았다.

ki2ctl release 11 아카이브 재검증: test_ki2ctl_package가 실제 .ki2에서
CLI를 읽어 소스와 바이트 단위로 비교하고, 모드 0755/root 소유 및
install-info 런타임 의존성을 확인한다. 추출한 CLI를 임시 경로에 두고
설치/삭제/업그레이드/그룹/서명/롤백 및 후처리 회귀 시험 20개를 실행했다.
전체 통과(내부 시험 8.493초, wrapper 시험 8.781초).

```sh
KIKI_TEST_KI2CTL_PACKAGE=1 PYTHONPATH=tools python3 -B -m unittest test_ki2ctl_package -v
```

실제 패키지의 CLI를 사용했지만 실행기는 빌드 호스트 Python이다.
저장소와 설치 대상은 임시 경로이며 HTTP 시험은 로컬 시험 서버만 사용한다.
대상 KIKI Python으로 실행하거나 실제 부팅 시스템에서 훅을 수행한
검증을 대신하지 않는다. 기존 ISO와 패키지 내용은 변경하지 않았다.

ki2ctl 트랜잭션 후속 검증/수정: 임시 로컬 저장소와 실제 CLI로 Info
문서 두 패키지를 설치하고 하나를 삭제해 공통 인덱스 보존을 확인했다.
이어 문서 패키지 설치 후 잘못된 hardlink를 가진 시험 패키지로 실패를
일으켰다. 최초 시험에서는 파일/설치 DB는 복원되지만 pending-hooks.json에
취소된 설치 작업이 남는 결함이 재현됐다.

설치와 제거 트랜잭션의 백업 목록에 후처리 기록을 포함해 수정했다.
관련 20개 테스트 통과(20.257초), 이후 기존 후처리 기록이 없는 경우를
추가한 집중 시험도 통과(2.105초). 기존 기록이 있으면 바이트 단위로
복구하고, 없었다면 실패 과정에서 만들어진 기록을 제거함을 확인했다.
검사는 오프라인 대상이며 실제 hooks apply 실행은 하지 않는다.

ki2ctl 0.1.0-11을 /tmp/kiki-ki2ctl-r11-eeAAIXWZ 에서 빌드했다.
키 61bcaae0ac78, 종료 코드 0, 패키지 SHA-256:
`53d0647d98c76f8357ffbdfe9540db512e4c49e2fa5b86fcdba6837426b427d2`.
소스 CLI 시험이므로 해당 아카이브에서 추출한 CLI의 전체 재시험 및
실제 설치 시스템 후처리 검증을 대신하지 않는다. ISO는 변경하지 않았다.

release 2 완료: /tmp/kiki-install-info-r2-P74uwmMA 에서 종료 코드 0.
install-info-7.2-2.x86_64.ki2는 77,382바이트이며 SHA-256은
`104e4ce87445c8cfa94ca6dcfbe8a0a2c65266ddd3367e1f73e8541414d2f02a`.
별도 시험 의존성을 더하지 않고 패키지의 선언된 런타임 의존성만으로
일반/gzip/xz/bzip2 문서 추가·반복 실행·압축 항목 삭제 시험이 통과했다
(test_install_info_runtime 1개, 8.593초).

ki2ctl은 공통 /usr/share/info/dir을 생성물로 처리하도록 보완했다.
페이로드 경로 검사·추출·소유권 계산에서 제외하고, 이전 DB의 해당 파일도
패키지 삭제 시 직접 지우지 않는다. 문서 자체의 설치·삭제가 인덱스 재생성
훅을 기록한다. 모의 패키지 두 개를 실제 아카이브로 만들어 기존 공통
인덱스를 보존하고 설치 충돌이 없는지 검사했다. 관련 19개 테스트 통과
(22.388초). 실제 저장소 설치/제거 트랜잭션과 rollback 전체 시험은 별도다.

install-info를 런타임 의존성으로 연결한 ki2ctl 0.1.0-10을
/tmp/kiki-ki2ctl-info-y2DKhuqJ 에서 빌드했다(키 29c91ed263af, 종료 코드 0).
패키지 SHA-256:
`23a5d6aa23d361f7632c5b5999a0d2f5c76fad893f5a5f71422b7e79a58ed0a2`.
기존 ISO는 재빌드하지 않았으며 이전 후보들도 삭제하지 않았다.

대상 실행 검증 후속: install-info 7.2-1과 BusyBox를 임시 chroot에
풀어 일반/gzip/xz/bzip2 문서의 추가, 같은 문서 재추가의 멱등성,
gzip 문서 항목 삭제 후 다른 항목 보존을 확인했다.
test_install_info_runtime 1개 통과(8.794초).
호스트 장치를 마운트하지 않았으며 gnulib의 /dev/null 열기 검사에는
임시 빈 일반 파일을 사용했다. 실제 장치 동작을 검증한 것은 아니다.
첫 실행은 해당 파일 부재로 실패했으며 시험 환경을 보완한 뒤 통과했다.

이 시험에서 필요한 /bin/sh와 bzip2를 BusyBox가 제공함을 확인해
레시피 release 2의 런타임 의존성에 busybox를 추가했다.
테스트도 별도 추가 패키지 없이 install-info 의존성만 사용하도록 변경했다.
release 2 재빌드 및 그 패키지에 대한 재검증은 아직 남아 있다.

GNU 공식 https://ftp.gnu.org/gnu/texinfo/texinfo-7.2.tar.xz 에서 소스를
받아 install-info 전용 레시피와 info-tools 개발 프로필을 추가했다.
소스 SHA-256은
`0329d7788fbef113fa82cb80889ca197a344ce0df7646fe000974c5d714363a6`이다.
독립적인 배포 서명 검증은 수행하지 않았다.
전체 Texinfo 편집/변환 도구가 아니라 공통 인덱스 갱신 바이너리를 패키징한다.
레시피 카탈로그 109개 검증은 통과했다.

빌드는 /tmp/kiki-install-info-8uw7PUC7 에서 종료 코드 0으로 완료했다.
키는 bd9aa982ca7d이며 install-info-7.2-1.x86_64.ki2는 77,304바이트,
SHA-256은 `3bf66d7961d7f8f2d56837444597d4de73999a6aaa7ffd59d0df908280ef26fb`이다.
실제 Makefile의 CC/CFLAGS/LDFLAGS가 대상 sysroot를 가리키며
패키징 시 RPATH/RUNPATH 부재 검사도 통과했다. 실행 시험은 아직 남아 있다.
소스에서 압축 문서 처리가 popen으로 gzip/xz/bzip2 등을
호출함을 확인했다. 현재 레시피의 gzip/xz 외에 셸 의존성 보완과 대상 환경
압축 문서 시험이 필요하다. 이 준비를 ki2ctl 후처리 배포 완료로 간주하지 않는다.

### GNOME 인증 기반 통합 rootfs (2026-09-09)

GNU Info 인덱스 후속 수정: ki2build의 rootfs 조립 마지막에 표준
install-info로 설치된 .info 및 지원 압축 문서의 공통 dir을 재생성한다.
임시 인덱스를 같은 디렉터리에서 만든 뒤 교체하므로 도구 누락·실패 시
기존 인덱스는 유지된다. 대상 밖 심볼릭 링크 경로와 비정규 문서를 거부한다.
빌드 호스트에는 GNU install-info가 필요하다.

test_info_index와 test_ki2build 총 24개 테스트 통과(5.047초).
모의 도구 실패/누락 시 보존과 실제 문서 두 개의 병합·반복 실행을 검사했다.
앞서 만든 실제 GNOME rootfs에도 적용해 gmp와 GNU libunistring 항목이
모두 남고 반복 실행 결과가 동일함을 확인했다(655 → 236바이트).
이는 표준 최소 헤더로 재생성한 결과이며 문서 본문은 수정하지 않았다.

개별 패키지의 /usr/share/info/dir 중복 자체와 실행 중 ki2ctl 설치·삭제
후의 인덱스 재생성은 아직 해결하지 않았다. 따라서 이 변경을 모든
패키지 관리 경로의 충돌 해결로 간주하지 않는다. 기존 ISO는 그대로다.

ki2ctl 후속 소스 구현: Info 문서/공통 dir의 설치·삭제 후
info-index-rebuild 작업을 대기 목록에 추가한다. 루트 /에서 hooks apply 시
표준 install-info로 전체 문서를 처리해 임시 인덱스를 원자적으로 교체한다.
오프라인 root 및 dry-run은 기존 훅처럼 실행을 보류한다. 도구 누락이나
실패는 Ki2CtlError로 전달하므로 완료 처리되지 않고 기존 실패/재시도
기록 경로를 사용한다. 문서가 모두 삭제되면 빈 메뉴로 재생성한다.

test_ki2ctl_hooks와 test_ki2ctl 총 18개 테스트 통과(19.165초).
실제 install-info를 이용한 두 문서 병합, 하나 삭제, 마지막 문서 삭제,
도구 누락 시 기존 인덱스 유지와 오프라인/dry-run 보류를 확인했다.
이는 소스 시험이며 새 ki2ctl 패키지나 ISO를 빌드한 결과는 아니다.
KIKI 대상 install-info 패키지 제공 및 개별 패키지의 공통 dir 소유권
제거/충돌 처리는 여전히 남아 있다. 그 전에는 전체 설치 경로에서
Info 인덱스 문제가 해결됐다고 간주하지 않는다.

48개 개발용 패키지를 /tmp/kiki-gnome-auth-rootfs-miYMD4mI/rootfs 에
조립했다. ki2build rootfs 종료 코드 0이며 기존 rootfs/ISO는 덮어쓰지 않았다.
GLib 스키마 캐시 생성은 성공했지만 /system/ 스키마 경로의 사용 중단 예정
경고는 발생했다. 아직 GNOME Shell/GDM 및 부팅 가능한 완성 데스크톱이 아니다.

```sh
KIKI_GNOME_TEST_ROOTFS=/tmp/kiki-gnome-auth-rootfs-miYMD4mI/rootfs PYTHONPATH=tools python3 -B -m unittest test_gnome_foundation_runtime -v
```

통합 실행 테스트 1개 통과(0.037초). 대상 Python/GLib에서 GDesktopEnums,
Json, GUdev, Polkit, PolkitAgent typelib 5개를 로드했다. JSON 파싱,
GUdev 생성/해제, dconf 로드, Polkit details의 한국어 UTF-8 저장/조회와
없는 키의 NULL 반환, agent 라이브러리 로드를 확인했다.
권한 승인 요청이나 daemon 시작은 수행하지 않았다.

48개 패키지 manifest의 비디렉터리 경로를 별도로 대조했다.
고유 경로 11,000개 중 중복은 /usr/share/info/dir 한 경로로,
gmp와 libunistring이 각각 제공한다. 현재 조립 순서에서는 후자의 파일이
남으므로 GNU Info 공통 인덱스 병합/재생성 처리가 후속 과제다.
이 검사는 manifest 경로 비교이며 전체 파일 내용·동작 검증을 뜻하지 않는다.

### Polkit 127 통합 준비 (2026-09-09)

127-3 통합 회귀 시험: 실제 현재 패키지에 대해 test_polkit_package,
test_polkit_runtime, test_polkit_accounts, test_pam_unix_runtime 전체
5개 테스트가 통과했다(108.338초). 한국어 catalog/XML, 파일 모드,
6개 ELF 의존성, 4개 CLI 버전, 서비스 계정/규칙 디렉터리 초기화와
멱등성, Polkit PAM 6개 사례 및 일반 PAM 실패 잠금 회귀를 포함한다.
이 결과는 실제 daemon/agent 승인 또는 VM 부팅 시험을 포함하지 않는다.

Polkit을 gnome-foundation 개발용 프로필에 연결했다. 런타임 의존성은
48개로 기본 검사 한도 40개를 넘으므로 이 프로필의 검증 명령은 다음과 같다.
서버 기본 한도나 server-core 구성은 변경하지 않았다.

```sh
python3 -B tools/ki2build.py validate --profile distro/profiles/gnome-foundation.toml --max-packages 64
```

108개 레시피 검증과 의존성 계획 생성이 통과했다. gnome-foundation은
여전히 개발용이며 완성된 GNOME 설치 프로필이 아니다. 합쳐진 rootfs,
GDM/로그인 세션 및 daemon/agent 통합 시험은 남아 있다.

한국어 번역 후속 빌드: Polkit 127-3에 KIKI 작성 ko.po의 핵심 메시지
24개를 포함했다. msgfmt --check 서식 검사 통과. 사용자명·명령 치환 토큰과
printf 인수를 보존했다. 번역을 소스 입력 해시에 포함하고 upstream
LINGUAS에 ko를 추가해 catalog 및 권한 요청 XML에 병합한다.

- 빌드: /tmp/kiki-polkit-ko-Gvvs4tA7, 종료 코드 0.
- 패키지: dist/ki2/packages/x86_64/polkit-127-3.x86_64.ki2,
  272,623바이트, SHA-256
  `e1f821d4457084a290679f44a6935a918846f2c5612c9af5c21f9577d5341f37`.
- test_polkit_package 1개 통과(0.211초). ko catalog를 필수 파일로 검사하며
  GNUTranslations로 실제 번역과 치환 토큰을 읽고, 권한 요청 XML의
  xml:lang=ko 인증 문구도 확인했다.

이 결과는 한국어 지원 전체 완료가 아니다. 긴 pkcheck 도움말과 예제 메시지,
다른 구성 요소(GLib/PAM/GNOME)의 문구 및 실제 인증 창 렌더링은 별도 작업이다.
127-2의 한국어 catalog 부재 기록은 이전 후보 결과로 남긴다.
127-3에 대한 라이브러리 실행·PAM·계정 초기화 시험 전체 재실행과
데몬/인증 agent 연동은 남아 있다. 기존 ISO에는 아직 포함하지 않았다.

서비스 계정 준비 검증: `tools/test_polkit_accounts.py`가 실제 패키지
의존성을 임시 루트에 풀고 대상 systemd-sysusers/systemd-tmpfiles를
`--root`로 실행한다. 테스트 1개 통과(23.384초).

```sh
KIKI_TEST_POLKIT_ACCOUNTS=1 PYTHONPATH=tools python3 -B -m unittest test_polkit_accounts -v
```

Linux root가 필요하지만 계정 파일·디렉터리 변경은 TemporaryDirectory
아래의 대상 루트로 한정된다. 서비스 시작, 디스크 포맷, 마운트는 하지 않는다.
polkitd의 UID/GID가 0이 아닌지, 같은 이름의 그룹과 GID가 일치하는지,
nologin 셸과 잠긴 암호 필드가 생성되는지 검사했다. 시험 rules.d를 0777로
변경한 후 tmpfiles가 root:polkitd 0750으로 고치는지, 두 도구를 다시
실행해 passwd/group이 변하지 않고 그룹이 유지되는지도 확인했다.
실제 부팅 중 자동 실행되거나 polkitd가 해당 권한으로 가동되는지는
아직 검사하지 않았다.

첫 시도는 시험용 동적 로더에서 libsystemd-shared-255.so를 찾지 못해
중단됐다. 임시 대상의 /usr/lib/systemd를 로더 검색 경로에 추가한 뒤
통과했으며, 이 실패를 실제 설치된 시스템의 로딩 결함으로 단정하지 않는다.

추가 PAM 시험은 실제 polkit 패키지에서 /etc/pam.d/polkit-1을 읽고
레시피 입력 정책과 바이트 단위로 비교한 뒤 임시 chroot에 적용한다.
기존 PAM 시험에 패키지 정책용 사례를 추가했으며 서비스명도 polkit-1로
호출한다. 정상 암호·잘못된 암호·잠금·없는 사용자·만료·빈 암호의
6개 사례를 검사한다. 호스트 계정·PAM 파일은 사용하지 않는다.
최신 실행은 KIKI_TEST_PAM_UNIX=1로 test_pam_unix_runtime 전체
2개 테스트 통과(64.075초): Polkit 패키지 정책 6개 사례와
일반 PAM 정책 6개 사례 및 실패 카운터 초기화·3회 실패 잠금·관리자
잠금 해제가 통과했다. 빈 암호 사례는 shadow의 암호 필드와 제공 암호를
모두 비워 거부되는지 확인한다.
이 검증은 root가 libpam을 직접 호출하는 시험으로, Polkit 데몬이나
helper를 통한 승인 흐름, session/password 모듈의 호출 검증은 아니다.
또한 일반 PAM 시험의 faillock 잠금 검증이 Polkit 정책에 적용됐다는
뜻은 아니다. 현재 Polkit 정책에는 faillock이 연결되지 않았다.

추가 실행 검증: `tools/test_polkit_runtime.py`는 실제 패키지와 런타임
의존성을 임시 루트에 풀고 대상 동적 로더로 검사한다. 테스트 1개 통과
(23.155초). pkcheck/pkaction/pkexec/pkttyagent의 --version 출력에서 127을
확인했고, 이 네 도구와 polkitd/helper 총 6개의 ELF 라이브러리 경로가
모두 대상 루트 안임을 확인했다. 여섯 파일 모두 RPATH/RUNPATH가 없었다.

```sh
KIKI_TEST_POLKIT=1 PYTHONPATH=tools python3 -B -m unittest test_polkit_runtime -v
```

검사용 복사본의 pkexec/helper는 특수 권한을 제거했다. 시스템 D-Bus 주소는
임시 루트의 존재하지 않는 소켓으로 지정하고 데몬 시작이나 권한 승인을
요청하지 않았다. 따라서 이 시험은 setuid 동작, 실제 PAM 인증, 서비스
계정/소켓 활성화, GNOME 인증 창의 검증을 대신하지 않는다.

후속 빌드: 개발용 auth-foundation에 Polkit 127-2 전체 패키지를 추가했다.
데몬, PAM helper, Polkit/PolkitAgent typelib과 서비스 파일을 포함한다.
빌드는 /tmp/kiki-polkit-final-F8zO4gzr 에서 종료 코드 0으로 완료했다.
패키지는 dist/ki2/packages/x86_64/polkit-127-2.x86_64.ki2,
271,343바이트, SHA-256
`496595f43887c9d6fbd389bab33071b6ac12f2eb2c16833ca1c5e7d98bd9a6c1`이다.

첫 127-1 빌드는 종료 코드 0이었지만 systemd pkg-config 변수에 붙은
sysroot가 설치 경로로 유입됐다. 이 후보는 배포 대상으로 사용하지 않는다.
127-2는 systemd/sysusers/tmpfiles 경로를 KIKI /usr/lib 아래로 고정하고,
dest/tmp 부재와 필수 파일 존재를 패키징 전에 검사한다.

독립 /etc/pam.d/polkit-1은 pam_unix 인증·계정·세션 검사와 pam_deny
암호 변경 거부를 연결한다. nullok 또는 배포판 공통 include에 의존하지 않는다.
이는 아직 런타임 검증 전인 개발 정책이며 로그인 기본 설정을 바꾸지 않는다.
연속 실패 잠금 정책은 아직 이 파일에 연결하지 않았다.
pkexec/helper의 setuid-root 모드는 레시피에서 명시적으로 설정하고,
실제 아카이브에서 root 소유권과 04755를 검사했다.

```sh
KIKI_TEST_POLKIT_PACKAGE=1 PYTHONPATH=tools python3 -B -m unittest test_polkit_package -v
```

패키지 구조 테스트 1개 통과(0.169초): 서비스·PAM·규칙 디렉터리 모드,
소유권, manifest 일치, typelib, 라이선스, 임시 경로 혼입 부재를 확인했다.
처음 포함했던 한국어 catalog 검사는 실패했다. upstream 127 LINGUAS에
ko가 없으므로 한국어 지원은 미완료로 분리했으며 구조 테스트의 통과가
한국어 지원을 뜻하지 않는다. gettext는 활성화했지만 한국어 catalog는 없다.
실제 권한 승인/거부, helper 소켓, sysusers/tmpfiles 적용, GDM 연동,
upstream 런타임 테스트는 아직 수행하지 않았다. 기존 ISO에는 포함하지 않았다.

패키지 생성기의 선행 결함을 수정했다. 기존 package_entry_mode는
/usr/lib/polkit-1/polkitd와 일반 실행 권한의 인증 helper를 0644로
정규화해 실행 비트를 제거했다. 두 경로에 한해 원본의 실행 의도를 보존하고,
rules.d는 0750으로 패키징한다. setuid를 새로 부여하지는 않으며 기존에
명시된 특수 모드를 보존하는 동작은 유지한다. 대상 polkitd 그룹은
systemd-tmpfiles 적용 단계에서 설정해야 한다.

임시 패키지 생성 테스트에서 데몬/helper 0755, 데이터 파일 0644,
rules.d 0750 및 root 소유권을 확인했다. 이 수정은 아직 만들지 않은
Polkit 패키지의 준비 작업이며 기존 ISO 재빌드를 의미하지 않는다.

[공식 릴리스](https://github.com/polkit-org/polkit/releases/tag/127)의 태그
소스를 내려받아 소스 잠금 목록에 추가했다. SHA-256은
`9b7bc16f086479dcc626c575976568ba4a85d34297a750d8ab3d2e57f6d8b988`이며
다운로드한 아카이브에서 계산했다. 독립적인 서명 검증은 수행하지 않았다.
아직 Polkit 패키지 빌드나 설치를 완료한 상태는 아니다.

127 소스의 meson.build, meson_options.txt, data/meson.build,
meson_post_install.py 및 helper unit을 직접 확인한 통합 조건:

- Meson >=1.4.0, GLib >=2.44, Duktape >=2.2.0, Expat, PAM,
  libsystemd 및 GObject introspection을 대상으로 구성한다.
  전체 데스크톱용 빌드에서는 libs-only로 데몬을 제외하지 않는다.
- `os_type`을 호스트에서 자동 판정하게 두지 않는다. 기본 PAM 템플릿은
  다른 정책 파일을 include하므로 실제 존재하는 KIKI 정책과 연결해야 한다.
  현재 distro 아래에는 system-auth/system-login 또는 pam.d 정책 파일이 없다.
  기존 sudo는 --without-pam이며 임의로 전환하지 않는다.
- polkitd 계정은 제공된 sysusers 정의로 대상 시스템에 생성해야 한다.
  rules.d는 root 소유, polkitd 그룹, 0750이며 polkitd가 규칙을 수정할 수
  없어야 한다. 빌드 호스트의 polkitd GID를 대상 패키지에 고정하면 안 된다.
- 127에는 polkit-agent-helper.socket 및 인스턴스 서비스가 있다.
  소켓 경로는 /run/polkit/agent-helper.socket이고 helper는
  --socket-activated로 실행된다. 소켓 활성화와 PAM 인증을 함께 검사해야 한다.
- upstream 설치 스크립트는 pkexec와 인증 helper의 setuid-root 설정을
  root 실행 시 적용하고 비특권 실행 시 경고만 출력한다.
  따라서 빌드 성공만으로 배포 파일 권한이 정확하다고 간주할 수 없다.
  KIKI 패키지 생성·추출 후 소유권/모드와 실제 호출 경로를 별도로 검사한다.
- 권한 승인·거부·취소, 암호 오류·잠금, 비활성 세션, 잘못된 규칙 파일,
  helper 미가동 및 재시작을 임시 대상 환경에서 검증한 뒤 GNOME에 연결한다.

호스트 인증·서비스 설정과 기존 ISO는 변경하지 않았다.
다음 구현은 명시적인 KIKI PAM 정책 및 패키지 권한 처리와 함께 진행한다.

### Duktape 규칙 엔진 기반 패키지 (2026-09-09)

Polkit 준비 단계로 개발용 auth-foundation 프로필에 Duktape 2.7.0-1을
추가했다. Polkit 자체의 패키징·서비스·PAM 정책 연결이 완료됐다는 뜻은 아니다.
[공식 다운로드](https://duktape.org/download.html)의 소스를 사용했고,
MIT 라이선스 원문을 패키지에 보존했다. 독립적인 배포 서명 검증은 수행하지 않았다.

- 소스 SHA-256: `90f8d2fa8b5567c6899830ddef2c03f3c27960b11aca222fa17aa7ac613c2890`.
- 빌드: `/tmp/kiki-duktape-build-xN255gzj`, 키 `76c78665ed5f`, 종료 코드 0.
- 패키지: `dist/ki2/packages/x86_64/duktape-2.7.0-1.x86_64.ki2`,
  210,430바이트, SHA-256
  `8cccb08372638fba0b640aed9daffe0ce60522479b54fd504c56d2224e1d7a01`.
- KIKI glibc와 libm으로 빌드했고 RPATH/RUNPATH가 없음을 확인했다.
  디버그 복제 라이브러리와 별도 JavaScript CLI는 포함하지 않았다.

```sh
KIKI_TEST_DUKTAPE=1 PYTHONPATH=tools python3 -B -m unittest test_duktape_runtime -v
```

테스트 1개 통과(9.267초): 임시 디렉터리에 패키지 의존성을 풀고 대상 로더로
실행해 JSON·수학 함수·한글 Unicode 문자열·구문/실행 오류 처리·오류 후 정상
평가를 확인했다. 로더가 해석한 공유 라이브러리 경로는 모두 임시 대상 루트 안이었다.
이 결과는 전체 upstream 테스트나 Polkit 권한 승인 규칙 검증을 대신하지 않는다.
기존 로그인 정책, server-core 프로필 및 GTK11 ISO는 변경하지 않았다.

### Linux-PAM 인증 기반 패키지 (2026-09-09)

#### pam_unix 암호 경로 추가 검증

후속 실패 잠금 검증: 같은 임시 chroot 시험에 `pam_faillock`의
preauth/authfail/authsucc 연결을 추가했다. 최신 실행은 테스트 1개 통과(35.377초).
기존 다섯 계정 사례에 더해 다음을 확인했다.

- 두 번 실패 후 정상 인증하는 순서를 두 차례 반복해 성공 시 실패 카운터가
  초기화되고 비연속 실패가 잠금으로 이어지지 않음을 확인했다.
- 세 번 연속 실패 후 올바른 암호를 제공해도 거부됨을 확인했다.
- 임시 `/run/faillock/fixture` 기록이 생성됐으며, 같은 chroot 안에서
  `faillock --user fixture --reset` 실행 후 정상 인증이 회복됐다.

시험 설정은 `deny=3`, `fail_interval=900`, `unlock_time=0`이다. 재현성을 위한
시험 정책일 뿐 배포 기본 보안 정책으로 채택한 것은 아니다. 기록·설정·계정은
임시 chroot 안에만 있고 종료 후 정리된다. 호스트 잠금 상태와 기존 ISO는 변경하지 않았다.
시간 경과 자동 해제, 병렬 인증, 재부팅 후 기록 보존, 비특권 호출, 실제 GDM 로그인은
아직 검사하지 않았다.

`tools/test_pam_unix_runtime.py`를 추가했다. Linux root로 임시 chroot에만
합성 passwd/group/shadow와 PAM 정책을 생성한다. 실제 사용자 암호나 호스트
`/etc/pam.d`는 사용하지 않으며 마운트/장치 생성도 하지 않는다.

```sh
KIKI_TEST_PAM_UNIX=1 PYTHONPATH=tools python3 -B -m unittest test_pam_unix_runtime -v
```

최종 테스트 1개 통과(19.153초), 다섯 사례:
올바른 SHA-512 crypt 암호 인증·계정 검사 성공, 잘못된 암호 거부,
`!`로 잠긴 계정 거부, 존재하지 않는 계정 거부, 만료 계정의 암호 인증 성공 후
`PAM_ACCT_EXPIRED` 반환을 확인했다.

첫 실행은 올바른 암호도 `PAM_PERM_DENIED`로 실패했다. 모듈 dlopen은 성공했고,
helper가 빈 환경으로 exec되므로 상위 로더의 `--library-path`를 상속하지 않는
구조를 확인했다. 임시 chroot 내부의 대상 ldconfig로 라이브러리 캐시를 생성한
후 다섯 사례가 통과했다. 따라서 초기 결과를 PAM 패키지 결함으로 확정하지 않는다.
실제 설치 환경에서도 helper의 독립 실행이 가능한 링커 경로를 유지해야 한다.

이 시험은 root 호출 경로다. 비특권 helper의 setuid/그룹 권한, 암호 변경,
GDM/Polkit 세션, 실제 VM 로그인은 아직 미검증이다. 연속 실패 잠금의 후속
검증 범위는 위 결과를 참고한다.
PAM 패키지나 기존 ISO는 변경하지 않았다.

[공식 Linux-PAM 1.7.2 릴리스](https://github.com/linux-pam/linux-pam/releases/tag/v1.7.2)
기반 개발용 패키지를 추가했다. `auth-foundation.toml` 프로필은 인증 라이브러리
검증용이며 server-core/ISO 기본 프로필에는 추가하지 않았다.

- 기존 sudo 레시피는 `--without-pam`을 유지한다. GDM/Polkit 및 로그인 서비스의
  PAM 정책 연결은 아직 구현하지 않았다. 호스트 인증 설정은 변경하지 않았다.
- 대상 glibc/libxcrypt/systemd를 연결하고 pam_unix 및 logind를 활성화했다.
  문서 생성과 예제는 비활성화했으며 선택 의존성을 모두 제공한다는 의미는 아니다.
- 빌드 `/tmp/kiki-pam-build-LY8uAVRA`, 키 `838ddacec1b9`, 종료 코드 0.
  패키지 `dist/ki2/packages/x86_64/linux-pam-1.7.2-1.x86_64.ki2`, 462,221바이트,
  SHA-256 `7ed25fd6823dacc0f1846c599384754dea55df075d93652402943ca9aabd428a`.
- 소스 SHA-256 `3d86b6383fb5fd9eb9578d2cd47d92801191f4bf3f9bc61419bfefc8aa1e531a`.
  다운로드 해시를 고정했으며 독립적인 배포 서명 검증은 수행하지 않았다.
- Copyright/COPYING 고지를 보존하고 libpam/pam_unix의 RPATH/RUNPATH 부재를
  확인했다. Meson deprecated 옵션 및 Python 버전 경고는 발생했다.

```sh
KIKI_TEST_PAM=1 PYTHONPATH=tools python3 -B -m unittest test_pam_runtime -v
```

테스트 1개 통과(19.447초): 패키지 대상 로더/라이브러리로 임시 PAM 정책의
permit 성공, deny 실패, 모듈 누락 실패를 확인했다. `pam_start_confdir`에
임시 디렉터리를 명시하고 절대 모듈 경로를 사용했으며 `/etc/pam.d`는 변경하지 않았다.
테스트용 permit 정책을 설치 기본값으로 제공하지 않는다.

실제 암호 검증/변경, 실패 횟수 제한·잠금, 비특권 unix_chkpwd 권한 구성,
systemd pam_systemd 세션, GDM 및 Polkit 통합, 전체 upstream 시험은 남아 있다.
PAM 패키지 빌드 성공은 GNOME 로그인 준비 완료가 아니며 기존 GTK11 ISO도 변경하지 않았다.

### libimobiledevice 기반 패키지 추가 (2026-09-09)

[공식 1.4.0 릴리스](https://github.com/libimobiledevice/libimobiledevice/releases/tag/1.4.0)
소스로 장치 통합 라이브러리와 CLI 20개를 빌드했다. GNOME 전원 관리 의존성
준비 단계이며, GNOME 세션이나 USB 장치 연동이 완료됐다는 뜻은 아니다.

- `--with-gnutls --without-openssl`을 함께 지정해 GnuTLS 백엔드를 선택했다.
  `--without-openssl`만으로 GnuTLS가 자동 선택된다고 가정하지 않는다.
- Cython 바인딩은 비활성화했으며 C 라이브러리와 도구를 제공한다.
- 패키지: `dist/ki2/packages/x86_64/libimobiledevice-1.4.0-1.x86_64.ki2`,
  500,644바이트, SHA-256 `ff5c55a2ddfbc4bb35945e52001a0bf3b78f066a96d717fd43146643e41d7680`.
- 소스 SHA-256 `23cc0077e221c7d991bd0eb02150a0d49199bcca1ddf059edccee9ffd914939d`.
  다운로드 해시를 고정했으며 독립적인 서명 검증을 완료한 것은 아니다.
- 빌드 `/tmp/kiki-imobile-build-ZlI9UBkw` 종료 코드 0.
- COPYING/COPYING.LESSER 및 빌드 전 제3자 소스를 고지용으로 보존했다.
  Ed25519 README는 Zlib 라이선스를 명시하지만 별도 LICENSE 파일은 배포
  아카이브에 없었다. 이를 포함해 배포 전 전체 소스·고지 제공 점검은 남아 있다.

검증 명령:

```sh
KIKI_TEST_IMOBILE=1 PYTHONPATH=tools python3 -B -m unittest test_libimobiledevice_runtime -v
```

테스트 1개 통과(12.400초): CLI 20개의 도움말·버전, KIKI 패키지 경로로만
해결되는 동적 의존성, RPATH/RUNPATH 부재를 확인했다. 주 라이브러리가
GnuTLS/libgcrypt에 직접 연결되며 OpenSSL에 직접 연결되지 않음을 검사했다.
전이 의존성인 libtatsu/curl의 OpenSSL 사용까지 제거했다는 뜻은 아니다.
실제 장치 검색, 페어링, 백업, 전원 상태 조회는 수행하지 않았다.
기존 ISO는 변경하지 않았으며 이 패키지는 아직 ISO에 반영하지 않았다.

### GnuTLS 기반 패키지 추가 (2026-09-09)

`crypto-foundation.toml`과 개발용 `gnome-foundation` 프로필에 GnuTLS
3.8.13-1을 추가했다. 프로젝트 이름과 대시보드는 변경하지 않았다.
대상 sysroot의 Nettle, GMP, libtasn1, libunistring, libidn2, p11-kit,
zlib/zstd 및 C++ 런타임을 연결한다. 기본 CA 파일은
`/etc/ssl/certs/ca-certificates.crt`이며 PKCS#11 기능을 유지했다.
DANE, TPM, Brotli 의존성은 없으므로 해당 선택 기능은 제공되지 않는다.

- 빌드 디렉터리: `/tmp/kiki-gnutls-build-W399j8Nf`, 종료 코드 0.
- 패키지: `dist/ki2/packages/x86_64/gnutls-3.8.13-1.x86_64.ki2`, 1,939,291바이트.
- 패키지 SHA-256: `4054cecea02826cef44ffccdedd086498ae01981c5cb8614fb83b4633a6b8fe2`.
- 소스 SHA-256: `ffed8ec1bf09c2426d4f14aae377de4753b53e537d685e604e99a8b16ca9c97e`.
  다운로드한 공식 배포 파일의 해시를 고정했으며 독립 서명 검증 완료를 뜻하지 않는다.
- GPL/LGPL, x86 가속, inih, crau, CC0 고지를 패키지에 보존했다.
- libgnutls/libgnutlsxx, gnutls-cli, certtool의 RPATH/RUNPATH 부재를 확인했다.
  선택 include 디렉터리 누락과 upstream 경고는 발생했으며 무경고 빌드는 아니다.

검증 명령 (Linux root, 임시 chroot만 사용):

```sh
KIKI_TEST_GNUTLS=1 PYTHONPATH=tools python3 -B -m unittest test_gnutls_runtime -v
```

테스트 1개 통과(11.004초). 패키지와 런타임 의존성만 추출한 환경에서
gnutls-cli/certtool 버전 실행, 기본 CA 147개 로딩, `한국.한국` IDNA 변환을
확인했다. 네트워크, 마운트, 호스트 신뢰 저장소 변경은 수행하지 않았다.
CA 최신성, TLS 핸드셰이크/인증서 거부, 전체 upstream 테스트, GNOME 세션 및
실제 ISO 설치를 검증한 결과는 아니다. 기존 ISO는 그대로이며 이 패키지는
아직 ISO에 반영하지 않았다.

[GNOME 공식 50.4 빌드 메타데이터](https://download.gnome.org/sources/gnome-build-meta/50/)
아카이브를 내려받아 공식 SHA-256과 대조했다. 핵심 네 구성 요소의 버전과 해시를
`distro/specs/gnome-desktop-sources.toml`에 기록했다. 이 파일은 계획용 잠금 정보이며
실행 가능한 `.ki2` 빌드 레시피나 전체 의존성 잠금 파일이 아니다.

공식 메타데이터의 Shell/Mutter/GDM/Session 정의를 검토했다. GTK뿐 아니라
GJS, GNOME 설정 서비스, 계정 서비스, dconf, GDM 인증 구성, NetworkManager,
Wayland/그래픽·입력 라이브러리 등의 통합이 필요하다. 현재 KIKI의 GTK+Cage
설치 런타임을 GNOME 데스크톱의 대체물로 취급하지 않는다.

## 구현 및 검증 순서

1. 전체 의존성과 기존 KIKI 레시피 버전/ABI 차이를 산출한다.
2. 핵심 라이브러리·인증/PAM·사용자 D-Bus/systemd 세션을 네이티브 패키지로 준비한다.
3. GNOME Shell/Mutter/GDM/Session과 필요한 설정·파일·터미널 앱을 빌드한다.
4. 실제 패키지 집합이 준비된 뒤 `desktop-gnome` 선택형 그룹/프로필을 노출한다.
5. 서버 프로필의 systemd-networkd와 GNOME 네트워크 관리 서비스가 같은 인터페이스를
   동시에 관리하지 않도록 프로필별 소유권을 결정하고 시험한다.
6. tty1 AI / tty2 복구 셸과 GDM의 VT 할당이 충돌하지 않는지 실기 검증한다.
   아직 확인하지 않은 GDM 설정 키를 임의로 적용하거나 기존 콘솔 요구를 바꾸지 않는다.
7. 동일 ISO에서 설치, 로그인/로그아웃, 재부팅, 한글 입력, 네트워크, AI 명령 승인,
   GUI 실패 시 콘솔 복구를 시험한다.

빌드 방식은 [GNOME 공식 빌드 안내](https://handbook.gnome.org/development/building.html)와
각 모듈의 지침을 기준으로 확인한다. GNOME OS 이미지를 KIKI 설치 결과로 바꿔 부르지 않는다.

현재 검증용 ISO에는 GNOME 기반 패키지가 일부 있지만 완성된 데스크톱은 없다. Hyper-V 접근과 폐기 가능한
테스트 VM이 아직 확보되지 않아 실기 검증도 미완료다.

## 기반 패키지 진행

### 암호 라이브러리 의존성 — libgpg-error 준비

GNOME 50.4 메타데이터의 libimobiledevice 1.4.0 정의는 GnuTLS/libgcrypt와
`--disable-openssl`을 사용한다. GnuTLS는 아직 KIKI 네이티브 레시피에 없으며,
libgcrypt는 아래 후속 작업에서 패키지 빌드와 제한된 런타임 검사를 완료했다.
libgcrypt의 기반 libgpg-error부터 개발용 gnome-foundation 프로필에 추가했다.
기존 ISO와 서버 기본 패키지 집합은 변경하지 않았다.

libgpg-error 1.61 공식 소스 SHA-256은
`7a85413f2bc354f4f8aa832b718af122e48965e9e0eb9012ee659c13c6385c93`이며
[GnuPG 공식 무결성 목록](https://gnupg.org/download/integrity_check.html)과 일치한다.
소스 README/도구 헤더에서 LGPL-2.1-or-later 및 gpgrt-config의 FSFULLR 고지를
확인했다. PGP 서명 검증을 수행한 것으로 간주하지 않는다.
공유 라이브러리/도구/헤더를 빌드하고 `.la`는 제외하며 ELF RPATH/RUNPATH를 검사한다.
문서 빌드는 비활성화했으며 런타임 API나 NLS를 비활성화하지 않았다.
현재 작업 경로 `/tmp/kiki-gpg-error-iTwIQsU0`, 빌드 키 `69ec82682ea7`.
빌드는 종료 코드 0으로 완료됐고 필수 ELF RPATH/RUNPATH 부재 검사도 통과했다.
패키지 `libgpg-error-1.61-1.x86_64.ki2`, 368,637바이트, SHA-256:
`07392774d499c00e626f45f03a7875b339a1c21d2605fbc28bdee0f1752f114a`.
릴리스 1 대상 런타임 검사 1개가 통과했다. `tools/test_gpg_error_runtime.py`는
KIKI glibc/헤더로 검사 프로그램을 만들고 KIKI 로더에서 libgpg-error와 libc가
대상 루트 안에서만 해석되는지 확인한다. errno 10종의 명시적 대응 및 역변환,
4개 스레드의 gpgrt 잠금으로 보호한 40,000회 카운터 증가와 잠금 해제를 검사했다.
전체 오류 번호/ABI 또는 암호 기능 검증을 의미하지 않는다.

빌드 로그에서 오류 번호 헤더의 전처리 명령에 CFLAGS가 적용되지 않는 것을 확인해
릴리스 2의 CC 자체에 `--sysroot=${KI2_SYSROOT}`를 명시했다. 호스트에서 실행되는
빌드 보조 프로그램은 별도 호스트 컴파일러를 유지한다.
새 경로 `/tmp/kiki-gpg-error-target-p7iWsMeo`, 키 `6e652a7a2ca5`에서
릴리스 2 빌드가 종료 코드 0으로 완료됐다. 새 패키지로 같은 런타임 검사를 재실행해
통과했다. 패키지 `libgpg-error-1.61-2.x86_64.ki2`, 368,539바이트, SHA-256:
`8d0dfac2a7fcc4e3d7aae9057f4eaf7b08773bd65716b9d559ed2291b87283a6`.
이전 릴리스와 ISO는 보존했다. 이 패키지는 아직 ISO에 포함하지 않았다.

검사 명령:
```sh
PYTHONPATH=tools KIKI_TEST_GPG_ERROR=1 python3 -B -m unittest test_gpg_error_runtime -v
```

### libgcrypt 1.12.3 — 패키지 및 upstream 런타임 검사

2026-09-09 개발용 gnome-foundation 프로필에 libgcrypt를 추가했다.
공식 소스의 SHA-256
`98d1b0b3202d2b03fa754a35aa3cbbfcf526a3260d8d2ee213748001b1043006`을
[GnuPG 무결성 목록](https://gnupg.org/download/integrity_check.html)과 대조했다.
PGP 서명 검증은 수행하지 않았다. COPYING, COPYING.LIB, LICENSES, AUTHORS를
`/usr/share/licenses/libgcrypt`에 포함했으며 원본과 바이트 단위 일치를 검사했다.

KIKI sysroot의 glibc와 libgpg-error 1.61-2를 사용해 공유 라이브러리,
헤더 및 도구를 빌드했다. 문서와 정적 라이브러리는 비활성화했으며
암호 알고리즘 집합은 별도로 축소하지 않았다.
빌드 경로 `/tmp/kiki-libgcrypt-igEEyebb`, 키 `050935b89e64`, 종료 코드 0.
패키지 `libgcrypt-1.12.3-1.x86_64.ki2`, 770,361바이트, SHA-256:
`2ef29122bec7f589a050f2836329d7041b9e0032f5c4ab08a4c02b364d52d9a5`.
공유 라이브러리에 RPATH/RUNPATH가 없고 불필요한 libgcrypt.la는 제외했다.

`tools/test_libgcrypt_runtime.py`의 unittest 1개에서 upstream 실행 파일 8개
(version, basic, hmac, t-kdf, mpitests, t-sexp, aeswrap, keygrip)가 통과했다.
첫 실행은 upstream 테스트 ELF의 RPATH가 빌드 트리 라이브러리를 선택해
경로 검증에서 실패했다. 테스트 로더의 `--inhibit-rpath ''`로 이를 제외한 뒤,
각 실행 파일의 libgcrypt/libgpg-error/libc가 추출한 패키지 루트 안에서만
해석되는지 확인하고 다시 실행했다. 최종 실행은 15.905초, 종료 코드 0.

재현 명령:
```sh
PYTHONPATH=tools \
KIKI_LIBGCRYPT_TEST_SOURCE=/tmp/kiki-libgcrypt-igEEyebb/x86_64/work/libgcrypt/source/libgcrypt-1.12.3 \
python3 -B -m unittest test_libgcrypt_runtime -v
```

upstream 전체 테스트 집합, FIPS 인증, 모든 CPU 경로 또는 GNOME 통합 검증은 아니다.
기존 ISO와 서버 기본 패키지 집합은 변경하지 않았다.
다음 작업은 GnuTLS 의존성 구성과 libimobiledevice 통합이다.

### GnuTLS 의존성 — 기존 GMP 대상 빌드 보완

GnuTLS 공식 설치 안내는 Nettle과 GMP를 필수 의존성으로 명시한다:
https://www.gnutls.org/manual/html_node/Downloading-and-installing.html
현재 YAML/TOML 레시피를 모두 검색해 GMP는 기존 kubernetes.yaml에 있지만,
당시 Nettle/GnuTLS/libtasn1/p11-kit/libunistring 레시피는 없는 것을 확인했다.
Nettle은 아래 후속 작업에서 추가했다.

기존 GMP 6.3.0-1은 sysroot에서 glibc를 제외하고 호스트 환경으로 빌드했다.
릴리스 2는 linux-headers 빌드 의존성, 대상 CC/sysroot/링크 경로,
명시적 build/host 및 x86 fat 라이브러리를 사용하도록 보완했다.
기존과 같이 C 공유 라이브러리를 제공하며 C++ 바인딩을 새로 활성화하지 않았다.
기존 소스 캐시의 SHA-256
`a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898`은
저장소의 기존 GMP 소스 핀과 일치한다. 이번 작업에서 별도 서명을 검증하지 않았다.
COPYING/COPYING.LESSERv3/COPYINGv2 고지 포함과 ELF RPATH/RUNPATH 검사를 추가했다.

빌드 작업 경로는 `/tmp/kiki-gmp-XFbBqD1h`이다.
빌드는 종료 코드 0으로 완료됐고 필수 ELF RPATH/RUNPATH 부재 검사도 통과했다.
패키지 `gmp-6.3.0-2.x86_64.ki2`, 503,376바이트, SHA-256:
`d2ccad484e4dd6ede9a6dea7668d55017d3545701091c891457fd992200671b8`.
후속으로 `tools/test_gmp_runtime.py`에서 upstream `make check`를 실행했다.
2026-09-09 총 178개 중 PASS 177, SKIP 1, FAIL/ERROR 0으로 종료 코드 0,
35.128초였다. SKIP은 `mpn/t-addaddmul`이며 해당 네이티브 함수가
없는 구성에서는 upstream 소스가 명시적으로 77을 반환한다.
이 항목을 통과로 계산하지 않는다.

각 ELF 테스트를 실행하기 전에 대상 로더의 의존성 목록을 검사하여 모든
해석된 라이브러리가 추출한 KIKI 패키지 루트 내부에 있는지 확인했다.
테스트 전용 빌드 트리 RPATH는 로더에서 제외했다. 라이선스 파일도 원본과 대조했다.
호스트 make/컴파일러로 테스트를 빌드하고 KIKI 라이브러리로 실행한 것이며,
다른 CPU 전체 경로, C++ 바인딩 또는 실제 설치 VM을 검증한 것은 아니다.

재현 명령:
```sh
PYTHONPATH=tools \
KIKI_GMP_TEST_SOURCE=/tmp/kiki-gmp-XFbBqD1h/x86_64/work/gmp/source/gmp-6.3.0 \
python3 -B -m unittest test_gmp_runtime -v
```
이전 패키지와 ISO는 보존하며 GNOME 제공 완료로 간주하지 않는다.

### Nettle/Hogweed 3.10.2 패키지 빌드

2026-09-09 Nettle을 개발용 gnome-foundation 프로필에 추가했다.
API 변경이 있는 4 계열 대신 기존 GnuTLS 의존성 구성을 위한 3 계열을 선택했다.
[공식 4.0 발표](https://lists.lysator.liu.se/mailman/hyperkitty/list/nettle-bugs%40lists.lysator.liu.se/thread/D4IKICV4QZHHGRXW3D6VS7GTMLBZF65C/)
는 3 계열의 심각한 버그에 대한 유지보수를 설명한다.
이는 GnuTLS 통합이 이미 검증됐다는 의미가 아니다.

공식 GNU FTP에서 내려받은 소스의 SHA-256을 레시피에 고정했다:
`fe9ff51cb1f2abb5e65a6b8c10a92da0ab5ab6eaf26e7fc2b675c45f1fb519b5`.
이번 작업에서 별도의 서명 또는 독립된 체크섬 목록 대조는 수행하지 않았다.
KIKI glibc와 GMP 6.3.0-2를 사용하고 호스트 빌드 보조 컴파일러는 별도로 지정했다.
공유 Nettle/Hogweed, 헤더와 도구를 제공하며 정적 라이브러리와 문서 빌드,
벤치마크 프로그램의 OpenSSL 연동은 제외했다. 공개키 알고리즘은 유지했다.
COPYINGv2/COPYINGv3/COPYING.LESSERv3/AUTHORS를 패키지에 포함했다.

빌드 경로 `/tmp/kiki-nettle-lNEdNEQy`, 종료 코드 0.
패키지 `nettle-3.10.2-1.x86_64.ki2`, 1,214,041바이트, SHA-256:
`8c1c36fa6887d8af8e1e102c07a2c11ce125f878914bd5709c1453f8601a90a0`.
libnettle.so.8와 libhogweed.so.6의 RPATH/RUNPATH 부재 검사를 통과했다.
후속으로 `tools/test_nettle_runtime.py`가 upstream Makefile의 TS_C 집합을
빌드한 뒤 패키징된 KIKI 라이브러리로 실행했다. 2026-09-09 총 115개 C 테스트 중
114개 통과, `x86-ibt-test` 1개 건너뜀, 최종 unittest 종료 코드 0(11.440초).
첫 실행은 건너뜀 코드 77을 실패로 집계했다. upstream 소스에서 CET/IBT 조건에
따른 명시적 SKIP임을 확인해 집계를 보완하고 전체 C 집합을 다시 실행했다.
건너뜀을 통과로 계산하지 않으며 이 환경에서 CET/IBT 작동을 입증하지 않는다.

각 테스트의 동적 의존성이 임시 패키지 루트 내부에서만 해석되는지 확인했다.
Nettle/Hogweed/GMP/glibc 로딩과 라이선스 원본 바이트 일치도 검사했다.
C++ 테스트, 셸 심볼 검사, dlopen 전용 검사, Valgrind 및 별도 CPU override
조합은 이번 TS_C 검사 범위 밖이다. upstream 전체 make check 통과로 표현하지 않는다.
GnuTLS 통합은 아직 미완료다.

재현 명령:
```sh
PYTHONPATH=tools \
KIKI_NETTLE_TEST_SOURCE=/tmp/kiki-nettle-lNEdNEQy/x86_64/work/nettle/source/nettle-3.10.2 \
python3 -B -m unittest test_nettle_runtime -v
```
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### libtasn1 4.21.0 패키지 빌드

2026-09-09 ASN.1/DER 라이브러리 libtasn1을 개발 프로필에 추가했다.
[GNU 공식 매뉴얼](https://www.gnu.org/software/libtasn1/manual/libtasn1.html)의
4.21.0 버전을 기준으로 공식 FTP 소스를 사용했다. 다운로드 SHA-256:
`1d8a444a223cc5464240777346e125de51d8e6abf0b8bac742ac84609167dc87`.
이 해시를 레시피에 고정했으며 별도 서명·독립 체크섬 대조는 미수행이다.

KIKI sysroot/CC/링크 경로로 공유 라이브러리와 CLI 도구를 빌드했다.
정적 라이브러리와 문서 빌드는 제외하고 COPYING/COPYING.LESSERv2/README.md를
패키지에 포함했다. 라이브러리는 LGPL-2.1-or-later, CLI는 GPL-3.0-or-later다.
빌드 경로 `/tmp/kiki-libtasn1-1iSV45CI`, 종료 코드 0.
공통 플래그의 선택적 sysroot/include가 없다는 컴파일 경고가 있었지만 빌드는 성공했다.

패키지 `libtasn1-4.21.0-1.x86_64.ki2`, 106,995바이트, SHA-256:
`04458ee21c81e23c764ab9524f9ea879639b631acecc516165a109e7e3b3f2a4`.
libtasn1.so.6의 RPATH/RUNPATH 부재 검사는 통과했다.
후속으로 `tools/test_libtasn1_runtime.py`에서 upstream C 테스트 24개를 실행해
24개 통과, SKIP/FAIL/ERROR 0, 종료 코드 0(10.548초)을 확인했다.
테스트용 CVE-2018-1000654 헤더 2개는 패키지의 asn1Parser를 KIKI 로더로 실행해
생성했다. 각 테스트 및 생성 도구의 libtasn1/libc 의존성이 임시 패키지 루트
내부에서만 해석되는지 확인했고 라이선스 파일을 원본과 바이트 단위로 대조했다.
upstream TESTS_ENVIRONMENT의 ASN1 입력 파일 설정을 유지했다.

재현 명령:
```sh
PYTHONPATH=tools \
KIKI_LIBTASN1_TEST_SOURCE=/tmp/kiki-libtasn1-1iSV45CI/x86_64/work/libtasn1/source/libtasn1-4.21.0 \
python3 -B -m unittest test_libtasn1_runtime -v
```

별도 셸 테스트 7개(crlf, threadsafety, decoding, invalid-x509, invalid-pkcs7,
coding, parser), Valgrind 및 GnuTLS 통합은 아직 미검증이다.
upstream 전체 make check 통과 또는 실제 VM 설치 검증으로 표현하지 않는다.
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### GnuTLS Unicode 의존성 — libunistring

[GnuTLS 3.8.13 configure.ac](https://raw.githubusercontent.com/gnutls/gnutls/3.8.13/configure.ac)
에서 기본 구성은 시스템 libunistring의 u8_normalize를 요구하는 것을 확인했다.
내장 사본으로 대체하는 대신 KIKI 개발 프로필에 libunistring 1.4.2 레시피를 추가했다.
PKCS#11의 p11-kit과 국제화 도메인 처리의 libidn2는 여전히 후속 구성 대상이다.
GnuTLS의 시스템 신뢰 저장소는 기존 KIKI의
`/etc/ssl/certs/ca-certificates.crt`를 명시적으로 지정할 계획이며 아직 적용하지 않았다.

GNU 공식 소스 다운로드의 SHA-256:
`5b46e74377ed7409c5b75e7a96f95377b095623b689d8522620927964a41499c`.
레시피에 이 해시를 고정했으며 별도 서명 검증은 미수행이다.
대상 sysroot의 glibc/헤더로 공유 라이브러리를 빌드하고 정적 라이브러리는 제외한다.
문서는 기본 설치를 유지하며 COPYING/COPYING.LIB/README 및 문서 FDL 고지를 포함한다.
작업 경로는 `/tmp/kiki-unistring-ecoiW7gv`이다.
빌드가 종료 코드 0으로 완료됐다. 패키지
`libunistring-1.4.2-1.x86_64.ki2`, 1,029,538바이트, SHA-256:
`84df9b09ab2a9b49647d36d20e1a2f0b8810d19ea5ddc93d784f22e3bb40006f`.
libunistring.so.5의 RPATH/RUNPATH 부재 검사를 통과했다.

`tools/test_unistring_runtime.py`를 실행해 테스트 1개가 통과했다(9.383초).
KIKI 대상 헤더/라이브러리로 C 검사 프로그램을 컴파일하고 대상 로더로 실행했다.
완성형 한글 11,172자 각각의 NFD 결과를 초성/중성/종성 계산값과 대조한 뒤
NFC 재결합이 원본과 일치하는지 검사했다. UTF-8 e+결합 악센트의 NFC 결과도 검사했다.
libunistring/libc가 임시 패키지 루트 내부에서 해석되는 것을 확인했다.
이는 Unicode 전체 적합성, upstream 전체 테스트, 한글 글꼴 렌더링이나 입력기 검증이 아니다.

재현 명령:
```sh
PYTHONPATH=tools KIKI_TEST_UNISTRING=1 python3 -B -m unittest test_unistring_runtime -v
```
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### libidn2 국제화 도메인 의존성

2026-09-09 libidn2 2.3.8을 개발 프로필에 추가했다.
[공식 매뉴얼](https://www.gnu.org/software/libidn/libidn2/manual/html_node/Introduction.html)
에서 IDNA2008/TR46 및 libunistring 의존성을 확인했다.
GNU FTP 소스 다운로드 SHA-256을 레시피에 고정했다:
`f557911bf6171621e1f72ff35f5b1825bb35b52ed45325dcdee931e5d3c0787a`.
별도 서명 검증은 수행하지 않았다.

KIKI libunistring/glibc에 연결해 공유 라이브러리와 idn2 CLI를 빌드한다.
정적 라이브러리와 문서 생성은 제외하고 COPYING/COPYINGv2/COPYING.LESSERv3,
COPYING.unicode 및 README.md를 패키지에 포함한다.
라이브러리와 CLI의 RPATH/RUNPATH 부재를 필수 검사로 추가했다.
첫 작업 경로 `/tmp/kiki-libidn2-k53ExDqH`에서 컴파일·설치 후 ELF 검사가 실패했다.
라이브러리와 CLI의 RPATH에 임시 sysroot/usr/lib가 남았으며 LIBUNISTRING 및
LTLIBUNISTRING 변수에서 이를 생성한 것을 확인했다.
공식 configure 옵션 `--disable-rpath`를 적용하고
`/tmp/kiki-libidn2-clean-PA3QuVJ8`에서 재빌드를 시작했다.
재빌드는 종료 코드 0으로 완료됐으며 라이브러리·CLI의 RPATH/RUNPATH 검사도 통과했다.
패키지 `libidn2-2.3.8-1.x86_64.ki2`, 193,500바이트, SHA-256:
`a49ed76f6956314d7f863c1a1d8bd6851f9821a9f77bb6610f761ec3390e639a`.

`tools/test_idn2_runtime.py` 테스트 1개가 통과했다(9.308초).
한국.한국, 한글.example, 서울.example, bücher.example을
IDNA 비전이/STD3 모드에서 ASCII로 변환하고 다시 원본 Unicode로 복원했다.
기대 ASCII 값은 Python의 Punycode 코덱으로 독립 계산했다.
하이픈으로 시작하는 잘못된 라벨도 거부하는 것을 확인했다.
libidn2/libunistring/libc의 해석 경로가 추출한 패키지 루트 내부인지 검사했다.

재현 명령:
```sh
PYTHONPATH=tools KIKI_TEST_IDN2=1 python3 -B -m unittest test_idn2_runtime -v
```

이는 선택한 4종의 라이브러리 API 검사이며 IDNA/TR46 전체 적합성이나
CLI의 모든 기능을 검증한 것은 아니다. 외부 DNS 조회·TLS 연결은 수행하지 않았으며
GnuTLS 통합은 아직 미완료다.
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### p11-kit 준비 — libffi 대상 빌드 보완

기존 libffi 3.4.8-1은 glibc를 sysroot에서 제외하고 호스트 환경으로 빌드했다.
릴리스 2는 KIKI glibc/헤더/링크 경로 및 명시적 build/host를 사용하고
MIT LICENSE 파일과 RPATH/RUNPATH 검사를 추가했다. 기존 버전은 보존한다.
이는 libffi 버전 업그레이드나 전체 보안 검증을 뜻하지 않는다.

첫 경로 `/tmp/kiki-libffi-o5ArvMdT`에서는 upstream의 multi-OS 디렉터리
규칙이 /usr/lib 설정을 /usr/lib64로 변경하여 최종 ELF 경로 검사가 실패했다.
공식 `--disable-multi-os-directory` 옵션을 추가하고
`/tmp/kiki-libffi-final-OrS2nHgO`에서 재빌드를 시작했다.
재빌드는 종료 코드 0으로 완료됐다(키 `c1a9fdd80eb3`).
패키지 `libffi-3.4.8-2.x86_64.ki2`, 34,561바이트, SHA-256:
`65b6b05e28a5ddd59b8f05c61b25885dc1b432daf50740a1456ddc33b94ef8d7`.
실제 ELF 의존성은 libc.so.6이며 RPATH/RUNPATH 부재 검사도 통과했다.
`tools/test_ffi_runtime.py` 1개가 통과했다(9.238초).
KIKI 헤더·라이브러리로 C 프로그램을 컴파일하고 대상 로더로 실행해
int/double 혼합 인자의 ffi_call, 실행 가능한 클로저 할당·콜백·해제를 확인했다.
libffi/libc가 추출된 패키지 루트 내부에서 해석되는지 검사했다.
upstream 전체 ABI/구조체/가변 인자 테스트나 실제 GNOME 세션 검증은 아니다.

재현 명령:
```sh
PYTHONPATH=tools KIKI_TEST_FFI=1 python3 -B -m unittest test_ffi_runtime -v
```
p11-kit 패키지 구현과 GnuTLS 통합은 여전히 미완료다.
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### p11-kit 0.26.5 구성

공식 GitHub 릴리스 API에서 0.26.5와 소스 자산 SHA-256을 확인하고 다운로드와 대조했다:
`f2cc09111e44bf3fea58f023180b33acea90aa82d042d6fbb623fbc5ba033bb7`.
PGP 서명을 검증한 것으로 간주하지 않는다.
개발 프로필에 p11-kit 레시피를 추가하고 libffi, libtasn1, glibc 및 CA 번들을
런타임 의존성으로 선언했다. systemd는 소켓 활성화 설정용 빌드 의존성이다.

Meson cross 파일로 대상 아키텍처와 KIKI 실행 래퍼를 지정했다.
빌드 중 asn1Parser도 대상 로더로 실행하도록 별도 래퍼를 추가했다.
libffi, trust_module, systemd 지원은 명시적으로 활성화하며 테스트 빌드 기본값을 유지한다.
신뢰 모듈 입력 경로는 `/etc/ssl/certs/ca-certificates.crt`로 지정했다.
이는 인증서 갱신이나 실제 PKCS#11 토큰 검증을 완료했다는 뜻이 아니다.

작업 경로 `/tmp/kiki-p11-kit-jo5oodZv`에서 빌드가 종료 코드 0으로 완료됐다.
패키지 `p11-kit-0.26.5-1.x86_64.ki2`, 1,526,803바이트, SHA-256:
`6f2a1969af231bcb926aa53d4133b89573a7c28e291e812bd816f0f7dc3b0f18`.
libp11-kit.so.0의 RPATH/RUNPATH 부재 검사가 통과했다.
설치 산출물에서 p11-kit/trust CLI, client/trust 모듈, 공개 헤더를 확인했다.
ELF 의존성은 라이브러리가 libffi/libc, 신뢰 모듈이 libtasn1/libc 및 대상 로더로,
선언한 패키지 의존성 안에 포함된다.
upstream 경고(일부 반환값 미사용 등)가 있었으며 경고 없는 빌드라고 표현하지 않는다.
테스트 프로그램 컴파일은 완료됐지만 실행은 아직 하지 않았다.
후속으로 `tools/test_p11_trust_runtime.py` 테스트 1개가 통과했다(8.798초).
Linux root 권한은 임시 패키지 루트로 chroot하는 데만 사용했으며
장치 마운트, 호스트 인증서 저장소 변경 또는 외부 네트워크 접근은 하지 않았다.
KIKI 로더로 p11-kit list-modules, trust list --filter=ca-anchors 및
trust extract --format=pem-bundle --filter=ca-anchors를 실행했다.
신뢰 모듈 발견과 인증서 목록 조회가 성공했고, 내보낸 CA 147개의 DER 집합이
패키지 원본 번들의 DER 집합과 정확히 일치했다.
기존 CA 번들의 최신성 또는 모든 인증서 정책의 정확성을 입증하는 검사는 아니다.
실제 하드웨어 토큰, 잘못된 인증서·폐기 정책, TLS 연결 및 GnuTLS 통합은 미검증이다.

재현 명령(Linux root, 임시 루트만 사용):
```sh
PYTHONPATH=tools KIKI_TEST_P11_TRUST=1 python3 -B -m unittest test_p11_trust_runtime -v
```
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### curl/libtatsu — 의존성 보완 및 최종 릴리스 런타임 검사 통과

curl의 실제 ELF/공개 링크 정보에서 zstd 의존성을 확인했다. curl 레시피에
zstd 런타임 의존성과 `--with-zstd`를 명시하고 대상 sysroot 컴파일/링크를 적용했다.
릴리스 2의 curl/libtatsu 빌드는 종료 코드 0이며, 선언된 의존성만으로
libtatsu 메모리 요청 생성 및 curl 버전/zstd 기능 표시/로컬 파일 전송 검사가 통과했다.

추가 점검에서 curl의 `.la`와 `curl-config --static-libs`에 임시 sysroot 경로가
남는 것을 확인했다. `.la`만 패키징에서 제외하고 curl-config 템플릿에서 빌드용
LDFLAGS 출력을 제외했다. 공유 라이브러리, 정적 아카이브, 헤더, pkg-config는 유지한다.
curl 실행 파일/공유 라이브러리에 RPATH/RUNPATH가 있으면 빌드를 실패시킨다.
교차 configure 결과에 기본 CA 경로가 비어 있어 KIKI 인증서 패키지의
`/etc/ssl/certs/ca-certificates.crt`를 명시했다. 인증서 검증을 끄는 변경은 없다.

최종 curl 8.8.0-4/libtatsu 1.0.5-4를 `/tmp/kiki-curl-ca-UIhMui71`에서
종료 코드 0으로 빌드했다. 이전 릴리스 패키지는 보존했다.

- `curl-8.8.0-4.x86_64.ki2`: 1,404,770바이트, SHA-256
  `ad99257ba0c1f7b56244914d93bec77318d10e7fe24ff890e5a9a6233345c57b`.
- `libtatsu-1.0.5-4.x86_64.ki2`: 21,234바이트, SHA-256
  `0261b16a5382aae152323a3f5bfac14f618ded49decd84eafebd6cb09cd4db46`.

런타임 검사에는 CURLINFO_CAINFO 기본값, 패키지 내 CA 파일 존재, curl-config 출력,
curl 자체의 대상 라이브러리 해석 및 ELF 경로 검사도 추가했다.
최종 검사 1개가 통과했다. curl-config의 CA 출력은 따옴표를 포함하므로
셸 인자 파싱 후 경로를 비교한다. libtatsu 메모리 요청 생성, curl 로컬 파일 전송,
zstd 의존성 로딩, `.la` 제외/정적 아카이브 보존까지 검사했다.
이 검사는 외부 TSS/HTTPS 통신, TLS 핸드셰이크, 실제 기기 접근을 수행하지 않는다.
curl 및 CA 소스 버전 업데이트나 전체 보안 감사로 간주하지 않는다.
기존 ISO는 변경하지 않았다. 빌더 21개/ISO 생성기 34개 회귀 검사와 범위 지정
Go 검사(`./cmd/... ./internal/... ./deploy/... ./installer/...`, 캐시 포함)가 통과했다.
이는 GUI/TUI/CLI 실제 ISO 설치 시험을 대신하지 않는다.

#### 최초 libtatsu 릴리스 및 실패 재현 기록

GNOME 50.4 메타데이터의 libtatsu 1.0.5 의존성을 준비한다.
[공식 릴리스](https://github.com/libimobiledevice/libtatsu/releases/tag/1.0.5)의
소스 파일 302,913바이트, SHA-256
`536fa228b14f156258e801a7f4d25a3a9dd91bb936bf6344e23171403c57e440`는
GitHub release asset digest와 일치한다. 별도 PGP 검증을 주장하지 않는다.
원본 configure.ac의 libplist >=2.6.0 및 libcurl 의존성, LGPL-2.1-or-later
고지를 확인했다. KIKI libplist/curl을 사용하는 공유 라이브러리 레시피를
개발용 gnome-foundation 프로필에만 추가했다.

빌드 경로 `/tmp/kiki-libtatsu-DEiWDbBt`, 키 `922463a805db`에서 종료 코드 0으로 빌드했다.
libtool 경로 삽입 비활성화, `.la` 패키징 제외, ELF RPATH/RUNPATH 부재 검사를
포함한다. 패키지 `libtatsu-1.0.5-1.x86_64.ki2`, 21,203바이트, SHA-256
`d3ce2eadedab8199d098f8dbf38ddce4d0df3cc89e13176d8d7809abfcce72cd`.

`tools/test_libtatsu_runtime.py`를 추가했다. Linux에서 다음과 같이 실행한다.

```sh
PYTHONPATH=tools KIKI_TEST_LIBTATSU=1 python3 -B -m unittest test_libtatsu_runtime -v
```

선언된 런타임 의존성과 Linux 헤더만 임시 루트에 풀고, 호스트 C 컴파일러로
대상 sysroot용 검사 프로그램을 만든 뒤 KIKI 로더로 버전/메모리 요청 생성/
라이브러리 해석 경로를 확인하도록 구성했다. TSS 전송 함수는 호출하지 않는다.
첫 검사의 pkg-config 파일명 오류는 실제 이름 `libtatsu-1.0.pc`로 교정했다.
재실행에서는 실제 의존성 문제가 발견됐다: libcurl이 요구하는 `libzstd.so.1`이
선언된 런타임 의존성 집합에 없어 검사 프로그램 링크가 실패했다.
현재 curl 레시피의 런타임 목록에는 zstd가 없다. 이 의존성 및 빌드 시 자동 탐지
설정을 정리하고 영향 패키지를 재빌드한 뒤 검사를 다시 실행해야 한다.
따라서 메모리 기능 검사 및 최종 로딩 경로 검사는 아직 통과하지 않았다.
외부 TSS 서버 요청, 기기 접근, 인증 정보 전송은 수행하지 않았다.
기존 ISO와 서버 기본 프로필은 변경하지 않았다.

### libusbmuxd 2.1.1 — 빌드 완료 및 도구 시작 검사

후속 릴리스 2에서는 libusbmuxd 자체의 `.la`에도 남은 임시 sysroot 경로를
확인하고 해당 파일만 패키징 대상에서 제외했다. 이전 릴리스 1 패키지는 보존했다.
빌드 경로 `/tmp/kiki-usbmux-clean-lN5mpuLG`, 키 `e4326f2ce125`, 종료 코드 0.
`libusbmuxd-2.1.1-2.x86_64.ki2`, 37,195바이트, SHA-256
`e0fe6236d1c0c71a2836257fb6c84d8b4c4d438557d3090686aa0784d8f817f8`.
런타임 검사 1개 통과: 기존 도움말·버전·대상 로더 및 ELF 검사에 더해,
libusbmuxd/glue/libplist C·C++의 `.la` 부재와 공유 라이브러리·pkg-config 파일
보존을 확인했다. 실제 장치/네트워크 연결은 수행하지 않았고 ISO도 변경하지 않았다.

#### 이전 릴리스 및 의존성 정리 기록

GNOME 50.4 메타데이터의 버전 2.1.1, 커밋
`adf9c22b9010490e4b55eaeb14731991db1c172c`를 확인했다.
[공식 릴리스](https://github.com/libimobiledevice/libusbmuxd/releases/tag/2.1.1)의
소스 325,055바이트, SHA-256
`5546f1aba1c3d1812c2b47d976312d00547d1044b84b6a461323c621f396efce`는
GitHub release asset digest와 일치한다. 라이브러리 LGPL-2.1-or-later 및
iproxy/inetcat GPL-2.0-or-later 고지를 확인해 패키지 메타데이터에 함께 기재했다.
inotify 및 두 도구를 유지하고 개발 프로필에만 레시피를 등록했다.

첫 빌드 키 `8290ffc6c4c9`, `/tmp/kiki-libusbmuxd-qsNBm33H`는 링크에서 실패했다.
의존성의 `.la` 파일이 호스트 `/usr/lib/libplist-2.0.la`와 이전 임시 sysroot를
참조했다. 호스트 라이브러리를 추가하는 대신, 공유 전용 libplist/libimobiledevice-glue
패키지에서 `.la` 메타데이터만 제외하도록 수정했다. 공유 객체, 헤더 및 `.pc`는
유지한다. 기존 패키지는 보존하고 libplist 릴리스 3, glue 릴리스 4로 올렸다.
세 패키지를 `/tmp/kiki-mobile-la-clean-vVnZMY03`에서 의존성 순서대로 재빌드했고
전체 빌드가 종료 코드 0으로 완료됐다. libusbmuxd 라이브러리 및 iproxy/inetcat의
필수 ELF RPATH/RUNPATH 부재 검사도 통과했다.
패키지 `libusbmuxd-2.1.1-1.x86_64.ki2`, 37,782바이트,
SHA-256 `cdaef944125210be01316e6cc779f84b0905f4e2eeba5729798f7ee2030c1ed8`.
기존 ISO는 변경하지 않았다. 새 릴리스로 런타임 검사 3개를 다시 실행해 모두
통과했다: libplist의 패치된 upstream 스크립트 41/41, glue의 버전/SHA256/OPACK,
iproxy/inetcat의 도움말/버전 및 대상 로딩 경로와 RPATH 부재 검사.

`tools/test_libusbmuxd_runtime.py`는 KIKI 로더에서 iproxy/inetcat의 도움말·버전,
라이브러리 해석 경로 및 RPATH 부재를 검사하도록 추가했다.
장치 열거, 포트 포워딩, USB 접근은 검사에 포함하지 않는다.

### libimobiledevice-glue 1.3.2 — 릴리스 3 빌드 및 메모리 기능 검사 완료

검증된 GNOME 50.4 메타데이터는 libimobiledevice-glue 1.3.2,
커밋 `aef2bf0f5bfe961ad83d224166462d87b1df2b00`을 지정한다.
[공식 릴리스](https://github.com/libimobiledevice/libimobiledevice-glue/releases/tag/1.3.2)의
소스 아카이브 338,101바이트를 확보했다. SHA-256
`6489a3411b874ecd81c87815d863603f518b264a976319725e0ed59935546774`는
GitHub release asset API의 digest와 일치한다. 별도 PGP 검증을 주장하지 않는다.
소스의 LGPL-2.1-or-later 고지를 확인했고 libplist 의존성의 네이티브 레시피를
개발용 gnome-foundation 프로필에만 추가했다. 기본 서버/ISO는 변경하지 않았다.

첫 릴리스 1 빌드는 성공했지만 ELF에 임시 sysroot `/usr/lib` RPATH가 남았다.
패키지 44,181바이트, 키 `b3eab499baea`, SHA-256
`b522b45dd6e4ade1fdf74945545049dd3d61582623489db2f81a2e303252778c`.
이 산출물을 배포 준비 완료로 취급하지 않는다.
원인은 libtool의 hardcode_libdir_flag_spec 경로 삽입이며, 생성된 libtool에서
해당 설정을 비활성화하는 빌드 단계를 추가했다. 릴리스 1은 보존하고 릴리스 2,
키 `a2ed180ee5bf`, `/tmp/kiki-limd-glue-clean-hmXX4L0O`에서 재빌드했다.
릴리스 2도 정상 빌드됐지만 RPATH에 sysroot와 리터럴 `$LD_RUN_PATH`가 남았다.
libtool의 대체 `runpath_var=LD_RUN_PATH` 경로까지 비활성화한 릴리스 3을 준비했다.
패키지 생성 전에 readelf로 RPATH/RUNPATH가 없음을 검사하고, 남아 있으면 실패한다.
릴리스 3 빌드 경로 `/tmp/kiki-limd-glue-final-X9jdqZTL`, 키 `19f07354f1eb`에서
종료 코드 0으로 빌드 완료했다. 필수 ELF 검사에서 RPATH/RUNPATH가 없음을 확인했다.
패키지 `libimobiledevice-glue-1.3.2-3.x86_64.ki2`, 44,153바이트,
SHA-256 `0c76dcf3f969b12c1026f24ad83751387ff41524060111809d1a2510f44f5b53`.
`tools/test_limd_glue_runtime.py`를 추가하고
`KIKI_TEST_LIMD_GLUE=1 python3 -B tools/test_limd_glue_runtime.py`로 실제 검사했다.
KIKI 패키지와 Linux UAPI 헤더를 임시 rootfs에 풀고 호스트 C 컴파일러로 작은
시험 프로그램을 만든 뒤, KIKI 로더와 라이브러리로 실행했다. 검사 1개 통과:
버전 1.3.2, SHA-256 abc 알려진 값, 문자열/정수 딕셔너리의 OPACK 인코딩·디코딩
왕복 및 메모리 해제. 실제 동적 라이브러리 해석 경로가 임시 KIKI rootfs 내부이며
공유 라이브러리에 RPATH/RUNPATH가 없는 것도 검사했다.
소켓 연결, USB 장치 접근, 페어링, 데스크톱 세션은 실행하지 않았다.
라이브러리의 모든 기능 또는 GNOME 장치 연동 검증을 대신하는 결과는 아니다.

### GCC 런타임 빌드 환경 준비

사용자 승인 후 Rocky-9에 gmp-devel 6.2.0-13.el9,
mpfr-devel 4.1.0-10.el9, libmpc-devel 1.2.1-4.el9 설치를 완료했다.
의존성으로 gmp-c++ 6.2.0-13.el9가 설치됐고 기존 mpfr은
4.1.0-7.el9에서 4.1.0-10.el9로 갱신됐다. dnf 트랜잭션 정상 종료 및
rpm 조회로 설치 결과를 확인했다. 이는 호스트 빌드 의존성 준비이며
KIKI libgcc 런타임 패키지 빌드 또는 C++ 예외 처리 검증 완료가 아니다.
기존 ISO와 VM 디스크는 변경하지 않았다. VM 디스크 초기화 승인과
UPower 정상 소스 확보는 별도 대기 사항이다.

후속 작업으로 `distro/recipes/compiler-runtime.toml`에 GCC 11.5.0 소스에서
KIKI sysroot를 대상으로 `libgcc_s.so.1`을 만드는 레시피를 추가했다.
빌드용 C 컴파일러와 target-libgcc만 빌드하고 배포 패키지에는 공유 런타임과
링커용 심볼릭 링크를 설치한다. libplist의 빌드/실행 의존성에도 libgcc를 명시했다.
첫 빌드 키 `7ae943f68019`, 작업 경로 `/tmp/kiki-libgcc-Dyes2S1j`에서는
C 컴파일러 생성 후 target-libgcc 구성에서 실패했다. 생성된 `gcc/as` 래퍼의
`ORIGINAL_AS_FOR_TARGET`가 비어 `exec: --: invalid option`이 발생했다.
서로 다른 vendor triple 때문에 발견하지 못한 동일 x86_64 ELF binutils를
AS/LD/AR/NM/RANLIB/STRIP/OBJCOPY/OBJDUMP_FOR_TARGET에 명시했다.
두 번째 빌드 키 `04aaa02d478e`, 경로 `/tmp/kiki-libgcc-tools-XHd1RVvy`에서는
대상 도구 경로가 실제 GCC 래퍼에 반영됐고 libgcc 컴파일까지 통과했다.
공유 링크에서 `crti.o` 검색이 실패했다. 파일은 sysroot의 `/usr/lib64`에 있지만
libgcc 공유 링크 규칙이 LDFLAGS_FOR_TARGET 대신 CFLAGS를 사용했다.
CFLAGS에 대상 시작 파일 경로와 relro/now 플래그를 전달한 재링크는 성공했다.
생성 ELF의 SONAME은 `libgcc_s.so.1`, NEEDED는 `libc.so.6`, BIND_NOW가 확인됐고
RPATH/RUNPATH는 없었다. 이 산출물은 진단용이며 패키지 완료가 아니다.

검증한 플래그를 CFLAGS_FOR_TARGET에 반영하고, 새 빌드 키 `28e688163d98`,
경로 `/tmp/kiki-libgcc-final-TVkFX8Pj`에서 처음부터 재현 빌드를 시작했다.
이전 작업 디렉터리와 ISO는 보존했다. 런타임 패키지 및 C++ 예외 처리 검증은
아직 미완료이며 기존 ISO에 포함됐다고 간주하지 않는다.

`tools/test_gcc_runtime.py`는 `KIKI_TEST_GCC_RUNTIME=1`로 선택 실행한다.
패키지들을 임시 rootfs에 풀고 대상 로더의 라이브러리 해석 경로를 확인한 다음,
공유 라이브러리 양방향 C++ 예외 전달과 스택 정리(RAII)를 검사한다.
런타임 패키지 빌드 후 실제 실행 결과를 별도 기록해야 한다.
환경변수 없는 기본 실행은 Linux/Windows에서 1개 skip을 확인했다.
이는 테스트 로드 및 선택 실행 조건 확인이며 C++ 런타임 검사 통과가 아니다.
호스트/VM 디스크 설치나 GNOME 그래픽 세션 검증을 대신하지 않는다.
패키지 빌드 도구 회귀 테스트 21개는 다시 통과했다.

### GCC 런타임 재현 빌드 및 예외 처리 검사 완료

키 `28e688163d98`의 전체 빌드는 종료 코드 0으로 완료됐다.
`dist/ki2/packages/x86_64/libgcc-11.5.0-1.x86_64.ki2`, 189,794바이트,
SHA-256 `e83aa2384afed912e685f8762834815921668ecea3423e7c4594d8c5147937a1`.
KIKI libgcc/libstdcxx/glibc를 임시 rootfs에 풀어 실제 대상 로더로 실행한 C++
양방향 공유 라이브러리 예외 전달 및 RAII 검사 1개가 통과했다.
처음에는 테스트용 Linux UAPI 헤더가 없어 컴파일에 실패했고, KIKI linux-headers
패키지를 테스트 환경에 추가한 재실행에서 통과했다. 라이브러리 해석 경로도
임시 KIKI rootfs 내부임을 확인했다. 호스트 C++ 컴파일러/개발 헤더를 사용하는
런타임 검사이며 전체 자체 C++ 툴체인 구축이나 모든 예외 ABI 검증은 아니다.

### libplist 2.7.0 — 릴리스 2 빌드 및 패치된 upstream 41개 검사 통과

`tools/test_libplist_runtime.py`에 KIKI 패키지 라이브러리로 upstream 스크립트를
실행하는 선택 검사를 추가했다. 모든 시험 바이너리의 로더 해석 경로가 임시
KIKI rootfs 내부임을 확인한다. 스크립트는 호스트 `/bin/sh`와 시간대 데이터를
사용하며 출력은 임시 디렉터리에만 생성한다. 완전한 chroot/OS 세션 검사는 아니다.

처음 원본 스크립트로 실행한 결과는 39/41이었다. JSON/OpenStep 음수 테스트는
잘못된 `-neq` 연산자로 셸 오류를 내면서도 종료 코드 0을 반환했다. 검사기는
이 셸 오류를 실패로 판정했다. 추가로 OpenStep 데이터 노드는 src/oplist.c의
PLIST_DATA 직렬화 구현과 실제 실행에서 지원되는데, 원본 시험은 실패를 기대했다.
`0001-fix-format-test-exit-checks.patch`에서 `-ne`로 수정하고 데이터의 기대값을
성공(0)으로 정정했다. 지원하지 않는 나머지 형식 변환의 기대값 2는 유지했다.
`openstepn` 철자도 `openstep`으로 정리했다. 라이브러리 구현을 테스트에 맞춰
축소하거나 C++ 기능을 제거하지 않았다.

릴리스 2 빌드 키 `9780f6c45d29`, 경로 `/tmp/kiki-libplist-tests-PSHu47js`.
빌드 종료 코드 0, 실제 패치된 upstream 스크립트 41/41 통과.
패키지 `dist/ki2/packages/x86_64/libplist-2.7.0-2.x86_64.ki2`, 111,384바이트,
SHA-256 `f7d2b2674788bd18f33ca0ee2968743b4012082bd6044104409778115a31ec8a`.
기존 릴리스 1은 보존했다. 완성된 installed-brand ISO는 변경하지 않았으며
libgcc/libplist 신규 패키지와 GNOME 데스크톱은 해당 ISO에 미포함이다.

재현 명령:
```sh
KIKI_LIBPLIST_TEST_SOURCE=/tmp/kiki-libplist-tests-PSHu47js/x86_64/work/libplist/source/libplist-2.7.0 \
  python3 -B tools/test_libplist_runtime.py
```

#### 릴리스 1 빌드 기록

libgcc 의존성과 `-shared-libgcc`를 사용한 후속 빌드가 정상 완료됐다.
키 `fe6728793669`, 경로 `/tmp/kiki-libplist-runtime-vV3qfMrs`.
`dist/ki2/packages/x86_64/libplist-2.7.0-1.x86_64.ki2`, 111,355바이트,
SHA-256 `a08edeb7003cdcf9c2ff480e0ed47c54163e3e3fb8622bddf68882f9c945a4a4`.
upstream 테스트 실행과 libplist 자체의 런타임 기능 검증은 아직 남아 있다.
libgcc/libplist는 installed-brand ISO의 고정 패키지 스냅샷에 포함되지 않는다.

#### 이전 실패 및 소스 기록

GNOME 50.4 메타데이터는 libplist 2.7.0을 지정한다. 공식 GitHub release의
`libplist-2.7.0.tar.bz2`를 확보했고 로컬 SHA-256은
`7ac42301e896b1ebe3c654634780c82baa7cb70df8554e683ff89f7c2643eb8b`이다.
해당 release API에 digest가 없어 별도 게시 해시/서명과 대조했다고 주장하지 않는다.

C/C++ 라이브러리, plistutil, upstream 테스트를 유지한 레시피를 추가했다.
Cython 제외는 GNOME 메타데이터와 동일하다. 기존 KIKI libstdcxx 11.5.0-2와
전체 sysroot를 사용했으나 C++ 테스트 링크에서 실패했다.
`libplist++-2.0.so`의 `libgcc_s.so.1` 의존성을 찾지 못했고
`_Unwind_Resume@GCC_3.0` 미해결 참조가 발생했다. LDFLAGS의 `-static-libgcc`만으로
해결되지 않았다. KIKI용 GCC 예외 처리 런타임과 라이브러리 경계를 보완해야 한다.
호스트 런타임 복사나 C++ 기능 제거는 하지 않았다.

실패 빌드 경로 `/tmp/kiki-libplist-3s2O1Cfe`, 키 `044ffe9a3c75`.
새 libplist 패키지 생성 및 upstream 테스트 실행은 미완료다.
개발용 gnome-foundation 프로필에만 추가했으며 기존 ISO는 변경하지 않았다.

### 보조 스크립트 변경과 빌드 캐시

URL 소스 레시피의 셸 명령 문자열이 같으면 외부 래퍼 파일 변경만으로는 캐시 키가
바뀌지 않는 문제를 테스트로 재현했다. `build.inputs`에 명시한 파일의 SHA-256을
캐시 키에 반영하도록 빌드 도구를 수정했다. 파일이 없으면 빌드를 거부한다.
새 필드는 명시적 입력 목록이며 셸 명령이나 스크립트의 의존성을 자동 분석하지 않는다.
사용한 보조 파일과 그 전이 의존성은 레시피 작성자가 함께 선언해야 한다.

gsettings-desktop-schemas, json-glib, libgudev에 Python/GIR/pkg-config/대상 로더
래퍼를 실제 사용 범위에 맞춰 등록했다. 보조 파일 내용 변경 시 키 변경,
무관한 파일 변경 시 키 유지, 입력 누락 시 실패를 검사했다.
Linux 빌드 도구 테스트 21개 통과. 처음 Windows 전체 실행에서는 새 테스트의
예상 실패 외에 기존 소스 빌드 테스트 2개 오류와 1개 skip이 있었으므로,
Windows 전체 통과로 간주하지 않는다.

실제 libgudev dry-run 키는 `614c28a0b6dc`로 이전 `2867e375b2a8`과 다르다.
dry-run은 재빌드 계획 확인이며 새 패키지 생성 결과가 아니다.
이번 캐시 수정 이후 GNOME 패키지를 다시 빌드하거나 기존 current ISO를 갱신하지 않았다.

### UPower 소스 확보 대기

GNOME 50.4 메타데이터는 UPower v1.91.3, 커밋
`3dc5323bf9f8f84b0a038f5f36c34d49e480ee3c`를 지정한다.
2026-09-08 공식 GitLab 태그 아카이브 다운로드는 HTTP 응답에 봇 확인용 HTML
(7,506바이트)을 반환했고 tar 형식 검사에 실패했다. 이를 소스 해시로 고정하거나
빌드 입력으로 사용하지 않았다. 응답은 `dist/sources/upower-v1.91.3-download-challenge.html`로
이름을 바꿔 보존했다. 브라우저 확인을 거쳐 받은 정상 아카이브가 필요하다.
봇 확인 절차 우회는 수행하지 않았다. UPower 레시피 구현/빌드는 미완료다.

### libusb 1.0.29 — UPower 의존성

GNOME 50.4 메타데이터의 UPower가 libusb를 요구함을 확인했다.
[공식 libusb 배포](https://github.com/libusb/libusb/releases/tag/v1.0.29)의
tar.bz2를 GitHub release asset SHA-256과 대조했다. PGP 서명 검증은 미수행이다.
이는 GNOME의 freedesktop-sdk junction 버전과 별도로 고정한 입력이다.

KIKI 전체 sysroot와 libudev를 사용해 libusb 1.0.29-1 패키지 빌드 완료.
빌드 키 `a44829ef9f40`, 크기 83,237바이트, 패키지 SHA-256:
`548fb1f7b238c570438daed6bef357863683540e2ca35b427f9253c70c271bb8`.
udev/shared library 지원을 켰다. ELF RPATH/RUNPATH는 없다.
91개 레시피 및 GNOME 기반 프로필 참조 검증 통과.

`/tmp/kiki-libusb-Z3pFqt1B` 빌드의 upstream `tests/init_context -v`를
KIKI 로더와 설치 대상 libusb 경로로 실행해 초기화/로그 수준/로그 콜백 3개 통과.
USB 전송·장치 설정 변경은 수행하지 않았다. stress/set_option은 빌드만 했으며
umockdev 테스트는 의존성이 없어 미구성이다. UPower 통합은 미완료다.
이번 패키지는 기존 current ISO와 이전 4개 기반 패키지 통합 rootfs에는 미포함이다.

### 이전 기반 패키지

- UPower/GNOME Desktop 공통 의존성 libgudev 238 레시피 추가 및 90개 레시피 검증 통과.
  [공식 소스 체크섬](https://download.gnome.org/sources/libgudev/238/libgudev-238.sha256sum)과
  일치 확인. GLib 2.84.4 및 libudev 255 의존성 탐지는 성공했다.
  초기 GIR 링크의 GLIBC 버전 충돌 및 후속 호스트 컴파일러 환경 문제를 해결했다.
  full sysroot/대상 로더 및 GIR 경로 변수 분리 후 패키지 생성과 통합 런타임 검사를
  통과했다. 아래 후속 검증 절에 실패 이력과 성공 근거를 구분해 기록했다.
  introspection을 끄거나 호스트 libudev를 KIKI 라이브러리로 대체하지 않았다.
  umockdev 미구성으로 upstream 장치 테스트도 미실행이다.

- GNOME Session/Mutter 공통 의존성 JSON-GLib 1.10.8 네이티브 레시피 추가.
  공식 메타데이터 해시 일치 및 GLib >= 2.72 요구 확인(KIKI는 2.84.4).
  GIR/typelib과 upstream 단위 테스트 빌드는 켜고 문서·설치형 테스트·별도 conformance
  테스트는 제외했다. 최초 GIR 빌드의 호스트 pkg-config 환경 충돌을 기존 래퍼로
  수정했다. JSON-GLib 1.10.8-1 패키지 빌드 완료 및 라이브러리/GIR/typelib 포함 확인.
  빌드 디렉터리에서 KIKI 라이브러리 경로로 upstream 단위 테스트 14개 통과.
  별도 conformance 테스트와 설치된 GNOME 소비자의 통합 시험은 미실행이다.

- 다음 패키지 `gsettings-desktop-schemas` 50.1 소스 확보 및 공식 메타데이터 해시
  일치 확인. 원본 Meson 설정과 스키마/헤더 빌드를 검토했다.
  GLib 도구와 GObject Introspection을 사용하며 GDesktopEnums GIR/typelib 생성이
  필요하다. 네이티브 레시피를 `gnome.toml`에 추가하고 개발 검증 프로필에 연결했다.
  레시피 검증은 통과했으나 최초 빌드는 스캐너의 호스트 Python 선택으로
  `giscanner`를 찾지 못해 실패했다. KIKI Python 래퍼를 사용하도록 수정했다.
  이어서 typelib 컴파일러의 호스트 GLib 심볼 충돌을 빌드 전용 래퍼로 해결했다.
  50.1-1 패키지 빌드 완료(1,897,794바이트). GIR/typelib과 스키마 XML 포함 확인.
  DESTDIR 설치는 upstream 스키마 캐시 생성을 생략하므로 `gschemas.compiled`는
  패키지에 없다. guided 설치 백엔드에 전체 패키지 설치 후 대상 chroot에서
  `glib-compile-schemas --strict`를 실행하도록 연결했으며 실패하면 설치 실패로 처리한다.
  ISO 도구 회귀 테스트 30개 통과. 이 변경은 io-units ISO 생성 이후이며 해당 ISO에 없다.
  별도 rootfs 조립에도 KIKI 로더/GLib으로 전체 스키마 캐시를 생성하도록 연결했다.
  실패하면 설치 상태 기록 전에 중단하며 스키마가 없는 서버 rootfs는 건너뛴다.
  현재 지원은 Linux x86_64 빌더이며 다른 환경에서는 스키마가 있을 때 오류로 안내한다.
  패키지 설치/갱신/삭제는 스키마 XML/override 변경 시 `glib-compile-schemas` 후처리를
  등록한다. 기존 후처리 모델에 따라 설치 시스템 안에서 운영자가
  `ki2ctl hooks apply`를 실행해야 하며 자동 실행으로 바꾸지는 않았다.
  실패는 failed 상태와 오류를 남기고 비정상 종료하며, 재시도가 가능하다.
  이미 적용된 후처리도 다음 패키지 변경에서 다시 등록된다.
  실제 설치 시스템에서의 패키지 갱신 및 GNOME 로그인은 미완료다.

- `distro/recipes/gnome.toml`에 dconf 0.49.0 네이티브 레시피 추가.
  공식 소스를 GNOME 메타데이터에 고정된 SHA-256과 대조했다.
- 원본 `meson.build`의 GLib 최소 요구는 2.67.4이며 현재 KIKI GLib은 2.84.4다.
  버전 조건 충족은 런타임 호환 검증을 대체하지 않는다.
- 개발 검증용 `gnome-foundation` 프로필은 dconf, gsettings-desktop-schemas, json-glib,
  libgudev를 포함한다. libgudev 빌드 완료 전에는 확장된 프로필 전체 조립이 불가능하다.
  Vala 바인딩·문서·bash completion은 이번 C/GIO 기반 패키지에서 제외한다.
- 레시피/프로필 검증과 dconf 0.49.0-1 패키지 빌드 완료.
- `KIKI_TEST_DCONF_RUNTIME=1 python3 -B tools/test_dconf_runtime.py` 통과:
  실제 KIKI 패키지를 임시 경로에 풀고 별도 D-Bus 세션에서 GSettings로 42를 저장한 뒤
  독립 dconf/GSettings 클라이언트로 재조회하고 설정 파일 생성을 확인했다.
  사용자 HOME/설정/런타임 버스 대신 테스트 전용 디렉터리를 사용했다.
- 2026-09-08 확장 테스트 2개 통과(27.282초): 서비스 직접 시작과 별도 D-Bus의
  자동 활성화를 각각 확인했다. 후자는 패키지 서비스 파일의 Exec만 임시 경로와
  KIKI 로더에 맞게 치환한다. 호스트 서비스/설정 파일은 변경하지 않는다.
  설치된 절대 경로의 실행, systemd 사용자 관리자 활성화, GNOME 로그인/로그아웃,
  ISO 부팅을 검증한 결과는 아니다. 첫 실행은 WSL 연결 오류였으며 재실행에서 통과했다.
- upstream 빌드가 호스트 `dbus-daemon` 부재로 일부 자체 테스트를 생략했으며
  쓰기 반환값 미검사 경고도 출력했다. 이를 전체 upstream 테스트 통과로 간주하지 않는다.
- `desktop-gnome` 설치 선택지는 아직 노출하지 않았으며 서버 기본 패키지는 변경하지 않았다.

## GNOME 설정 런타임 검증

`KIKI_TEST_DCONF_RUNTIME=1 python3 -B tools/test_dconf_runtime.py` 3개 통과(31.818초).
실제 KIKI 패키지의 GNOME XML/enum 스키마와 테스트 스키마를 임시 경로에서 함께
컴파일하고, 별도 D-Bus 자동 활성화와 GSettings/dconf로 `color-scheme` 저장·조회·초기화를
확인했다. 호스트 설정과 세션 버스는 사용하지 않았다.

upstream의 `/system/` 경로 사용 중단 예정 경고가 출력됐으나 컴파일은 성공했다.
typelib 파일 포함만 확인했으며 GJS에서 enum 로딩, GNOME 화면, ISO 설치를 검증한 것은 아니다.

## 실제 기반 rootfs 조립 확인

2026-09-08 `gnome-foundation` 프로필을 새 임시 rootfs
`/tmp/kiki-gnome-rootfs-check-rlv3k_2w/rootfs`에 조립 완료했다.
패키지 추출 후 통합 캐시 생성과 `var/lib/ki2/installed.json` 기록까지 실행됐으며
`gschemas.compiled` 크기는 41,260바이트다. 기존 rootfs/ISO는 변경하지 않았다.

조립된 KIKI Python 3.12와 libgirepository를 KIKI 로더/라이브러리 경로로 실행해
GDesktopEnums 3.0 typelib 및 ColorScheme enum의 값 3개 로딩을 확인했다.
따라서 typelib은 포함 여부뿐 아니라 GI 런타임 로딩도 확인한 상태다.
GJS 소비자, GNOME Shell/Mutter/GDM 세션과 실제 VM 부팅 검증은 여전히 미완료다.

프로젝트 Go 회귀 검사 `go test -mod=vendor ./cmd/... ./internal/... ./deploy/... ./installer/...`
통과. 이 결과는 GNOME 데스크톱 작동이나 ISO 설치 완료의 증거가 아니다.

후속 검증: rootfs 캐시 생성 함수를 실제 패키지 런타임 테스트에 연결해 3개 재통과
(31.821초). 빌드 도구 테스트 20개 통과: 스키마 없음, 필수 도구 누락, 미지원 아키텍처,
컴파일 실패 전파 및 호출 인자 확인 포함. 호스트 GLib 대신 KIKI 로더/라이브러리를
지정하고 LD_PRELOAD 등 호스트 환경변수를 전달하지 않는다.
이 후속 코드 변경은 이미 생성한 io-units ISO에는 미포함이다.

ki2ctl 후처리 상태 테스트 3개와 패키지 관리자 회귀 테스트 13개 통과.
명령 실패/도구 누락/오프라인 보류/재등록/재시도는 모의 실행이며,
임시 저장소 패키지 설치에서는 스키마 후처리 등록을 확인했다.
Windows 첫 전체 실행은 OpenSSL 경로 누락으로 1개 실패했으며 설치된 Git OpenSSL
경로를 지정한 재실행에서 모두 통과했다. 호스트의 실제 후처리 명령은 실행하지 않았다.

## libgudev 전체 sysroot 재검증

2026-09-08 libgudev 238 빌드 키 `2867e375b2a8`을 재검증했다.
KIKI 전체 sysroot와 대상 로더를 사용한 구성 및 공유 라이브러리 링크는 통과했다.
그러나 GIR 생성용 임시 프로그램을 링크하는 호스트 `cc`가 `SIGFPE`로 종료되어
전체 빌드는 실패했다. 이전 GLIBC 버전 오류와 다른 실패이며, 호스트 컴파일러와
GIR 도구의 라이브러리 환경 분리를 추가 점검해야 한다. 원인은 아직 확정하지 않았다.
libgudev 패키지 완성, GNOME 데스크톱 준비 완료 또는 새 ISO 검증으로 간주하지 않는다.

### 후속 수정 및 성공 결과

GIR 스캐너의 `get_internal_link_flags`가 호스트 컴파일러 실행 전에
`LD_LIBRARY_PATH`에 대상 라이브러리 경로를 추가하는 것을 확인했다.
대상 로더 모드에서는 `--lib-dirs-envvar=KI2_SYSROOT_LIBRARY_PATH`를 전달해
호스트 환경과 대상 실행 경로를 분리했다. 기본 모드는 변경하지 않았다.

수정 후 libgudev 전체 빌드가 종료 코드 0으로 완료됐다. 생성 패키지는
`dist/ki2/packages/x86_64/libgudev-238-1.x86_64.ki2`(71,302바이트)이며,
공유 라이브러리와 GUdev-1.0 GIR/typelib 설치를 빌드 출력에서 확인했다.
실제 대상 로더·Python·glibc 2.39 환경에서 libgudev를 로딩하고
`g_udev_client_new(NULL)` 생성 및 `g_object_unref` 해제도 통과했다.
장치 설정이나 디스크 쓰기는 수행하지 않았다.

`tools/test_target_launchers.py` 2개 통과: 모의 로더에서 환경변수 제거와
GIR 인자 전달을 확인하고, 대상 로더 누락 시 126 반환을 확인했다.
umockdev 기반 upstream 테스트는 비활성화 상태이며 통과로 주장하지 않는다.
GNOME Shell/Mutter/GDM 전체 구성, 실제 GUI 세션 및 ISO 검증은 미완료다.

### 기반 패키지 통합 런타임 검사

2026-09-08 dconf, gsettings-desktop-schemas, json-glib, libgudev와 의존성을
`/tmp/kiki-gnome-union-rP7mCvnw/rootfs`에 새로 조립했다. 통합 스키마 캐시 생성과
rootfs 조립은 정상 종료했다. upstream `/system/` 스키마 경로의 사용 중단 예정
경고가 출력됐으며 오류로 종료되지는 않았다.

재현 명령:
```sh
KIKI_GNOME_TEST_ROOTFS=/tmp/kiki-gnome-union-rP7mCvnw/rootfs \
  python3 -B tools/test_gnome_foundation_runtime.py
```

실제 KIKI Python/로더/glibc 2.39에서 통합 테스트 1개 통과:
GDesktopEnums 3.0, Json 1.0, GUdev 1.0 typelib 로딩, JSON 구문 분석,
GUdev 클라이언트 생성/해제 및 dconf 라이브러리 로딩을 확인했다.
호스트 세션 버스/설정 변경, 장치 쓰기, 마운트 또는 디스크 설치는 수행하지 않았다.
GJS, GNOME Shell/Mutter/GDM 및 실제 화면 시험을 대신하는 결과는 아니다.
