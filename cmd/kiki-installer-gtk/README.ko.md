# KIKI OS GTK 4 설치 계획 작성기

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
계정 화면에서 입력하고, 검토 화면에서는 `INSTALL /dev/...` 확인 문자열을 정확히
입력합니다. 암호는 InstallPlan이나 영구 디스크에 기록하지 않습니다. 프로세스
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
python3 tools/ki2graphics.py prepare --jobs 4
python3 tools/ki2build.py build \
  --profile distro/profiles/server-core.toml --only kiki-installer-gtk
```

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
