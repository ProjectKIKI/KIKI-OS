# KIKI OS GTK 4 설치 계획 작성기

`kiki-installer-gtk`는 GTK 4 기반 설치 프런트엔드입니다. YAML을 독자적으로
작성하지 않고 `kiki-installer-tui --write`를 호출하므로 CLI, TUI, GUI와 무인
설치에서 동일한 프로필 선택, 검증 및 `InstallPlan` 직렬화 로직을 사용합니다.

ISO 런타임은 내장 seatd가 활성화된 libseat와 udev 입력 장치 태깅을 사용합니다.
GUI 시작 실패 로그는 `/run/kiki/gui-installer.log`에서 확인할 수 있습니다.

현재 GUI의 책임은 설치 계획 검토와 저장까지입니다. 실제 파티션 포맷과 패키지
추출은 Stage-1 설치 실행기가 담당하며, GUI가 없는 서버와 그래픽 초기화 실패
환경에서는 기존 TUI를 사용합니다.

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
