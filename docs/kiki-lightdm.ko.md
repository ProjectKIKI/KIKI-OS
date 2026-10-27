# 선택형 LightDM 로그인

기존 r17 ISO의 인스톨러는 Cage/Wayland를 유지한다. 이 패키지는 설치된 KIKI OS에
추가할 X11 로그인 경로이며, 기본 부팅 대상을 자동 변경하지 않는다.

## 구성

- `kiki-lightdm` 1.30.0-1: LightDM 1.30.0, GTK3 greeter 2.0.8,
  AccountsService, GTK3 런타임을 Rocky Linux 9 호스트 ABI로 부트스트랩한다.
- 기존 `kiki-x11-runtime`에 의존한다. Xorg, xterm, xauth 등을 중복하지 않는다.
- 기존 네이티브 `linux-pam`에 의존하며, 호스트 PAM 라이브러리/모듈을 묶지 않는다.
- `lightdm` 서비스, `lightdm` 시스템 계정, PAM 파일, greeter, 최소 xterm 세션,
  켜기 명령 `kiki-lightdm-enable`을 제공한다.
- 게스트 로그인, 자동 로그인, X 서버 TCP 수신을 끈다.
- 기본 세션은 `KIKI OS X11 Terminal`이다. 데스크톱 환경은 포함하지 않는다.

## 재빌드

Rocky 9 빌드 환경에 EPEL의 `lightdm`, `lightdm-gtk`, `lightdm-gobject`,
`accountsservice`가 필요하다. r17 ISO에 들어 있는 그래픽 release 15 패키지와
`kiki-x11-runtime`의 rootfs를 같은 버전으로 준비한다. 서로 다른 그래픽 버전은
`ki2lightdm.py`가 거부한다.

~~~sh
python3 tools/ki2lightdm.py \
  --base-rootfs build/ki2/host-lightdm/r17-base/rootfs \
  --x11-rootfs build/ki2/host-x11/rootfs \
  --output build/ki2/host-lightdm/rootfs
python3 tools/ki2build.py build --profile distro/profiles/lightdm.toml \
  --only kiki-lightdm --packages-dir dist/ki2/lightdm-packages
KIKI_TEST_LIGHTDM_PACKAGE=1 PYTHONPATH=tools python3 -m unittest test_lightdm_runtime
~~~

`--output`은 존재하지 않는 디렉터리여야 한다. 빌드 결과는
`dist/ki2/lightdm-packages/x86_64/kiki-lightdm-1.30.0-1.x86_64.ki2`이다.

## 서명 저장소와 설치

`dist/ki2/lightdm-repo/`에 r17 추가 패키지 전용 저장소가 있다. 여기에는
`kiki-lightdm`, `kiki-x11-runtime`, `linux-pam` 세 패키지와 Ed25519 서명된
`repo/metadata.x86_64.json`, `repo/index.x86_64.json`, `repo/channels.json`이 있다.
서명은 r17 ISO의 Stage 3 저장소와 같은 키로 검증된다. 개인키는 저장소에
포함하지 않는다. 기존 r17 기반 패키지(`glibc`, `systemd`, `dbus`, `shadow`,
`libxcrypt`, `kiki-installer-gtk` 등)는 설치된 시스템에 있어야 한다.
기반 패키지까지 한 저장소에서 조회하려면 116개 최신 패키지를 담은
`dist/ki2/signed-all/`을 사용한다. 전체 저장소 구성은
`docs/kiki-signed-current-repo.ko.md`에 기록한다.
이 추가 저장소는 기존 ISO나 기본 저장소를 덮어쓰지 않으며 아직 네트워크에
호스팅하지 않았다. 전체 디렉터리를 신뢰할 수 있는 방법으로 KIKI OS의
`/srv/kiki-lightdm`에 복사한 뒤, 설치된 시스템에서 다음과 같이 사용한다.

~~~sh
sudo ki2ctl --repo file:///srv/kiki-lightdm update
sudo ki2ctl --repo file:///srv/kiki-lightdm install kiki-lightdm --dry-run
sudo ki2ctl --repo file:///srv/kiki-lightdm install kiki-lightdm
~~~

서명 검증을 생략하는 옵션은 사용하지 않는다. 설치 전 dry-run에서 기존 r17
기반 패키지가 누락됐다고 나오면 먼저 해당 패키지를 신뢰된 r17 저장소에서
설치한다. 저장소 서명과 패키지 해시만 검증한 상태이며, 실제 KIKI OS 대상
설치는 별도로 시험해야 한다.

## 설치 후 활성화

설치된 시스템에서 로컬 콘솔을 유지한 상태로 다음 명령을 명시적으로 실행한다.

~~~sh
sudo kiki-lightdm-enable
sudo systemctl set-default graphical.target
sudo reboot
~~~

`kiki-lightdm-enable`은 필수 파일을 확인하고 계정/런타임 디렉터리를 준비한 뒤
LightDM만 활성화한다. 다른 디스플레이 매니저가 이미 선택되어 있으면 멈춘다.
기본 대상 전환과 재부팅은 운영자가 따로 선택한다. 문제가 생기면 로컬 tty에서
`sudo systemctl set-default multi-user.target`으로 텍스트 부팅을 복구한다.

## 검증 한계

패키지 빌드, 그래픽/X11 중복 파일 검사, 설정 파싱, PAM/서비스/세션 파일 정적
검사는 수행했다. 실제 Hyper-V VT 전환, LightDM greeter 표시와 사용자 로그인을
아직 검증하지 않았다. 이 패키지를 검증 전 기본 ISO에 포함하지 않는다.
