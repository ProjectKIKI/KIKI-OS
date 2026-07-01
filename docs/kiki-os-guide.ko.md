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

- `stage1-v1`: 부팅과 설치 가능성 증명을 마친 최종 기준선
- `stage2-v2`: 운영 가능한 최소 서버 배포판 기준선
- stage 3: 자기 빌드와 쿠버네티스/클러스터 운영이 가능한 독립 배포판

상세 정의는 [KIKI OS 개발 단계 정의](kiki-os-stages.ko.md)를 따른다. Stage 1의
고정 범위는 [KIKI OS Stage 1 V1 최종 문서](kiki-stage1-v1-final.ko.md), Stage 2의
완료 범위는 [KIKI OS Stage 2 V2 완료 문서](kiki-stage2-v2-progress.ko.md)를 우선한다.

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

콘솔 환경은 `/etc/profile`에서 `LESS=-R`, `LESSCHARSET=utf-8`,
`SYSTEMD_COLORS=1`, `SYSTEMD_URLIFY=0`, `SYSTEMD_LESS=FRSXMK`를 기본값으로
둔다. 이 설정은 `systemctl status`와 `journalctl`의 ANSI color를 보존하고,
Hyper-V 콘솔처럼 OSC 8 hyperlink escape를 제대로 표시하지 못하는 환경에서
`file://...` 제어 문자열이 화면에 노출되는 문제를 피하기 위한 기본값이다.

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

설치 후 네트워크 변경은 `kiki-netconfig`로 처리한다.

```bash
sudo kiki-netconfig dhcp --apply
sudo kiki-netconfig static --address 192.168.122.50/24 --gateway 192.168.122.1 --dns 1.1.1.1 --apply
kiki-netconfig status
```

자세한 사용법은 [KIKI OS 네트워크 설정 도구](kiki-network-config.ko.md)를 따른다.

## 빌드 자동화와 웹 콘솔

`tools/ki2ci.py`는 CLI 파이프라인과 웹 콘솔을 제공한다.

파이프라인:

```text
smoke             빠른 Go/Python/레시피 검증
bootstrap         bootstrap-stage1 패키지, repo, rootfs 빌드
minimal-systemd   systemd 기반 기본 OS 패키지 빌드
stage2           ISO 없이 서명된 Stage 2 저장소 metadata, CRI-O/containerd Kubernetes 계획, Go TUI 렌더링 검증
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
python tools/ki2stage2.py verify-kubernetes --require-signed-metadata
python tools/ki2stage2.py verify-network-userspace
python tools/ki2stage2.py verify-installed-rootfs --root /mnt/target --runtime containerd
python tools/ki2ci.py run stage2
python tools/ki2ci.py run minimal-systemd --jobs 8 --toolchain-id rocky9-stage0-gcc11-v1
python tools/ki2ci.py run publish --publish-dir /srv/www/kiki
```

`ki2stage2.py verify-kubernetes --strict-production`은 placeholder 패키지를 실패로
처리한다. Stage 2 최종 완료 판정에서는 이 strict 모드가 통과해야 한다.

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

ISO 파일명 규칙:

```text
kiki-<release-channel>-<mode>-<arch>-YYYYMMDD-revN.iso
kiki-<release-channel>-<arch>-YYYYMMDD-revN.iso
```

`release-channel`은 기본적으로 `dist/ki2/repo/metadata.<arch>.json`의
`channel` 값이다. 현재 Stage 2 저장소에서는 `stage2-v2`가 된다. 저장소 metadata가 없으면 `bootstrap-stage1` 프로필은 `stage1-v1`로 기록된다. `revN`은
`git rev-list --count HEAD` 기준이다. `--release-name`으로 채널 이름만 바꾸거나
`--output`으로 전체 파일명을 직접 지정할 수 있다.

## TUI 설치기

설치기는 C로 작성된 syscall-only `/init` 바이너리로 동작한다. Go 런타임을
초기 initramfs에 넣지 않아도 되므로 부팅 초기 환경에서 가볍게 실행된다.
Stage 1에서는 이 C 설치기가 실제 설치 경로를 담당한다.

동시에 Stage 1부터 Go 기반 `kiki-installer-tui` preview를 패키지로 포함한다.
이 도구는 설치를 직접 실행하기보다 같은 선언형 설치 계획서를 상태판 형태로
렌더링하고, Stage 2에서 설치 계획서 계약을 검증하는 기반이다. Go TUI를 단독
설치기로 승격하는 작업은 Stage 3 후보로 둔다.

