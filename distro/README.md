# KIKI OS 배포판 빌드 시스템

`distro/`는 KIKI OS를 독립 배포판으로 만들기 위한 패키지, 프로파일, 설치
계획, 커널 설정, 템플릿을 담는 디렉터리다. 현재 목표는 완전한 자체 빌드가
아니라, 재현 가능한 초기 배포판 파이프라인을 만드는 것이다.

개발 단계는 `stage1-v1`, `stage2-v2`, 3단계로 관리한다. `stage1-v1`은
부팅과 설치 가능성 증명을 마친 최종 기준선이고, `stage2-v2`는 운영 가능한
최소 서버 배포판 기준선이다. 상세 기준은
`docs/kiki-os-stages.ko.md`, `docs/kiki-stage1-v1-final.ko.md`,
`docs/kiki-stage2-v2-progress.ko.md`에 둔다.

```text
레시피 -> 의존성 계획 -> 빌드 캐시 키 -> .ki2 패키지 -> 저장소 인덱스 -> 루트 파일시스템
레시피 -> ki2ci 파이프라인 -> 웹 작업 로그 -> 페이로드 ISO -> 부팅 ISO -> 설치 ISO
```

## 디렉터리 구조

```text
distro/
  recipes/core.toml              1단계 기본 seed 패키지 목록
  recipes/kubernetes.yaml        쿠버네티스 노드용 선택 패키지 계층
  specs/*.yaml                   패키지, 레시피, 프로파일, 설치 계획 스펙
  templates/*.yaml               새 패키지 레시피 작성용 템플릿
  profiles/bootstrap-stage1.toml pre-systemd 검증용 루트 파일시스템 프로파일
  profiles/installer-tui.toml    Go TUI 미리보기 단독 빌드 프로파일
  profiles/container-runtimes.toml CRI-O/containerd 2단계 런타임 검증 프로파일
  profiles/ki2ctl-runtime.toml   HTTP 패키지 관리자 단독 빌드 프로파일
  profiles/minimal-systemd.toml  기본 systemd 서버 노드 프로파일
  profiles/kiki-kube-bootstrap.yaml 첫 쿠버네티스 컨트롤 플레인 부트스트랩 프로파일
  profiles/kiki-kube-control.yaml 추가 쿠버네티스 컨트롤 플레인 프로파일
  profiles/kiki-kube-compute.yaml 쿠버네티스 컴퓨트 노드 지향 프로파일
  profiles/node-network-tools.toml nftables/firewalld/bridge 도구 검증 프로파일
  install-plans/*.yaml           설치기용 선언형 계획서 예제
  builders/rocky9-wsl-deps.sh    Rocky 9/WSL 빌더 의존성 설치 스크립트
  sources/                       copy/local 패키지용 소스 트리
```

관련 도구:

```text
tools/ki2build.py     패키지 빌드, 저장소 인덱스, 루트 파일시스템 조립
tools/ki2repo.py      저장소 인덱스, 운영 메타데이터, 채널 파일 생성
tools/ki2ci.py        CLI/웹 빌드 자동화 콘솔
tools/ki2iso.py       페이로드 ISO 생성
tools/ki2bootiso.py   VM 부팅 ISO와 1단계 설치 ISO 생성
tools/ki2publish.py   빌드 산출물 배포 트리 생성
cmd/kiki-installer-tui Go 기반 설치 계획서 TUI 미리보기
```

## 2단계 부트스트랩 패키지

`tools/ki2build.py`는 2단계 전용 `stage2-stub`와 `host-files` 빌드 타입을 지원한다.
`stage2-stub`는 아직 실제 페이로드가 없는 패키지 경로를 예약할 때만 쓰고,
`host-files`는 빌더 호스트에 설치된 검증용 실행 파일과 공유 라이브러리를 `.ki2`
페이로드로 묶는다. 2단계의 Kubernetes 경로는 실제 upstream 릴리스 바이너리 패키지와
host-files 부트스트랩 패키지가 섞여 있다.

현재 실제 upstream 릴리스 바이너리를 `.ki2` 페이로드에 넣는 항목:

