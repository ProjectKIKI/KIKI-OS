# KIKI OS 운영자 가이드

이 문서는 KIKI OS의 현재 기능, 빌드 흐름, 패키지 작성 방법, 설치기 동작,
네트워크 방향을 한국어로 정리한 운영자용 문서다.

## 전체 구조

```text
레시피 작성
  -> 의존성 검증
  -> 빌드 계획 생성
  -> .ki2 패키지 빌드
  -> 저장소 인덱스 생성
  -> rootfs 조립
  -> ISO/부팅 ISO/설치 ISO 생성
  -> 웹 콘솔 또는 정적 배포 트리 운영
```

개발 단계 기준:

- stage 1: 부팅과 설치 가능성 증명
- stage 2: 운영 가능한 최소 서버 배포판
- stage 3: 자기 빌드와 쿠버네티스/클러스터 운영이 가능한 독립 배포판

상세 정의는 [KIKI OS 개발 단계 정의](kiki-os-stages.ko.md)를 따른다.

주요 디렉터리:

```text
distro/recipes/        패키지 레시피
distro/profiles/       OS 이미지 프로파일
distro/sources/        local/copy 패키지용 소스 트리
distro/specs/          ki2 패키지, 레시피, 프로파일, 설치 계획 스펙
distro/templates/      새 패키지 작성 템플릿
distro/install-plans/  선언형 설치 계획서 예제
tools/                 빌드, CI, ISO, publish 도구
deploy/container/      컨테이너 기반 빌드 서버
deploy/systemd/        빌드 서버 systemd 유닛 예제
deploy/svn/            SVN post-commit 트리거 예제
```

## 현재 구현된 기능

### ki2 패키지 빌드

`tools/ki2build.py`는 KIKI OS의 기본 패키지 빌드 도구다.

지원 기능:

- TOML/YAML 레시피 로드
- YAML 프로파일 로드
- 의존성 그래프 검증
- 런타임/빌드 의존성 계획 출력
- 빌드 캐시 키 생성
- URL/local/virtual 소스 처리
- `gnu`, `make`, `cmake`, `meson`, `python`, `kernel`, `copy`, `virtual` 빌드 방식 지원
- patch 적용
- 빌드 환경 변수 확장
- `.ki2` 패키지 생성
- 패키지 manifest 생성
- 저장소 인덱스 생성
- rootfs 조립
- systemd unit enable 링크 생성

주요 명령:

```bash
python tools/ki2build.py list
python tools/ki2build.py validate --profile distro/profiles/minimal-systemd.toml --max-packages 64
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml --include-build-deps
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --allow-unpinned
python tools/ki2build.py repo-index
python tools/ki2build.py rootfs --profile distro/profiles/minimal-systemd.toml --rootfs-dir dist/rootfs/minimal-systemd
```

WSL Rocky 9 빌드 예:

```bash
python3 tools/ki2build.py \
  --repo-root /mnt/f/GitHub/KIKI-OS \
  --arch x86_64 \
  --jobs 8 \
  --toolchain-id rocky9-stage0-gcc11-v1 \
  build \
  --profile distro/profiles/minimal-systemd.toml \
  --build-dir /tmp/kiki-ki2-minimal-systemd \
  --allow-unpinned
```

### `.ki2` 패키지 형식

`.ki2`는 gzip tar 아카이브다.

구조:

```text
manifest.json
rootfs/
```

`rootfs/` 아래 경로는 대상 OS 내부 경로가 된다.

예:

```text
rootfs/etc/os-release                         -> /etc/os-release
rootfs/usr/bin/dbus-daemon                    -> /usr/bin/dbus-daemon
rootfs/usr/lib/systemd/system/dbus.service    -> /usr/lib/systemd/system/dbus.service
rootfs/boot/vmlinuz-kiki                      -> /boot/vmlinuz-kiki
```

패키지 manifest에는 다음 정보가 들어간다.

- 패키지 이름, 버전, 릴리스, 아키텍처
- 라이선스와 요약
- build/runtime 의존성
- 파일 목록, 권한, sha256
- 빌드 키
- 레시피 digest
- 빌드 시간
- 패키지 형식 리비전

권한 정책:

- `/etc/shadow`, `/etc/gshadow`: `0600`
- `/root`: 디렉터리 `0700`, 파일 `0600`
- systemd unit, tmpfiles, 일반 설정 파일: `0644`
- 실행 파일 경로: `0755`
- setuid/setgid/sticky bit가 필요한 파일: 원본 모드 보존
- tar owner: `root/root`

### minimal-systemd 프로파일

기본 systemd 프로파일은 `distro/profiles/minimal-systemd.toml`이다.

포함 방향:

