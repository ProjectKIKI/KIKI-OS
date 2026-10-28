# KIKI OS GTK 4 인스톨러

`kiki-installer-gtk`는 GTK 4 기반 설치 프런트엔드입니다. YAML을 독자적으로
작성하지 않고 `kiki-installer-tui --write`를 호출하므로 CLI, TUI, GUI와 무인
설치에서 동일한 프로필 선택, 검증 및 `InstallPlan` 직렬화 로직을 사용합니다.

ISO 런타임은 내장 seatd가 활성화된 libseat와 udev 입력 장치 태깅을 사용합니다.
GUI 시작 실패 로그는 `/run/kiki/gui-installer.log`에서 확인할 수 있습니다.
Xorg를 거치지 않고 Cage/wlroots가 DRM/KMS 장치를 직접 사용합니다.
Hyper-V처럼 가속 렌더 노드가 없는 장치에서는 wlroots Pixman과 DRM dumb buffer로
화면을 그립니다.

검토 화면의 `설치 시작` 버튼은 계획을 저장한 뒤 `/run/kiki/gui-install.request`로
Stage-1 실행기에 전달합니다. GUI에서 선택한 디스크, 프로필과 추가 그룹,
네트워크, 지역화 및 AI 설정은 실제 설치에 사용됩니다. 관리자 암호와 암호 확인은
계정 화면에서 입력하고, 검토 화면에서는 대상 디스크를 확인하고 데이터 삭제 동의
체크박스를 선택합니다. 디스크를 변경하면 동의가 해제됩니다. 직접 확인 문자열을
입력할 필요는 없습니다. 암호는 InstallPlan이나 영구 디스크에 기록하지 않습니다. 프로세스
간 전달을 위해 mode 0600인 `/run` tmpfs 요청 파일에 잠시 기록하며 Stage-1이
읽은 즉시 파일 내용을 제거합니다.

실제 파티션 포맷과 패키지 추출은 Stage-1 설치 실행기가 담당합니다. GTK는
`/run/kiki/install-progress.state`를 주기적으로 읽어 설치 단계, 진행률과 현재
패키지, `설치 완료 개수 / 전체 개수`를 표시하고 설치 중에는 종료되지 않습니다.
설치 완료 후 사용자가
`확인 후 재부팅` 버튼을 누르면 `/run/kiki/gui-reboot.request`를 전달하며,
Stage-1은 이 명시적 확인을 받은 경우에만 재부팅합니다. 설치 시작 전에 GUI
창만 닫으면 설치 요청 없이 TUI로 폴백하며, GUI가 없는 서버와 그래픽 초기화
실패 환경에서도 기존 TUI를 사용합니다.

개발 환경 실행:

```sh
make -C cmd/kiki-installer-gtk
KIKI_INSTALLER_TUI="$(pwd)/build/kiki-installer-tui" \
KIKI_INSTALLER_CSS="$(pwd)/cmd/kiki-installer-gtk/style.css" \
  ./cmd/kiki-installer-gtk/kiki-installer-gtk
```

설치 ISO용 Cage/Wayland·한글 폰트 런타임 생성 및 패키징:

```sh
python3 tools/ki2graphics.py doctor
python3 tools/ki2graphics.py prepare --installer-ui c --jobs 4
python3 tools/ki2build.py build \
  --profile distro/profiles/server-core.toml --only kiki-installer-gtk
```

Stage 3 빌드 계획은 `graphics.installer_ui: c`로 이 화면을 명시적으로 선택한다.
창 제목 표시줄은 하나만 사용하며, 각 설정 화면은 스크롤되고 이전/다음 버튼은
하단에 고정된다. 계획 경로와 자동화 모드는 시작 화면의 고급 옵션에 있다.
디스크는 모델·용량을 확인해 직접 선택한다. `/dev/sda`를 기본 선택하지 않는다.

로컬 화면·계획 생성·설치 요청 연동 테스트:

```sh
KIKI_GTK_TEST_ARTIFACTS=artifacts/installer-ui-test \
  python3 tools/test_gtk_installer_ui.py
```

Linux, GTK 4 개발 헤더, Go와 Xvfb가 필요하다. 실제 GTK 창을 한국어/영어와
1024×768·800×600 크기로 렌더링한다. Go 계획 생성기는 실제 실행하고,
설치·진행 상태·재부팅 요청은 임시 디렉터리의 모의 백엔드로 확인한다.
호스트 디스크를 포맷하거나 실제 재부팅하지 않는다. 이 테스트가 VM 설치 인수
검증을 대신하지는 않는다.

실제 패키지의 GUI·미디어 검증기·파티션 도구를 조합하는 Linux chroot 검사:

```sh
sudo env KIKI_TEST_MEDIA_RUNTIME=1 PYTHONPATH=tools \
  python3 -m unittest tools/test_ki2media_runtime.py
```

기본 패키지 경로는 `dist/ki2/packages/x86_64`이며, 별도 후보 저장소는
`KIKI_TEST_PACKAGES`로 지정한다. 이 검사는 `sfdisk`·`mkfs.ext4` 실행과 서명 검증,
손상·누락 패키지 및 변조된 메타데이터 거부를 확인한다. 장치에 쓰지는 않는다.