- `runc`
- `containerd`
- `conmon`
- `crun`
- `cri-o`
- `cni-plugins`
- `cri-tools`
- `kubelet`
- `kubeadm`
- `kubectl`

현재 `host-files` 페이로드로 실제 명령을 넣는 항목:

- `conntrack-tools`
- `nftables`
- `iptables`
- `firewalld`
- `bridge-utils`
- `socat`
- `ethtool`
- `chrony`

이 계층은 2단계 VM 검증용 부트스트랩 패키징이다. 장기적으로는 3단계에서
소스 기반 빌드 또는 공식 릴리스 산출물 기반 패키지로 승격한다.

## YAML 운영 방침

KIKI OS의 운영자용 설정 포맷은 YAML로 둔다. 기존 seed 파일에는 TOML이 남아
있지만, 새 패키지 계층, 쿠버네티스 프로파일, 설치 계획서는 YAML을 우선 사용한다.

내장 YAML 파서는 의도적으로 작은 부분집합만 받는다.

- 매핑
- 목록
- 문자열
- 정수
- `true` / `false`
- `null`

버전, CIDR, 모호할 수 있는 값은 따옴표로 감싼다. 앵커, 별칭, 탭,
`yes/no/on/off` 같은 YAML 특수 해석값은 피한다.

## 기본 패키지 범위

기본 seed는 1단계 설치와 systemd 부팅 검증에 필요한 범위로 작게 유지한다.

- 커널과 ABI: `linux`, `linux-headers`, `glibc`
- systemd 런타임: `systemd`, `dbus`, `kmod`, `util-linux`, `cfdisk`,
  `ncurses`, `libcap`,
  `libseccomp`, `acl`, `attr`
- 셸과 유저랜드: `bash`, `busybox`, `coreutils`, `findutils`, `grep`,
  `sed`, `gawk`, `tar`, `gzip`, `xz`, `zstd`
- 네트워크와 원격 접속: `iproute2`, `openssl`, `ca-certificates`,
  `openssh`, `curl`
- 향후 자체 빌드 준비용 빌드 도구: `make`, `pkgconf`, `meson`,
  `ninja`, `python`, `perl`
- KIKI 통합: `base-files`, `ki2ctl`, `kiki-agent`, `kiki-installer-tui`

쿠버네티스 관련 패키지는 선택 YAML 계층으로 분리한다. 이렇게 해야
`minimal-systemd`는 작게 유지하고, `kiki-kube-compute`는 kubeadm 준비가 된 컴퓨트 노드로
확장할 수 있다. CRI 런타임은 CRI-O를 기본으로 두되,
`kiki-kube-compute-containerd`처럼 `*-containerd` 프로필로 containerd도 검증한다.
1단계부터 `kiki-installer-tui` 미리보기 패키지를 포함해 같은
설치 계획서를 Go 기반 TUI에서도 렌더링하고 테스트한다.

## 네트워크 정책

기본 OS와 쿠버네티스 노드의 네트워크 관리는 `systemd-networkd`와
`systemd-resolved`를 기준으로 한다.

선택 이유:

- systemd 기반 OS에 이미 포함되는 구성요소라 추가 패키지 부담이 작다.
- YAML/무인 설치에서 `.network` 파일만 생성하면 동작을 예측하기 쉽다.
- 서버, VM, 쿠버네티스 노드처럼 고정적이고 자동화된 환경에 적합하다.
- `networkctl`, `resolvectl`, journal 기반 진단 흐름이 단순하다.

`NetworkManager`는 추후 선택 패키지로 둔다. 데스크톱, Wi-Fi, VPN, 노트북,
복잡한 운영자 UI가 필요한 프로파일에서는 `NetworkManager`가 더 좋다. 다만
현재 KIKI의 첫 목표는 서버/클러스터 노드이므로 기본값은 `systemd-networkd`다.

방화벽과 브리지 도구는 다음 순서로 확장한다.

- 기본 bridge 조작: `iproute2`의 `bridge` 명령
- Kubernetes/CNI 필수 계층: `nftables`, `iptables`, `conntrack-tools`
- 선택 운영 계층: `firewalld`, `bridge-utils`
- 검증 프로파일: `distro/profiles/node-network-tools.toml`

