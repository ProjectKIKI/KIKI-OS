# KIKI OS 설치 프런트엔드

KIKI OS 설치기는 하나의 `kiki-install-plan-v1` 계약을 GTK GUI, 전체 화면 TUI,
안전 CLI와
무인 설치가 함께 사용한다. 프로필별 패키지와 서비스 계산은
`kiki-installer-tui`가 담당하고 GTK 앱은 이 실행 파일을 호출해 같은 YAML을
생성한다.

전체 설치 실행 구조, 디스크 작업과 빌드·검증 절차는
[KIKI OS 인스톨러 구성 및 동작](kiki-installer.ko.md)에 정리되어 있다.

패키지 역할은 `/usr/share/ki2/package-groups.json`의 공통 그룹 카탈로그를
사용한다. GTK의 **추가 그룹(쉼표)** 입력란, TUI의
`group add|remove <그룹>` 명령과 무인 설치의 `--groups` 옵션은 모두
InstallPlan의 `packages.groups` 및 해석된 `packages.selected`에 기록된다.

## 메뉴 구성

| 순서 | 메뉴 | 주요 설정 |
| --- | --- | --- |
| 1 | 언어 및 지역 | 로케일, 콘솔 키맵, 시간대 |
| 2 | 디스크 | 전체 디스크, 자동 파티셔닝, swap 정책 |
| 3 | 네트워크 | DHCP, 고정 주소, 네트워크 끄기 |
| 4 | 계정 | 관리자 이름과 호스트명 |
| 5 | 패키지 소스 | 로컬 미디어, 원격 저장소, 미러와 검증 키 |
| 6 | 프로필 | 일반 서버·Kubernetes 역할과 추가 패키지 그룹 |
| 7 | 런타임 | 프로필 기본값, CRI-O, containerd |
| 8 | AI | 로컬 llama.cpp, 원격 호환 API, 끄기 |
| 9 | 검토 | 차단 항목과 파괴적 디스크 작업 확인 |
| 10 | 저장/설치 | InstallPlan 저장 후 Stage-1 실행기로 전달 |

디스크 암호화와 Secure Boot는 실제 포맷·키 등록 백엔드가 준비되기 전까지
메뉴에 표시하지 않는다. 선택지만 존재하고 실제로 적용되지 않는 상태를 피하기
위한 결정이다.

## CLI 및 무인 계획 생성

```sh
go build -o build/kiki-installer-tui ./cmd/kiki-installer-tui

build/kiki-installer-tui --write \
  --mode unattended \
  --plan ./install-plan.yaml \
  --profile server-core \
  --groups development \
  --disk /dev/sda \
  --locale ko_KR.UTF-8 --keymap kr --timezone Asia/Seoul \
  --network dhcp \
  --source local --source-location /run/install-media \
  --ai local
```

원격 저장소는 HTTP(S) URL과 검증 키가 모두 있어야 계획 검사를 통과한다.

```sh
build/kiki-installer-tui --write \
  --source remote \
  --source-location https://repo.example/kiki \
  --verify-key /etc/ki2/trust/repository.pub
```

ISO의 Stage-1 무인 설치는 기존 커널 인자
`kiki.autoinstall=erase|quick-vm`과 `kiki.profile`, `kiki.runtime`,
`kiki.target`, `kiki.hostname`, `kiki.locale`, `kiki.keymap`,
`kiki.timezone`, `kiki.ai`, `kiki.ai-endpoint`를 사용한다. 이 경로는 명시된
경우에만 콘솔의
파괴적 확인을 생략한다.

## GTK 4 실행

```sh
make -C cmd/kiki-installer-gtk
KIKI_INSTALLER_TUI="$(pwd)/build/kiki-installer-tui" \
KIKI_INSTALLER_CSS="$(pwd)/cmd/kiki-installer-gtk/style.css" \
  ./cmd/kiki-installer-gtk/kiki-installer-gtk
```

GTK는 웹 CSS를 직접 실행하는 것이 아니라 GTK CSS의 색상, 여백, 테두리,
상태 클래스 등을 사용한다. GTK 앱은 계획 작성·검토·저장과 `설치 시작` 동작을
제공한다. 시작 요청은 `/run/kiki/gui-install.request`를 통해 ISO Stage-1
실행기로 전달되며, 실제 파티션 포맷과 패키지 추출은 Stage-1이 수행한다.
관리자 암호와 암호 확인은 GTK 계정 화면에서 받고, 검토 화면에서
`INSTALL /dev/...` 형식의 파괴적 확인 문자열을 입력한다. 암호는 YAML이나 영구
디스크에 기록하지 않으며 mode 0600인 `/run` tmpfs 요청 파일로 전달한 뒤
Stage-1이 읽자마자 파일 내용을 제거한다.

