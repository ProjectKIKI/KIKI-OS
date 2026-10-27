# 선택형 X Window 런타임

기존 r17 Wayland/Cage 설치기를 유지하고, 별도 kiki-x11-runtime 패키지를 추가한다.
이 단계는 Rocky 9 ABI를 활용하는 부트스트랩이며, 독립 네이티브 Xorg 패키지 분할은 아니다.

## 구성

- Xorg 1.20.11-34.el9_8.3 (Rocky 배포 패치 포함).
- Xvfb, xinit, xauth, xterm, xkbcomp, xdpyinfo, xwininfo, xrandr.
- Xorg modesetting 모듈, libinput 입력 드라이버, X11 폰트/로케일 및 터미널 데이터.
- kiki-startx: 로컬 텍스트 콘솔에서 최소 Xorg + xterm 세션 실행.
- kiki-x11-check: r17 그래픽 런타임 식별자, 공유 파일, ELF 의존성 사전검사.
- Xwayland, 윈도 매니저, 데스크톱 환경, 디스플레이 매니저는 포함하지 않는다.

## 안전/호환성

- TCP 리스닝을 끄고 MIT-MAGIC-COOKIE-1 인증을 사용한다. xhost + 또는 -ac를 사용하지 않는다.
- setuid Xorg.wrap은 배포하지 않는다. kiki-startx를 sudo로 실행하는 방식은 권장하지 않는다.
  로컬 로그인 세션의 systemd-logind/VT/DRM 권한이 준비되어야 한다.
- 자동 그래픽 로그인 및 기존 기본 타깃을 변경하지 않는다.
- r17에 있는 동일 파일은 중복 패키징하지 않고, 내용이 다른 파일 충돌은 빌드에서 거부한다.
  기존 installer-gtk 번들에 의존하므로 다른 그래픽 기반으로 옮기면 다시 준비/검증해야 한다.
- ldconfig는 SONAME 링크를 바꿀 수 있어 링크 대상 문자열을 고정하지 않는다.
  원본 공유 파일 해시와 실제 Xorg/Xvfb/xterm ELF 로딩은 검사한다.
- 호스트 RPM 버전, 파일 해시, 공유 의존 파일은 usr/share/kiki-x11/runtime-manifest.json에 기록한다.
  호스트 패키지 업데이트 후 결과가 동일하다고 가정하지 않는다.

## 빌드

WSL Rocky 9에 xorg-x11-server-Xorg, xorg-x11-server-Xvfb, xorg-x11-xinit,
xorg-x11-xauth, xorg-x11-drv-libinput, xterm, xorg-x11-utils, xorg-x11-fonts-misc가 필요하다.
기존 경로를 덮어쓰지 않는 새 출력 디렉터리에서 tools/ki2x11.py를 실행한다.

~~~sh
python3 tools/ki2x11.py --base-rootfs /path/to/verified-r17-rootfs \
  --output build/ki2/host-x11/rootfs
python3 tools/ki2build.py build --profile distro/profiles/x11-runtime.toml \
  --only kiki-x11-runtime --packages-dir dist/ki2/x11-packages
~~~

--only 옵션으로 현재 검증 기반을 교체하지 않고 추가 패키지만 만든다.
일반 그래픽 레시피의 C/release 13 경로는 r17 gotk/release 15와 다르므로,
전체 의존 패키지를 무조건 다시 빌드하여 섞지 않는다.
패키지 설치 후 ldconfig를 실행하고 로컬 tty에서 kiki-x11-check, kiki-startx를 사용한다.
디스플레이 :0이 사용 중이면 시작하지 말고 기존 세션을 확인한다.

## 검증 범위

- 파일 충돌 및 로컬 세션 안전성 단위 테스트 통과.
- r17 rootfs 복사본에서 Xorg/Xvfb/xterm ELF 로딩 확인.
- Xvfb + xdpyinfo, 무인증 접속 거부, xterm 자식 명령 실행 통과.
  시험 rootfs에 독립 devpts 및 읽기 전용 proc를 임시 제공하고 종료 후 해제했다.
- 실제 Xorg의 DRM/VT 전환, Hyper-V 입력 장치, rootless logind 세션은 아직 시험하지 않았다.
- 기존 r17 ISO와 사용자 VM은 변경하지 않았다. ISO 포함 및 실제 화면 시험은 별도 단계다.

## 생성된 패키지

- dist/ki2/x11-packages/x86_64/kiki-x11-runtime-0.1.0-1.x86_64.ki2
- 크기: 11,562,977 bytes.
- SHA-256: 76b925d187b786e73f166e27c7d08b2d617004472c61c6b1d2f1ef7c0eb4e0b1
- 최종 패키지를 테스트 rootfs에 직접 추출한 인수 시험도 통과했다.
- 증거: build/validation/20260927-x11/.
- 패키지 파일만 생성했으며 공개 저장소 서명 인덱스나 ISO에 추가하지 않았다.