- 커널: `linux`
- libc: `glibc`
- init: `systemd`
- system bus: `dbus`
- 로그인/session: `shadow`, `bash`, `getty@tty1.service`, `systemd-logind.service`
- 네트워크: `iproute2`, `systemd-networkd`, `systemd-resolved`, DHCPv4 기본 설정
- 프로세스 관리: systemd PID 1, cgroup accounting, `systemctl`, `journalctl`, `loginctl`, `networkctl`, `ps`, `top`
- 원격 접근: `openssh`
- 운영 도구: `coreutils`, `findutils`, `grep`, `sed`, `gawk`, `tar`, `gzip`, `xz`, `zstd`, `curl`
- KIKI 도구: `ki2ctl`, `kiki-agent`

활성화되는 systemd unit:

```text
dbus.service
getty@tty1.service
systemd-logind.service
systemd-networkd.service
systemd-resolved.service
sshd.service
kiki-agent.service
```

`base-files`는 `nsswitch.conf`, `resolv.conf`, `logind.conf`,
`resolved.conf`, `system.conf`, `login.defs`, `securetty`, `/etc/profile`,
`/etc/motd`, tmpfiles 설정, 기본 DHCP networkd 설정을 제공한다.

## 네트워크 설계

KIKI OS의 기본 네트워크 관리는 `systemd-networkd`와 `systemd-resolved`로 한다.

기본값으로 선택한 이유:

- systemd 기반 배포판과 구성이 자연스럽다.
- 서버, VM, 쿠버네티스 노드처럼 자동화된 환경에 적합하다.
- `.network` 파일만 생성하면 무인 설치와 disconnected 설치에서 예측 가능하다.
- 패키지 수와 런타임 의존성이 작다.
- `networkctl`, `resolvectl`, `journalctl -u systemd-networkd`로 진단 흐름이 단순하다.

`NetworkManager`는 추후 선택 패키지로 추가한다.

`NetworkManager`가 적합한 경우:

- 데스크톱
- Wi-Fi
- VPN
- 노트북
- GUI 기반 네트워크 설정
- 사용자가 자주 네트워크를 전환하는 환경

현재 목표가 서버/쿠버네티스 노드이므로 기본 프로파일에서는
`systemd-networkd`를 유지한다.

## 빌드 자동화와 웹 콘솔

`tools/ki2ci.py`는 CLI 파이프라인과 웹 콘솔을 제공한다.

파이프라인:

```text
smoke             빠른 Go/Python/레시피 검증
bootstrap         bootstrap-stage1 패키지, repo, rootfs 빌드
minimal-systemd   systemd 기반 기본 OS 패키지 빌드
security          소스 pin, shell syntax, scanner 확인
iso               payload ISO 생성
bootiso           GRUB 부팅 ISO 생성
installer-iso     KIKI 로고와 TUI 설치 ISO 생성
publish           repo/package/ISO 산출물 배포 트리 생성
release           smoke부터 publish까지 묶음 실행
```

CLI 실행:

```bash
python tools/ki2ci.py run smoke
python tools/ki2ci.py run minimal-systemd --jobs 8 --toolchain-id rocky9-stage0-gcc11-v1
python tools/ki2ci.py run publish --publish-dir /srv/www/kiki
```

웹 콘솔 실행:

```bash
python tools/ki2ci.py serve --host 127.0.0.1 --port 8090
```

웹 콘솔 기능:

- 파이프라인 실행
- job 목록 확인
- job 로그 확인
- 패키지 카탈로그 확인
- 프로파일 확인
- 패키지/rootfs/ISO/VHDX 산출물 확인
- 보안 검사 페이지

주의: 웹 콘솔은 자체 인증이 없다. 실제 빌드 서버에서는 localhost, VPN, 또는
인증 리버스 프록시 뒤에서 운영한다.

## 컨테이너 빌드 서버

`deploy/container/`는 Rocky 9 기반 컨테이너 빌드 서버를 제공한다.

이미지 빌드:

```bash
podman build -f deploy/container/Containerfile -t kiki-buildd:rocky9 .
```

웹 콘솔 실행:

```bash
podman run --rm -it \
  -p 8090:8090 \
  -v "$PWD:/work" \
  -e KIKI_JOBS="$(nproc)" \
  kiki-buildd:rocky9
```

파이프라인만 실행:

```bash
podman run --rm -it -v "$PWD:/work" kiki-buildd:rocky9 run smoke
podman run --rm -it -v "$PWD:/work" kiki-buildd:rocky9 run minimal-systemd
```

Compose 예:

```bash
podman compose -f deploy/container/compose.yaml up --build
```

## ISO 생성

payload ISO:

```bash
python tools/ki2iso.py --profile bootstrap-stage1
```

부팅 테스트 ISO:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1
```

설치 ISO:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1 --mode installer
```

## TUI 설치기

설치기는 C로 작성된 syscall-only `/init` 바이너리로 동작한다. Go 런타임을
초기 initramfs에 넣지 않아도 되므로 부팅 초기 환경에서 가볍게 실행된다.

주요 기능:

- KIKI 로고 출력
- 패키지 미디어 확인
- 네트워크 인터페이스 확인
- 네트워크 설정: 기본 DHCP, interface match 변경, autoconfiguration 비활성화
- 디스크와 파티션 확인
- `minimal-systemd` 패키지 세트 선택
- 전체 패키지 선택
- 개별 패키지 이름 추가
- 자동 파티셔닝: ESP + swap + root
- 수동 파티셔닝: shell에서 `fdisk`/`cfdisk` 사용 후 파티션 경로 입력
- 관리자 사용자 생성
- root 직접 로그인 잠금 기본값
- sudoers 정책 작성
- systemd 기본 유닛 활성화
- UEFI fallback bootloader 설치
- 선언형 설치 계획서 미리보기

자동 파티셔닝 정책:

- ESP: 디스크 크기에 따라 512-768 MiB
- swap: 메모리 x2, 최대 16 GiB
- root: 나머지 ext4

수동 파티셔닝 정책:

- 사용자가 직접 ESP/root/swap 파티션을 만든다.
- 설치기는 입력된 파티션만 포맷한다.
- 전체 디스크와 파티션 경로를 구분한다.

설치 계획서:

```text
/run/kiki/install-plan.yaml
/var/lib/ki2/install-plan.yaml
```

설치 전에는 `/run/kiki/install-plan.yaml`을 화면에 보여주고, 설치 후에는 같은
계획서를 `/var/lib/ki2/install-plan.yaml`로 복사한다. 비밀번호는 계획서에
저장하지 않는다.

설치 계획서의 네트워크 섹션은 다음 값을 기록한다.

```yaml
network:
  manager: "systemd-networkd"
  resolver: "systemd-resolved"
  mode: "dhcp"
  interface_match: "en* eth*"
  dhcp4: true
  ipv6_accept_ra: true
```

## 사용자와 로그인

설치기는 기본적으로 다음 정책을 따른다.

- 기본 hostname: `localhost.localdomain`
- 기본 관리자 사용자: `kiki`
- lab 기본 암호: `kiki`
- root 직접 로그인: 잠금
- 관리자 사용자는 `sudo` 그룹에 추가

운영자가 설치 중 다른 관리자 이름과 암호를 입력할 수 있다. root 직접 로그인을
허용하면 root도 같은 암호로 설정된다.

## 패키지 작성 예제

소스 빌드 패키지:

```yaml
recipes:
  - name: my-package
    version: "1.0.0"
    release: 1
    summary: 예제 런타임 패키지
    license: Apache-2.0
    tier: runtime
    architectures:
      - x86_64
    source:
      type: url
      url: https://example.invalid/my-package-1.0.0.tar.gz
      sha256: REPLACE_ME
    depends:
      build: []
      runtime:
        - glibc
    build:
      system: gnu
      configure_options:
        - --disable-static
```

OS 설정 패키지:

```yaml
recipes:
  - name: my-os-config
    version: "0.1.0"
    release: 1
    summary: 대상 rootfs에 설치되는 OS 설정 패키지
    license: GPL-3.0-or-later
    tier: kiki
    architectures:
      - all
    source:
      type: local
      path: distro/sources/my-os-config
    depends:
      build: []
      runtime:
        - systemd
    build:
      system: copy
```

소스 트리 예:

```text
distro/sources/my-os-config/
  etc/
    my-config.conf
  usr/
    lib/
      systemd/
        system/
          my-service.service
```

빌드:

```bash
python tools/ki2build.py validate --profile distro/profiles/minimal-systemd.toml --max-packages 64
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --allow-unpinned
python tools/ki2build.py repo-index
```

## 쿠버네티스 노드 방향

`distro/profiles/kiki-kube-node.yaml`은 CRI-O 기반 쿠버네티스 노드 프로파일이다.

핵심 패키지:

- `cri-o`
- `conmon`
- `crun`
- `cni-plugins`
- `cri-tools`
- `kubelet`
- `kubeadm`
- `kubectl`
- `kube-node-config`

쿠버네티스 노드에서도 기본 네트워크 관리는 `systemd-networkd`로 둔다. CNI는
pod network 영역을 담당하고, 호스트 기본 링크/DHCP/DNS는 systemd 계열로
단순하게 유지한다.

## 배포

정적 배포 트리 생성:

```bash
python tools/ki2publish.py --target /srv/www/kiki
```

출력 구조:

```text
publish/
  manifest.json
  repo/
  packages/
  iso/
```

이 디렉터리는 nginx 같은 내부 웹 서버로 제공할 수 있다.

## 남은 큰 작업

- target sysroot toolchain 구성
- source hash pin 정리
- 패키지 충돌 탐지
- 설치된 시스템의 패키지 DB
- 온라인 패키지 관리자
- 저장소 서명
- NetworkManager 선택 패키지
- 웹 기반 설치기
- 무인 설치와 disconnected 설치 완성