Stage 3의 `server-core` 프로필은 `installer-gui` 그룹을 통해
`kiki-installer-gtk` 패키지를 포함한다. 이 패키지는 GTK 4 앱, Cage Wayland
키오스크, wlroots DRM/libinput 백엔드, Noto Sans CJK 한글 폰트와 필요한 동적
라이브러리를 설치 initramfs에 함께 넣는다. PID 1에서 logind 없이 DRM 장치를
열 수 있도록 내장 seatd 백엔드를 활성화한 libseat 0.9.3을 사용하며, libinput의
입력 장치 태깅을 위해 udevd를 GUI 시작 전에 실행한다.

그래픽 런타임은 다음 명령으로 단독 점검·생성할 수 있다.

```sh
python3 tools/ki2graphics.py doctor
python3 tools/ki2graphics.py prepare --jobs 4
python3 tools/ki2build.py build \
  --profile distro/profiles/server-core.toml \
  --only kiki-installer-gtk
```

`stage3-server-core.yaml` 빌드 계획은 패키지 검증보다 먼저 `prepare`를 자동
실행한다. Cage, wlroots, seatd 소스 버전 및 SHA-256은 도구에 고정되어 있으며,
결과에는 `/usr/share/kiki-installer-gtk/runtime-manifest.json`이 기록된다.
현재 이 그래픽 스택은 Stage 3 부트스트랩 경계로서 빌드 호스트 ABI를 묶는다.
장기적으로는 GTK/Wayland/Mesa를 KIKI 네이티브 레시피로 분리한다.

## 부트로더 및 폴백 순서

설치 ISO의 GRUB 기본값은 0번 `KIKI OS graphical installer (default)`이다.
이 항목은 커널에 `kiki.ui=gui`를 전달한다. initramfs에 `cage`,
`kiki-installer-gtk`, `kiki-installer-tui`와 GTK 4 런타임이 모두 있으면 cage
Wayland 키오스크 세션에서 GTK 설치기를 시작한다. 구성요소가 없거나 GUI 창을
설치 요청 없이 닫으면 `kiki-installer-tui --fullscreen --ascii`로 자동 전환한다.
`설치 시작`을 누르면 GUI에서 암호와 디스크 삭제 명령까지 확인하고 저장한
선택값을 Stage-1 실행기로 넘긴다. GTK/Cage는 계속 실행되며
`/run/kiki/install-progress.state`의 단계와 진행률을 한국어 화면에 표시한다.
패키지 설치 구간에는 완료 개수/전체 개수와 현재 패키지 이름도 함께 표시한다.
설치가 끝나면 `확인 후 재부팅` 버튼이 나타나고, 사용자가 누른 경우에만
`/run/kiki/gui-reboot.request`를 통해 Stage-1이 재부팅한다. Linux
커널 VT는 한글 글리프를 직접 렌더링하지 못하므로 폴백 TUI만 ASCII 안전 모드를
사용하고, GTK 화면에서는 Noto Sans CJK로 한국어를 표시한다. GUI 시작 실패의
원문은 `/run/kiki/gui-installer.log`에 남고 폴백 전에 화면에도 출력된다.
Hyper-V 2세대의 `hyperv_drm`처럼 가속 렌더 노드 없이 KMS 출력만 제공하는
가상 GPU에서는 wlroots의 CPU 기반 Pixman 렌더러와 DRM dumb buffer를 사용한다.
GLES2/GBM 세션은 프로세스가 종료되지 않으면서 펌웨어 콘솔을 GTK 화면으로
교체하지 못할 수 있으므로 설치기 기본값으로 강제하지 않는다. Xorg는 이 경로에
필요하지 않으며 ISO 그래픽 설치기는 Wayland/DRM을 직접 사용한다.
커널에서는 같은 합성 비디오 VMBus 장치를 선점하는 `CONFIG_FB_HYPERV`를 끄고
`CONFIG_DRM_HYPERV`와 DRM fbdev 에뮬레이션만 사용한다. 이 구성이 콘솔 출력을
유지하면서 Cage에 `/dev/dri/card0`을 제공한다.

GRUB의 1번 `KIKI OS full-screen TUI installer (...)`는 `kiki.ui=tui`를
전달해 그래픽 초기화를 건너뛴다. 방향키 또는 j/k로 이동하고 Enter로 항목을
선택하며, `:` 키로 기존 설정 명령을 입력한다. TUI에서 c 또는 q를 누르거나
TUI가 실행되지 않으면 번호 입력식 Stage-1 CLI로 전환한다.