설치 대상 패키지로 만든 별도 rootfs에는 다음 검사도 실행한다. GUI 런타임이
기본 명령을 덮어쓰지 않은 패키지 조합이어야 한다.

```sh
sudo env KIKI_CLI_TEST_ROOTFS=/path/to/disposable-installed-rootfs PYTHONPATH=tools \
  python3 -m unittest tools/test_installed_cli_runtime.py
```

`id`, `ls`, `cp`, `mv`, `stat`, `awk`, `find`, `sed`, `grep`, `tar`를 chroot에서 실행해
빌드 호스트 라이브러리에 대한 숨은 의존성을 확인한다.

## Hyper-V 확인

Hyper-V 2세대 VM에서는 Secure Boot를 끕니다. 로그에 `Found 0 GPUs` 또는
`Unable to create the wlroots backend`가 나타나면 GTK 자체보다 DRM 장치 생성과
커널 설정을 먼저 확인합니다. 지원 커널 구성은 다음과 같습니다.

```text
CONFIG_DRM_HYPERV=y
CONFIG_DRM_FBDEV_EMULATION=y
# CONFIG_FB_HYPERV is not set
```

`CONFIG_FB_HYPERV`와 `CONFIG_DRM_HYPERV`를 동시에 켜면 두 드라이버가 같은
Hyper-V 합성 비디오 장치를 두고 충돌할 수 있습니다. 정상 환경에서는 GUI 시작
전에 `/dev/dri/card0`이 존재해야 합니다. GUI가 실패하면 설치기는 전체 화면 TUI,
그 다음 Stage-1 CLI 순서로 폴백합니다.

오류가 출력되지 않은 채 Cage 시작 문구에 머무르는 경우는 GLES2/GBM이
scanout-only 장치에 화면을 표시하지 못한 경우와 구분해야 합니다. 설치 ISO는
`WLR_RENDERER=pixman`을 강제해 이 경로를 사용하지 않습니다.

wlroots는 키맵 전달에 POSIX 공유 메모리를 사용하므로 initramfs의 `/dev/shm`에는
mode 1777 tmpfs가 마운트되어야 합니다. GTK 설치기 런타임에는 libinput의 장치별
quirks 데이터인 `/usr/share/libinput`과 선택적 `/etc/libinput`도 함께 들어갑니다.

## 기존 GNOME 환경 선택

설치 프로파일 `desktop-gnome` 또는 추가 그룹 `desktop-gnome`은 기존에 구성한
GNOME 50·GDM·Wayland·네이티브 Mesa 후보의 `kiki-gnome-desktop`을 선택한다.
GDM과 충돌하는 tty1 AI 콘솔은 끄고, tty2 복구 로그인은 유지한다.
백엔드는 기존 `/usr/libexec/kiki-desktop-prepare`로 계정·캐시를 준비하고
`display-manager.service`와 `graphical.target`을 연결한다.

```sh
kiki-installer-tui --write --profile desktop-gnome --plan /tmp/desktop-plan.yaml
# 기존 서버 프로파일에 데스크톱 그룹을 추가하는 경우:
kiki-installer-tui --write --profile server-core --groups desktop-gnome --plan /tmp/desktop-plan.yaml

python3 tools/ki2build.py plan --profile distro/profiles/desktop-gnome.toml
python3 tools/ki2build.py rootfs --profile distro/profiles/desktop-gnome.toml \
  --rootfs-dir /tmp/kiki-desktop-rootfs
```

빌드 프로파일은 별도 GNOME 후보 저장소의 공개키·인덱스를 고정하고 서명과 모든
선택 패키지 해시를 확인한 뒤 재사용한다. GNOME 소스 재컴파일은 기존 후보 빌드
절차로 수행한다. `server-core` 기본 패키지는 유지한다.
기존 r4 서버 ISO에는 GNOME 패키지가 없으므로 해당 ISO만으로는 설치할 수 없다.
새 설치 미디어에는 업데이트한 설치기와 GNOME 후보 패키지·서명 인덱스가 필요하며,
필수 패키지가 없는 미디어에서는 디스크 쓰기 전에 중단한다.
새 설치 미디어는 설정·파일 앱, GTK4 VTE 터미널, IBus 한글 엔진과 실제 GNOME
키보드·접근성·전원·시간·화면보호·정리·rfkill 설정 데몬을 추가한다.
KIKI 설정과 파일 앱의 제공 범위는
`distro/sources/kiki-desktop-defaults/usr/share/doc/kiki-desktop-defaults/README.ko.md`에
기록한다. GNOME Control Center·Nautilus 전체 기능이나 오디오·화면 공유를 포함한
모든 데스크톱 기능의 지원을 의미하지 않는다.

프로파일·추가 구성은 공통 카탈로그에서 생성한다. 표시 이름은 사용자 언어로
제공하며, 현재 ISO에 없는 구성은 선택할 수 없다. 프로파일마다 기본 AI 정책을
적용하고 검토 화면에는 GDM·그래픽 부팅·tty2 복구 콘솔을 명시한다.
최신 빌드·설치 실측 근거는 `artifacts/desktop-installer-20261027`에 기록한다.
