# GNOME 기본 앱 네이티브 빌드 입력

2026-10-28 후보의 실제 빌드·패키징·ISO 검증 도구입니다. 실행 전에
`python3 tools/gnome_native/bootstrap.py`로 `artifacts/gnome-native-apps-20261028`
아래에 도구와 SHA가 고정된 GNOME 50.4 메타데이터를 준비합니다.
기존 파일 내용이 다르면 덮어쓰지 않습니다. 이후 명령은 해당 디렉터리의
도구를 저장소 루트에서 실행합니다. Linux root 빌드 환경이 필요합니다.

이 도구는 보존된 KIKI 네이티브 SDK에 추가하는 후보 빌드입니다.
빈 배포판에서 바로 실행하는 범용 빌드가 아닙니다. 기본 입력은
`/tmp/kiki-desktop-apps-20261027/sdk`,
`/home/tang/kiki-build/gnome50-session-20261017`의 호스트 도구·Rust·vendor,
`dist/ki2/desktop-installer-20261027`의 서명된 기준 패키지,
기존 GNOME 후보의 `gnome50-source-lock.json`입니다.
입력 후보와 SDK를 보존하고 별도 `/tmp/kiki-gnome-native-apps-20261028`에서
빌드합니다. WSL에서 Rust를 빌드할 때 `/proc/self/exe`가 현재 PID namespace를
가리켜야 합니다. 호스트 의존성에는 GCC, clang++, Meson, Ninja, gettext-devel,
gtk-doc, desktop-file-utils, appstream, perl-Parse-Yapp, libcom_err-devel,
libss-devel과 Go가 포함됩니다.

`sources.json`에 다운로드 URL과 SHA-256을 고정했습니다. GNOME 릴리스 tar는
공식 빌드 메타데이터의 SHA를 검증하고, Git 소스는 고정 커밋의 아카이브 SHA를
재확인합니다. `prepare-platform.py`는 GNOME이 지정한 freedesktop-sdk 커밋의
메타데이터를 사용합니다. 소스 준비는 동시에 실행하지 않습니다.

순서는 다음과 같습니다.

1. `prepare-sources.py`로 nautilus, gnome-control-center, tinysparql, libportal,
   librest, gnome-online-accounts, libgtop, colord-gtk, udisks2, gtk+-3, libnma,
   gnome-console, gnome-backgrounds, blueprint-compiler, tecla, samba, krb5를 준비합니다.
   `prepare-platform.py`, `fetch-readline.py`로 나머지 입력을 준비합니다.
   `prepare-sources.py localsearch`와 `prepare-portal-runtime.py`로 로컬 검색,
   FUSE, PipeWire, GStreamer, 포털과 사용자 폴더 도구를 준비합니다.
2. `prepare-blueprint.py`, `build-glycin-gtk4.py`를 실행합니다.
3. `build-runtime-libs.py libxcrypt libcom-err libatomic`으로 실제 SONAME을 가진
   암호·오류·원자 연산 라이브러리를 먼저 준비합니다.
   `build-native.py`에 sqlite libportal tinysparql libndp libwacom cracklib pwquality
   librest gnome-online-accounts readline cups-base libgtop colord-gtk udisks2
   NetworkManager gtk+-3 libnma ModemManager accountsservice-pc krb5를 순서대로
   전달합니다. `build-smbclient.py`를 실행한 뒤 `build-native.py`에
   fuse3 pipewire gstreamer xdg-desktop-portal xdg-desktop-portal-gnome
   localsearch xdg-user-dirs nautilus
   gnome-console gnome-backgrounds gnome-control-center를 순서대로 전달합니다.
4. `build-kernel.py`로 Linux 6.1.187을 빌드합니다. `installed-kernel.config`는
   설치 VM에서 읽은 기존 설정이며 FUSE만 추가합니다. 기존 x86-64-v2 CPU
   요구와 모듈 구성을 유지합니다. 문서 포털의 샌드박스를 해제하지 않습니다.
   `package-util-linux.py`로 보존된 util-linux의 mount/umount를 systemd가
   요구하는 `/usr/bin`에서도 실행할 수 있게 패키징합니다.
   `package-frontends.py`, `build-media.py`, `verify-media.py`,
   `check-rootfs.py`, `check-password-abis.py`를 실행합니다.
   기존 ISO는 덮어쓰지 않습니다. 개인 서명키는 Linux 작업 폴더에만 두고
   공개키·서명된 메타데이터만 배포합니다.
5. `hyperv-test-r3.ps1`은 지정된 새 시험 VM의 이름·ID·디스크를 확인하고 조작합니다.
   실제 설치, 로그인, 앱 동작, 재부팅 검증은 별도 수행하며 빌드 성공만으로
   설치 성공을 표시하지 않습니다. `guest-acceptance.py`는 설치된 게스트에서 실행합니다.

NetworkManager는 설치 계획을 받아 GNOME 네트워크 화면과 연결됩니다.
서버 프로파일은 기존 networkd를 사용합니다. UDisks는 이 후보에서 클라이언트
라이브러리만 빌드하며 이동식 디스크 자동 마운트 검증을 뜻하지 않습니다.
실물 GPU·무선·오디오·프린터·원격 공유의 동작은 해당 장치에서 별도 검증해야 합니다.