GRUB의 2번 `KIKI OS CLI installer (..., safe fallback)`은 `kiki.ui=cli`를
전달해 GUI와 TUI를 모두 건너뛴다. 직렬 콘솔과 BIOS VGA text 항목도 이 CLI를
강제하므로 터미널 제어 시퀀스를 지원하지 않는 장비에서 사용할 수 있다.

따라서 기본 부팅 경로는 `GTK GUI → 전체 화면 TUI → Stage-1 CLI`이다.
Stage 3 서버 빌드는 GUI 런타임을 기본 포함한다. 다른 프로필에서 GTK 4·Cage
패키지가 없는 경우에는 첫 단계를 감지해 건너뛰고 전체 화면 TUI부터 표시한다.

## Hyper-V 그래픽 오류 진단

다음 로그는 Xorg 오류가 아니라 Cage/wlroots가 사용할 DRM 장치를 찾지 못했다는
뜻이다.

```text
Found 0 GPUs, cannot create backend
failed to add backend 'drm'
Unable to create the wlroots backend
```

Hyper-V 2세대에서는 먼저 Secure Boot를 끄고, ISO의 부팅 커널 설정을 확인한다.

```text
CONFIG_DRM_HYPERV=y
CONFIG_DRM_FBDEV_EMULATION=y
# CONFIG_FB_HYPERV is not set
```

`CONFIG_FB_HYPERV=y`가 함께 설정되어 있으면 `hyperv_fb`가 합성 비디오 VMBus
장치를 먼저 점유할 수 있으므로 잘못된 구성이다. 정상 부팅 후에는
`/dev/dri/card0`이 생성되어야 한다. GUI 시작 과정의 전체 로그는
`/run/kiki/gui-installer.log`에서 확인한다.

오류 로그 없이 화면이 `Starting GTK installer with the cage Wayland compositor.`에
머문다면 Cage는 실행됐지만 GLES2/GBM 렌더링 결과가 `hyperv_drm` 출력에 표시되지
않은 상태일 수 있다. 설치 initramfs는 이를 피하기 위해
`WLR_RENDERER=pixman`을 사용한다.

`Failed to allocate shm file for keymap` 뒤에 상태 139로 종료되면 `/dev/shm`이
준비되지 않은 것이다. 설치 initramfs는 systemd의 `dev-shm.mount`가 실행되기 전
환경이므로 `/dev`에 devtmpfs를 마운트한 다음 `/dev/shm`에 mode 1777 tmpfs를 직접
마운트한다. 기본 서비스 목록의 `tmpfs on /dev/shm`이 `[ OK ]`인지 확인한다.
`failed to find data files` 또는 `Failed to load the device quirks`가 나타나지 않도록
GTK 설치기 패키지는 `/usr/share/libinput`과 `/etc/libinput` 데이터도 포함한다.

설치 ISO 생성기는 서명된 패키지 저장소의 최신 `linux-*.ki2`를 조립된 rootfs의
커널보다 우선한다. 따라서 저장소만 갱신한 설치기 재빌드에서도 ISO가 저장소보다
오래된 커널로 부팅하지 않는다. 특정 커널을 의도적으로 시험할 때만
`tools/ki2bootiso.py --kernel <경로>`를 사용한다.

2026-08-27 커널 수정 검증 산출물은 다음과 같다.

```text
dist/iso/kiki-stage3-v3-installer-x86_64-20260827-rev25-hyperv-drm-fix.iso
SHA-256: db2eea8a1ed77ecb5ed2c20c518d230ba33f82c5b1d9a931131001d2178e05da
```

이 ISO는 BIOS/UEFI 부팅 항목, GUI 기본값, GUI → TUI → CLI 구성, 최신
`linux-6.9.9-3` 패키지와 ISO 부팅 커널의 동일 해시를 정적 검증했다. 그러나
2026-08-29 실제 Hyper-V 부팅에서 GLES2 Cage 프로세스가 종료되지 않은 채 화면이
시작 문구에 머무르는 현상을 확인했다. 따라서 rev25도 최종 GUI 검증본으로 사용하지
않으며, Pixman 변경을 포함해 다시 빌드한 ISO에서 화면과 입력 장치를 검증해야 한다.
`rev24`는 오래된 커널이 포함되어 있으므로 역시 사용하지 않는다.

## AI 콘솔 배치

- `local`: tty1에서 한국어 AI 콘솔과 CPU 기반 llama.cpp 서버를 실행한다.
- `remote`: tty1 콘솔은 원격 OpenAI 호환 엔드포인트를 사용한다.
- `off`: tty1을 일반 로그인 셸로 되돌린다.
- 모든 모드에서 tty2는 독립 복구 셸이다.
- AI가 만든 명령은 실행 전에 명령 내용을 표시하고 운영자의 명시적 승인을 받는다.