주요 기능:

- KIKI 로고 출력
- 패키지 미디어 확인
- 네트워크 인터페이스 확인
- 네트워크 설정: 기본 DHCP, interface match 변경, autoconfiguration 비활성화
- 디스크와 파티션 확인
- Disk 메뉴에서 `cfdisk`/`fdisk` 즉시 실행
- `minimal-systemd` 패키지 세트 선택
- `kiki-kube-bootstrap`, `kiki-kube-control`, `kiki-kube-compute` 쿠버네티스 역할별 패키지 세트 선택
- 전체 패키지 선택
- 저장소 인덱스의 패키지 record 수와 고유 패키지 이름 수 구분 표시
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
- fstab은 `/dev/sdX` 이름 대신 `LABEL=KIKI_ROOT`, `LABEL=KIKI_EFI`,
  `LABEL=KIKI_SWAP`을 우선 사용한다.
- swap 항목에는 `nofail,x-systemd.device-timeout=10s`를 붙여 swap 장치 문제로
  emergency mode에 빠지는 일을 줄인다.

수동 파티셔닝 정책:

- 사용자가 직접 ESP/root/swap 파티션을 만든다.
- `1) Disk` 메뉴에서 `cfdisk`를 바로 실행할 수 있다.
- Disk 메뉴에서 편집한 디스크는 설치 단계의 기본 후보로 기억한다.
- 일반적인 `ESP + swap + root` 레이아웃이면 `/dev/sda1`, `/dev/sda2`,
  `/dev/sda3` 같은 후보를 ESP/swap/root 기본값으로 제안한다.
- 설치기는 입력된 파티션만 포맷한다.
- 전체 디스크와 파티션 경로를 구분한다.
- swap 후보가 제안되었지만 사용하지 않으려면 `none`을 입력한다.
- `cfdisk` 명령은 별도 `cfdisk` convenience 패키지로 노출하고, 실제
  파티션 편집 바이너리는 `util-linux`, TUI 런타임 라이브러리는 `ncurses`가
  제공한다.

설치 계획서:

```text
/run/kiki/install-plan.yaml
/var/lib/ki2/install-plan.yaml
```

설치 전에는 `/run/kiki/install-plan.yaml`을 화면에 보여주고, 설치 후에는 같은
계획서를 `/var/lib/ki2/install-plan.yaml`로 복사한다. 비밀번호는 계획서에
저장하지 않는다.

Stage 2 무인 설치:

```text
kiki.autoinstall=erase kiki.profile=kiki-kube-compute-containerd kiki.runtime=containerd kiki.target=/dev/sda kiki.hostname=localhost.localdomain
```

무인 설치 파라미터는 ISO 부팅 항목의 kernel command line에 추가한다. `kiki.autoinstall`이 없으면 기존 TUI가 뜨고, `erase` 또는 `quick-vm`일 때만 콘솔 확인 없이 진행한다. `kiki.target`을 생략하면 인스톨러가 가장 큰 VM 디스크를 선택한다. Kubernetes 프로파일은 설치 계획서에 `runtime`, `kubernetes`, `firewall`, `artifacts` 섹션을 기록하고 swap을 끈다.

Go TUI preview:

```bash
kiki-installer-tui --render
kiki-installer-tui --profile kiki-kube-compute --render
kiki-installer-tui --write --plan /run/kiki/install-plan.yaml
```

Stage 2 Go TUI의 저장소 source 명령:

```text
source local /run/install-media
source mirror /srv/kiki-mirror
source remote http://repo.example.internal:8080
verify-key /etc/ki2/trust/stage2-v2-repo.hmac
```

Go TUI는 다음 원칙을 따른다.

- 첫 화면은 “상태판 + 편집 명령” 구조로 둔다.
- TUI의 중심 데이터는 `/run/kiki/install-plan.yaml`이다.
- `start`와 `--write`는 Stage 1 설치기가 소비할 계획서를 작성하는 handoff 단계다.
- 비밀번호 평문은 계획서에 저장하지 않는다.
- Kubernetes 역할 프로필은 기본적으로 swap을 끈다.
- Kubernetes 계획서는 kubeadm action, role template, local config output,
  command, CRI socket을 기록하고 `verify-install-plan`으로 검증한다.
- 방화벽 backend는 `nftables`로 기록하고, `firewalld`는 선택값으로 둔다.
- bridge 점검 기본 도구는 `iproute2`의 `bridge` 명령이다.

설치 계획서의 네트워크 섹션은 다음 값을 기록한다.