## 기본 명령

카탈로그 검증:

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 72
```

기본 systemd 이미지 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
```

쿠버네티스 노드 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute.yaml
```

빌드 의존성까지 포함한 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/world.toml --include-build-deps
```

dry-run 빌드:

```bash
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --dry-run
```

패키지 빌드:

```bash
python tools/ki2build.py build \
  --profile distro/profiles/minimal-systemd.toml \
  --toolchain-id x86_64-linux-gnu-v1
```

저장소 인덱스 생성:

```bash
python tools/ki2build.py repo-index
```

루트 파일시스템 조립:

```bash
python tools/ki2build.py rootfs \
  --profile distro/profiles/minimal-systemd.toml \
  --rootfs-dir dist/rootfs/minimal-systemd
```

1단계 루트 파일시스템 조립:

```bash
python tools/ki2build.py rootfs \
  --profile distro/profiles/bootstrap-stage1.toml \
  --rootfs-dir dist/rootfs/bootstrap-stage1
```

## 빌드 캐시 모델

각 패키지 빌드 키는 다음 값으로 계산한다.

- 정규화된 레시피 내용
- 아키텍처
- 도구체인 ID
- 의존 패키지의 빌드 키

저장된 빌드 상태와 패키지 산출물이 일치하면 해당 패키지는 다시 컴파일하지
않는다. 이것이 매번 모든 패키지를 다시 빌드하지 않기 위한 첫 번째 장치다.

`.ki2` 패키지 매니페스트와 저장소 인덱스에는 빌드/런타임 의존성 정보가 함께
들어간다. `ki2ctl install`은 이 정보를 사용해 런타임 의존성을 풀고 HTTP
저장소에서 필요한 `.ki2` 패키지를 내려받는다.

## 패키지 형식

패키지 계약은 `distro/specs/ki2-package-v1.yaml`에 있다. `.ki2`는 gzip tar
아카이브이며 최상위 구조는 다음과 같다.

```text
manifest.json
rootfs/
```

`rootfs/` 아래 경로는 설치 대상 OS의 절대 경로가 된다. 예를 들어
`rootfs/usr/lib/systemd/system/crio.service`는 설치 후
`/usr/lib/systemd/system/crio.service`가 된다.

패키지가 소유할 수 있는 영역:

- `/etc`
- `/usr`
- `/boot`
- `/lib`
- `/lib64`
- `/opt`
- `/var`
- systemd 유닛 디렉터리

패키지에 넣지 않는 영역:

- `/dev`
- `/proc`
- `/sys`
- `/run`
- `/tmp`

이런 런타임 pseudo filesystem은 init 또는 systemd가 부팅 중 만든다.

## 패키지 작성 흐름

소스 빌드 패키지:

```bash
cp distro/templates/package.yaml distro/recipes/my-package.yaml
```

OS 설정 패키지:

```bash
cp distro/templates/local-os-package.yaml distro/recipes/my-os-config.yaml
mkdir -p distro/sources/my-os-config
```

검증과 빌드:

```bash
python tools/ki2build.py validate --profile distro/profiles/kiki-kube-compute.yaml --max-packages 64
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute.yaml
python tools/ki2build.py build --profile distro/profiles/kiki-kube-compute.yaml --allow-unpinned
python tools/ki2build.py repo-index
```

## 빌드 자동화 콘솔

사람이 ISO 빌드 전에 현재 상태를 확인하고 Stage 3 검증·계획·빌드를 관리할 때는
통합 콘솔을 사용한다. 인자 없이 실행하면 대화형 셸이 열리며, ISO 생성은 별도
승인이 필요하다.

```bash
python3 tools/kiki_console.py
python3 tools/kiki_console.py doctor --iso
python3 tools/kiki_console.py plan --iso
python3 tools/kiki_console.py iso --dry-run --yes
```

상세 사용법은 `docs/kiki-management-console.ko.md`에 정리되어 있다.

`tools/ki2ci.py`는 빌드 서버 엔트리포인트다. 기본 작업 메타데이터와 로그는
`build/ki2ci/` 아래에 저장한다.

파이프라인:

- `smoke`: 빠른 Go/Python/레시피 검증
- `bootstrap`: pre-systemd 패키지, 저장소, 루트 파일시스템 빌드
- `minimal-systemd`: systemd 기반 기본 프로파일 빌드
- `stage2`: ISO 없이 2단계 저장소 메타데이터, CRI-O/containerd Kubernetes 계획, Go TUI 렌더링 검증
- `security`: 소스 고정, 셸 문법, 선택 스캐너 확인
- `iso`: 부트스트랩 루트 파일시스템과 저장소를 페이로드 ISO로 패키징
- `bootiso`: KIKI 커널과 initramfs를 포함한 GRUB 부팅 ISO 생성
- `installer-iso`: KIKI 로고와 1단계 TUI 설치기 ISO 생성
- `publish`: 저장소, 패키지, ISO 산출물을 정적 배포 트리로 복사
- `release`: smoke부터 배포까지 묶음 실행

CLI 실행:

```bash
python tools/ki2ci.py run smoke
python tools/ki2stage2.py verify-kubernetes
python tools/ki2ci.py run stage2
python tools/ki2ci.py run bootstrap --jobs "$(nproc)" --toolchain-id rocky9-stage0-gcc11-v1
python tools/ki2ci.py run publish --publish-dir /srv/www/kiki
```

운영용 2단계 완료 여부는 `python tools/ki2ci.py run stage2` 통과 여부로 확인한다.
이 파이프라인은 `verify-kubernetes --strict-production`, `verify-network-userspace
--strict-production`, CRI-O/containerd 루트 파일시스템 검증, Go TUI 설치 계획서 계약 검증,
저장소 서명 검증을 함께 수행한다.

## HTTP 패키지 저장소

상세한 저장소 구성 방법은 `docs/kiki-repository-setup.ko.md`를 따른다.

저장소 인덱스는 별도 명령으로 생성한다.

```bash
python tools/ki2build.py repo-index
```

빌드 디렉터리를 바로 정적 HTTP 서버로 제공할 수 있다.

```bash
python -m http.server 8080 --directory dist/ki2
```

또는 배포 트리를 만든 뒤 nginx 같은 웹 서버로 제공한다.

```bash
python tools/ki2publish.py --target /srv/www/kiki
```

대상 시스템에서는 `ki2ctl`을 사용한다.

```bash
ki2ctl repo set http://SERVER:8080
ki2ctl update
ki2ctl search systemd
ki2ctl info systemd
ki2ctl install systemd --dry-run
ki2ctl install systemd
ki2ctl list
```

`ki2ctl`은 다음 HTTP 경로를 지원한다.

```text
repo/index.x86_64.json
packages/<package>.ki2
packages/x86_64/<package>.ki2
```

설치 대상 루트 파일시스템을 따로 지정해서 테스트할 수도 있다.

```bash
ki2ctl --root /mnt/target repo set http://SERVER:8080
ki2ctl --root /mnt/target update
ki2ctl --root /mnt/target install curl
```

웹 콘솔 실행:

```bash
python tools/ki2ci.py serve --host 127.0.0.1 --port 8090
```

웹 콘솔에는 자체 인증이 없다. 실제 빌드 서버에서는 localhost, VPN, 또는 인증
리버스 프록시 뒤에서만 노출한다.

## 컨테이너 빌더

`deploy/container/`는 Rocky 9 기반 빌드 컨테이너를 제공한다.

```bash
podman build -f deploy/container/Containerfile -t kiki-buildd:rocky9 .
podman run --rm -it -p 8090:8090 -v "$PWD:/work" kiki-buildd:rocky9
```

저장소는 컨테이너 내부 `/work`에 마운트되며, 산출물은 호스트의 `build/`와
`dist/`로 기록된다.

## ISO와 설치기

페이로드 ISO:

```bash
python tools/ki2iso.py --profile bootstrap-stage1
```

부팅 테스트 ISO:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1
```

설치기 ISO:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1 --mode installer
```

Stage 3 설치 ISO는 KIKI 로고와 GTK 4 GUI, 전체 화면 TUI, Stage-1 CLI를
제공한다. 기본 부팅 순서는 GUI → TUI → CLI이며, 앞 단계가 실행되지 않거나
종료되면 다음 단계로 폴백한다. 모든 프런트엔드는 동일한 선언형 설치 계획서를
사용한다. 설치기는 패키지 선택, 자동/수동 파티셔닝, 사용자 생성, systemd 유닛
활성화, UEFI 대체 부트 파일 설치를 수행한다. GTK에서 설치를 시작하면 단계별
진행률, 완료/전체 패키지 개수와 현재 패키지를 표시하고, 완료 화면에서 사용자가 확인한 경우에만
재부팅한다.

GTK 화면은 Xorg가 아니라 Cage/Wayland와 DRM/KMS를 사용한다. Hyper-V 커널은
`CONFIG_DRM_HYPERV=y`, `CONFIG_DRM_FBDEV_EMULATION=y`를 활성화하고 충돌하는
`CONFIG_FB_HYPERV`를 비활성화해야 한다. ISO 생성 시에는 서명 저장소의 최신
`linux-*.ki2` 패키지를 rootfs에 남은 커널보다 우선한다. 가속 렌더 노드가 없는
Hyper-V 출력은 `WLR_RENDERER=pixman`과 DRM dumb buffer를 사용한다.

네트워크 기본값은 `systemd-networkd` DHCP다. 설치기는 기본적으로 `en* eth*`
인터페이스에 DHCPv4, IPv6 RA, `systemd-resolved`를 설정한다. Guided 설치에서는
네트워크 자동 구성을 끄거나 인터페이스 일치 조건 값을 바꿀 수 있다.

설치 전에는 선언형 YAML 설치 계획서를 `/run/kiki/install-plan.yaml`에 쓰고
화면에 보여준다. 설치 후에는 같은 파일을 `/var/lib/ki2/install-plan.yaml`로
복사한다. 이 계획서는 추후 웹 기반 설치기와 무인 설치의 공통 계약으로 사용할
수 있다.

1단계 fstab은 systemd 장치 이름 변경에 덜 민감하도록 label 기반으로 작성한다.

```fstab
LABEL=KIKI_ROOT / ext4 defaults 0 1
LABEL=KIKI_EFI /boot/efi vfat noauto,nofail,x-systemd.device-timeout=3s,umask=0077 0 0
LABEL=KIKI_SWAP none swap defaults,nofail,x-systemd.device-timeout=10s 0 0
```

Go TUI 미리보기는 같은 설치 계획서를 상태판으로 렌더링한다.

```bash
go run ./cmd/kiki-installer-tui --render
go run ./cmd/kiki-installer-tui --profile kiki-kube-compute --render
```

현재 설치된 시스템에서 활성화하는 기본 유닛:

```text
dbus.service
getty@tty1.service
systemd-logind.service
systemd-networkd.service
systemd-resolved.service
sshd.service
kiki-agent.service
```

## 현재 빌드 상태

Rocky 9 WSL 빌더에서 pre-systemd 단계 패키지 저장소와 `bootstrap-stage1`
루트 파일시스템이 검증되어 있다.

- 패키지 산출물: `dist/ki2/packages/x86_64`
- 저장소 인덱스: `dist/ki2/repo/index.x86_64.json`
- 검증된 루트 파일시스템 프로파일: `distro/profiles/bootstrap-stage1.toml`

`systemd`는 configure와 컴파일 단계까지 진행되지만, 현재는 KIKI sysroot
헤더와 호스트 libc를 섞어 쓰는 부트스트랩 경계가 있다. 다음 단계는 실제 대상
sysroot 도구체인을 구성해 헤더와 libc를 같은 세계로 맞추는 것이다.

Rocky 9 WSL 의존성 설치:

```bash
bash distro/builders/rocky9-wsl-deps.sh
```

## 소스 pin 정책

일부 upstream source hash는 아직 `TODO`다. 실제 빌드는 기본적으로 unpinned
source를 거부하며, 실험할 때만 `--allow-unpinned`를 사용한다.

권장 흐름:

```text
upstream source 다운로드
수동 검증
sha256을 레시피에 기록
레시피 hash 변경 커밋
패키지 빌드
```