```yaml
network:
  manager: "systemd-networkd"
  resolver: "systemd-resolved"
  mode: "dhcp"
  interface_match: "en* eth*"
  dhcp4: true
  ipv6_accept_ra: true
  address: ""
  gateway: ""
  dns: ""
  ntp: ""
```

`mode`는 `dhcp`, `static`, `off` 중 하나다. `static` 모드에서는 `dhcp4`와
`ipv6_accept_ra`를 끄고 `address`, `gateway`, `dns`, `ntp` 값을
`systemd-networkd`의 `Address=`, `Gateway=`, `DNS=`, `NTP=`로 렌더링한다.

## 사용자와 로그인

설치기는 기본적으로 다음 정책을 따른다.

- 기본 hostname: `localhost.localdomain`
- 기본 관리자 사용자: `kiki`
- lab 기본 암호: `kiki`
- root 직접 로그인: 잠금
- 관리자 사용자는 `sudo` 그룹에 추가

운영자가 설치 중 다른 관리자 이름과 암호를 입력할 수 있다. root 직접 로그인을
허용하면 root도 같은 암호로 설정된다.

설치 후 Stage 1 기본 상태는 다음 명령으로 점검한다.

```bash
kiki-stage1-check
```

이 명령은 `systemctl`, `journalctl`, `loginctl`, `networkctl`, `resolvectl`,
`sudo`, `ki2ctl`, 주요 systemd 유닛, 설치 계획서 보존 여부를 확인한다.

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

## HTTP 패키지 관리자

저장소 구성과 운영 절차는 [KIKI 패키지 저장소 구성 가이드](kiki-repository-setup.ko.md)에
별도로 정리한다. 이 절은 자주 쓰는 명령만 요약한다.

저장소 인덱스는 다음 명령으로 생성한다.

```bash
python tools/ki2build.py repo-index
```

개발 중에는 빌드 산출물 디렉터리를 그대로 HTTP로 열 수 있다.

```bash
python -m http.server 8080 --directory dist/ki2
```

운영용으로는 publish 트리를 만든 뒤 nginx, apache, caddy 같은 정적 HTTP 서버로
제공한다.

```bash
python tools/ki2publish.py --target /srv/www/kiki
```

KIKI OS 안에서는 `ki2ctl`로 원격 저장소를 등록하고 인덱스를 내려받는다.

```bash
ki2ctl repo set http://repo.example.internal:8080
ki2ctl update
ki2ctl search curl
ki2ctl info curl
ki2ctl install curl --dry-run
ki2ctl install curl
ki2ctl upgrade --dry-run
ki2ctl upgrade
ki2ctl list
```

Disconnected 설치나 ISO 내부 저장소 테스트에서는 HTTP 서버 없이 로컬 경로를
저장소로 등록할 수 있다. `ki2ctl`은 로컬 경로를 `file://` 저장소로 정규화한다.

```bash
ki2ctl repo set /run/install-media/kiki
ki2ctl update
ki2ctl install curl --dry-run

ki2ctl --repo file:///srv/kiki-mirror info systemd
ki2ctl repo remove
```

테스트 또는 설치 중 대상 rootfs에는 `--root`를 사용할 수 있다.

```bash
ki2ctl --root /mnt/target repo set http://repo.example.internal:8080
ki2ctl --root /mnt/target update
ki2ctl --root /mnt/target install openssh
```

현재 `ki2ctl`의 범위:

- HTTP 및 local/file repository index 다운로드
- 패키지 검색과 정보 조회
- 런타임 의존성 해석
- `.ki2` 다운로드와 sha256 검증
- `rootfs/` payload 추출
- `/var/lib/ki2/installed.json` 설치 기록
- 설치된 패키지와 저장소 최신 버전 비교 후 `upgrade`
- 설치 전 파일 충돌 탐지
- `/var/lib/ki2/transactions/` 트랜잭션 기록과 기본 rollback
- 설치 기록 기반 파일 제거
- `repo remove`로 저장소 설정과 캐시된 인덱스 제거

`ki2build rootfs`로 조립한 rootfs도 `/var/lib/ki2/installed.json`과
`/var/lib/ki2/installed.list`를 남긴다. Stage 2 CI는 이 rootfs 상태 DB를 사용해
CRI-O와 containerd Kubernetes 프로필이 설치 결과에서도 서로 섞이지 않는지 확인한다.

아직 남은 작업:

- 운영용 저장소 키 배포 정책
- 완전한 디렉터리 정리 rollback
- systemd unit enable/disable hook
- 패키지 pre/post install script 정책

## 쿠버네티스 노드 방향

Kubernetes 계열 프로필은 CRI-O를 기본값으로 두고, containerd 변형 프로필도 함께 둔다.

- `distro/profiles/kiki-kube-bootstrap.yaml`: 첫 control-plane 부트스트랩 노드
- `distro/profiles/kiki-kube-control.yaml`: 추가 control-plane 노드
- `distro/profiles/kiki-kube-compute.yaml`: compute 노드
- `distro/profiles/kiki-kube-bootstrap-containerd.yaml`: 첫 control-plane 부트스트랩 노드, containerd 런타임
- `distro/profiles/kiki-kube-control-containerd.yaml`: 추가 control-plane 노드, containerd 런타임
- `distro/profiles/kiki-kube-compute-containerd.yaml`: compute 노드, containerd 런타임

핵심 패키지:

- `cri-o`
- `conmon`
- `crun`
- `containerd`
- `runc`
- `cni-plugins`
- `cri-tools`
- `kubelet`
- `kubeadm`
- `kubectl`
- `firewalld`
- `bridge-utils`
- `kube-node-config`
- `kube-node-config-containerd`

`kube-node-config*` 패키지는 `/etc/kubernetes/kiki/` 아래에 kubeadm v1beta4
템플릿을 설치한다.

- `kubeadm-init.yaml`: 첫 bootstrap/control-plane 노드용 `kubeadm init`
- `kubeadm-join-control-plane.yaml`: 추가 control-plane 노드용 `kubeadm join`
- `kubeadm-join-compute.yaml`: compute 노드용 `kubeadm join`

쿠버네티스 노드에서도 기본 네트워크 관리는 `systemd-networkd`로 둔다. CNI는
pod network 영역을 담당하고, 호스트 기본 링크/DHCP/DNS는 systemd 계열로
단순하게 유지한다.

Kubernetes 노드 프로필의 추가 정책:

- cgroup driver는 `systemd`로 맞춘다.
- CRI 런타임은 `CRI-O`를 기본 목표로 하고, `containerd`는 Stage 2 선택 런타임으로 지원한다.
- 기본 swap은 off이다. kubelet swap 지원은 별도 실험 옵션으로만 켠다.
- 설치기는 Kubernetes 계열 프로필을 설치하기 직전에 필수 패키지 목록을 다시 확인한다.
  `kubelet`, `kubeadm`, `kubectl`, 선택한 CRI 런타임, CNI, firewall/bridge 도구가 미디어에 없으면
  설치를 중단한다.
- 커널은 bridge netfilter, nftables, iptables 호환, IPVS, veth, vxlan, overlayfs를 포함한다.
- userspace 네트워크 도구는 `nftables`, `iptables`, `conntrack-tools`, `socat`,
  `ethtool`을 우선 source-backed 패키지로 전환한다.
- `firewalld`와 `bridge-utils`를 Kubernetes 계열 프로필에 포함한다. 기본 bridge
  조작은 `iproute2`의 `bridge` 명령을 기준으로 한다.

## 코어 패키지와 OCI 확장 모델

Stage 1 이후 KIKI OS의 패키지 경계는 다음처럼 나눈다.

- `ki2`: OS 코어, 부팅, systemd, dbus, 로그인, 네트워크, sudo, ssh,
  `ki2ctl`, CRI-O/kubelet 같은 기반 패키지
- `CRI-O`: Kubernetes pod 실행 전용 CRI 런타임
- `Podman`: 사용자가 추가하는 운영 도구, 개발 도구, 관리 서비스, 확장 앱 실행
- 데스크톱 환경: GNOME 같은 전체 세션은 컨테이너가 아니라 `desktop-gnome`
  계열 ki2 프로파일로 제공
- GUI 앱: Podman/OCI app bundle 또는 향후 Flatpak 계열 모델로 분리

즉, “OS가 부팅하고 복구되는 데 필요한 것”은 ki2에 남기고, “사용자가 선택해서
추가하는 것”은 OCI 기반 확장으로 분리한다. 이렇게 하면 최소 서버 OS, Kubernetes
노드, 데스크톱 프로파일을 같은 코어 위에서 단계적으로 키울 수 있다.

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
- 공개키 기반 운영 저장소 서명
- 패키지 hook과 업그레이드 정책 고도화
- NetworkManager 선택 패키지
- 웹 기반 설치기
- 설치 계획서 기반 무인 설치 실행 경로 완성
- disconnected ISO 설치 검증 자동화
