# KIKI OS

**첫 부팅부터 쿠버네티스 노드까지.**

KIKI OS는 새 VM 또는 베어메탈 머신을 쿠버네티스 노드로 바꾸기 위한 자동화
OS입니다. ISO 또는 디스크 이미지로 부팅하면 네트워크 준비, 노드 프로필 적용, CRI-O 또는 containerd 기반 kubelet 구성, 클러스터 조인, 상태 보고까지 이어지는 흐름을 목표로 합니다.

현재 저장소는 KIKI OS의 빌드 시스템, `.ki2` 패키지 형식, 패키지 저장소, 루트, 파일시스템 조립, BIOS/UEFI 부팅 미디어, 1단계 TUI 설치기, 빌드 웹 콘솔을 함께 다룹니다.

**제작자**
최국현<tang@dustbox.kr>

**지원자(Thanks for)**
안현, 장경빈

## 개발 환경 및 진행 상황

현재 개발 환경은 WSL2입니다. 최대한 크로스 컴파일을 배제하고 네이티브 패키지를 지향하면서 패키지와 운영체제를 구성하고 있습니다. 현재 진행 상황은 다음과 같습니다.

- [x] 기본 부팅 경로
- [x] systemd로 PID 1을 넘기는 단순 init 경로
- [X] systemd-initramfs 구현
- [X] 원격 패키지 저장소 HTTP/HTTPS 구현
- [ ] 엑스 윈도우 구성
- [ ] AI 및 LLM 서비스 통합
- [ ] 엑스 윈도우 서버 관리자 도구


## 저장소

- 개발자 Gitea: <https://git.vlab.dustbox.kr/dustbox/kiki-os>
- 개발자 공개 GitHub: <https://github.com/ProjectKIKI/KIKI-OS>

## 현재 상태

KIKI OS는 아직 초기 개발 단계입니다. 목표는 범용 서버 설치 미디어가 아니라, 쿠버네티스 노드 수명주기 자동화를 위한 재현 가능한 독립 배포판입니다.

- 1단계 설치기가 있습니다.
- `.ki2 패키지 -> 저장소 -> 루트 파일시스템 -> 부팅 미디어` 파이프라인이 있습니다.
- `minimal-systemd` 프로필로 systemd 기반 최소 서버 이미지를 구성합니다.
- 쿠버네티스 역할 프로필은 `kiki-kube-bootstrap`, `kiki-kube-control`, `kiki-kube-compute`로 모델링 중입니다.
- 코어 OS는 `ki2`로 유지하고, 사용자 확장 앱과 운영 도구는 2단계 이후
  Podman/OCI 모델로 분리합니다. CRI-O는 쿠버네티스 전용 런타임으로 둡니다.
- 기본 네트워크는 DHCP 기반 `systemd-networkd`와 `systemd-resolved`이며, 설치 시 고정 IPv4도 선택할 수 있습니다.
- 기본 실험 계정은 `kiki / kiki`이며 root 직접 로그인은 잠급니다.
- `sudo`, `systemctl`, `dbus`, `systemd-logind`를 일반 운영 기본 기능으로 맞추고 있습니다.
- 콘솔 기본값은 ANSI 색상, `less -R`, systemd 색상 활성화, systemd URL 하이퍼링크 비활성화를 적용합니다.
- 1단계부터 Go 기반 `kiki-installer-tui` 미리보기를 포함해 설치 계획서 TUI를 테스트합니다.

## 첫 부팅 흐름

1. **부팅 이미지**: ISO 또는 디스크 이미지로 VM/베어메탈을 부팅합니다.
2. **네트워크 준비**: DHCP 또는 고정 IPv4로 기본 네트워크를 확보합니다.
3. **프로필 적용**: OS 패키지, systemd 유닛, 런타임 설정을 재현 가능하게 적용합니다.
4. **런타임 시작**: CRI-O/containerd, CNI, systemd, kubelet 구성을 정리하고 서비스를 올립니다.
5. **클러스터 조인**: 부트스트랩 설정과 조인 토큰을 사용해 쿠버네티스 컨트롤 플레인에 등록합니다.
6. **상태 보고**: `kiki-agent`가 노드 상태와 하트비트를 보고합니다.

## 구조

| 영역 | 역할 |
| --- | --- |
| 레시피 + 프로필 | `.ki2` 패키지와 OS 이미지를 재현 가능하게 만듭니다. |
| VM / 베어메탈 | 같은 부팅 미디어를 여러 환경에서 테스트하고 설치합니다. |
| TUI 설치기 | 디스크 파티셔닝, 패키지 선택, 사용자 생성, 네트워크 기본값을 적용합니다. |
| CLI/TUI/GTK 설치 화면 | 지역화, 디스크, 네트워크, 소스 신뢰, 프로필, 런타임과 AI 설정을 하나의 InstallPlan으로 작성하고 GTK에서 설치 진행·완료 확인·재부팅까지 처리합니다. |
| systemd 기반 런타임 | `dbus`, `logind`, `networkd`, `resolved`, `sshd`, `sudo`를 운영 기본값으로 구성합니다. |
| Go TUI 미리보기 | 선언형 설치 계획서를 상태판 형태로 렌더링하고 2단계 설치기 전환을 검증합니다. |
| KIKI 에이전트 | 첫 부팅 자동화, 노드 프로필 적용, 클러스터 조인, 상태 보고를 담당할 예정입니다. |

## 노드 프로필

| 프로필 | 상태 | 설명 |
| --- | --- | --- |
| `minimal-systemd` | 기본 | 최소 systemd 서버 OS를 만들기 위한 기본 프로필입니다. |
| `server-core` | 3단계 초안 | 쿠버네티스 없이 일반 서버 OS 기능, 방화벽, 시간 동기화, 네트워크 도구를 제공하는 프로필입니다. |
| `kiki-kube-bootstrap` | 2단계 검증 | 첫 쿠버네티스 컨트롤 플레인을 kubeadm init 대상으로 준비하는 프로필입니다. |
| `kiki-kube-bootstrap-containerd` | 2단계 검증 | 첫 컨트롤 플레인을 containerd 런타임으로 준비하는 프로필입니다. |
| `kiki-kube-control` | 2단계 검증 | 부트스트랩 이후 추가 컨트롤 플레인 노드를 준비하는 프로필입니다. |
| `kiki-kube-control-containerd` | 2단계 검증 | 추가 컨트롤 플레인을 containerd 런타임으로 준비하는 프로필입니다. |
| `kiki-kube-compute` | 2단계 검증 | 쿠버네티스 컴퓨트 노드 부트스트랩을 위한 프로필입니다. |
| `kiki-kube-compute-containerd` | 2단계 검증 | 쿠버네티스 컴퓨트 노드를 containerd 런타임으로 준비하는 프로필입니다. |
| `edge-node` | 예정 | 작은 VM과 원격 지점을 위한 경량 노드 프로필입니다. |
| `gpu-node` | 예정 | GPU 런타임과 장치 플러그인 구성을 포함하는 계산 노드 프로필입니다. |
| `storage-node` | 예정 | 스토리지 워크로드와 노드 로컬 데이터 구성을 위한 프로필입니다. |

## 주요 도구

- `tools/kiki_console.py`: ISO 사전 상태·검증·빌드를 통합한 대화형 관리 콘솔
- `cmd/kiki-ai-console`: 설치 후 `tty1`에서 명령 확인을 거치는 한국어 AI 관리 콘솔 (`tty2`는 독립 복구 셸)
- `tools/ki2build.py`: `.ki2` 패키지 빌드, 의존성 계획, 루트 파일시스템 조립
- `tools/ki2repo.py`: HTTP 패키지 저장소 인덱스, 메타데이터, 채널 파일 생성
- `tools/ki2ci.py`: 명령줄 파이프라인과 빌드 웹 콘솔
- `tools/ki2iso.py`: 루트 파일시스템과 패키지 저장소를 담는 페이로드 ISO 생성
- `tools/ki2bootiso.py`: BIOS/UEFI 부팅 ISO, 1단계 TUI 설치 ISO 생성
- `tools/ki2publish.py`: 패키지, 저장소, ISO, 디스크 이미지를 정적 배포 트리로 복사
- `cmd/kiki-installer-tui`: Go 기반 선언형 설치 계획서 TUI
- `cmd/kiki-installer-gtk`: 같은 InstallPlan 생성기를 호출하는 GTK 4 설치 GUI
- `bosctl`, `cpmctl`, `bosbuild`: 초기 BOS/CPM 실험용 Go 도구

## 주요 문서

- [KIKI OS 운영자 가이드](docs/kiki-os-guide.ko.md)
- [KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)
- [KIKI OS 1단계 V1 최종 문서](docs/kiki-stage1-v1-final.ko.md)
- [KIKI OS 2단계 V2 완료 문서](docs/kiki-stage2-v2-progress.ko.md)
- [KIKI OS 3단계 V3 전환 계획](docs/kiki-stage3-v3-plan.ko.md)
- [KIKI OS 3단계 V3 초안](docs/kiki-stage3-v3-draft.ko.md)
- [KIKI OS 관리 콘솔](docs/kiki-management-console.ko.md)
- [KIKI OS 인스톨러 구성 및 동작](docs/kiki-installer.ko.md)
- [KIKI OS CLI/TUI/GTK 설치 프런트엔드](docs/kiki-installer-frontends.ko.md)
- [KIKI OS 온디바이스 AI 관리 콘솔](docs/kiki-ai-console.ko.md)
- [KIKI OS 홈페이지 콘텐츠 기준](docs/kiki-homepage-content.ko.md)
- [KIKI OS 네트워크 설정 도구](docs/kiki-network-config.ko.md)
- [KIKI 패키지 저장소 구성 가이드](docs/kiki-repository-setup.ko.md)
- [KIKI OS 2단계 상세 작업 메모](docs/kiki-stage2-plan.ko.md)

## 빠른 시작

ISO 사전 관리 콘솔:

```bash
python3 tools/kiki_console.py status
python3 tools/kiki_console.py doctor
python3 tools/kiki_console.py plan
python3 tools/kiki_console.py build --dry-run
```

프로필 검증:

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 72
python tools/ki2build.py validate --profile distro/profiles/minimal-systemd.toml --max-packages 64
```

빌드 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute-containerd.yaml
```

선택 패키지만 다시 빌드:

```bash
python tools/ki2build.py build --profile distro/profiles/kiki-kube-compute-containerd.yaml --only runc containerd cni-plugins cri-tools kubelet kubectl kubeadm
```

루트 파일시스템 조립:

```bash
python tools/ki2build.py rootfs --profile distro/profiles/bootstrap-stage1.toml --rootfs-dir dist/rootfs/bootstrap-stage1
```

패키지 저장소 인덱스 생성:

```bash
python tools/ki2build.py repo-index
python tools/ki2repo.py keygen --output build/ki2/keys/stage2-v2-repo.hmac --force
python tools/ki2repo.py generate --channel stage2-v2 --sign-key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2repo.py verify --key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2stage2.py verify-kubernetes --require-signed-metadata
python tools/ki2stage2.py verify-binary-smoke
python tools/ki2stage2.py verify-package-manager
python tools/ki2stage2.py verify-installed-rootfs --root /mnt/target --runtime containerd
```

빌드 웹 콘솔:

```bash
python tools/ki2ci.py run smoke
python tools/ki2ci.py run stage2
python tools/ki2ci.py serve --host 127.0.0.1 --port 8090
```

`stage2` 파이프라인은 ISO를 만들지 않고 Go/Python 테스트, CRI-O/containerd
쿠버네티스 프로필 계획, Go TUI 계획서 작성과 계약 검증, kubeadm init/join 계약이 포함된
2단계 쿠버네티스 준비도, 런타임/쿠버네티스 바이너리 스모크, kubeadm 템플릿
파싱, CRI-O/containerd 설치 루트 파일시스템 검증, 서명된 저장소 메타데이터 생성과 검증을
묶어 확인한다. 바이너리 스모크와 루트 파일시스템 검증은 Linux/WSL 빌더에서 실행해야 한다.

컨테이너 기반 빌드 콘솔:

```bash
podman build -f deploy/container/Containerfile -t kiki-buildd:rocky9 .
podman run --rm -it -p 8090:8090 -v "$PWD:/work" -e KIKI_JOBS="$(nproc)" kiki-buildd:rocky9
```

Stage 3 GUI/TUI/CLI 설치 ISO 생성:

```bash
python3 tools/ki2bootiso.py \
  --profile server-core \
  --mode installer
```

`--output`을 지정하지 않으면 ISO 파일명은 저장소 채널, 날짜, Git 리비전 수를
포함한다. Stage 3 설치 ISO의 기본 부팅 순서는 GTK GUI → 전체 화면 TUI →
Stage-1 CLI다. GUI 또는 TUI가 시작되지 않으면 다음 단계로 자동 전환하며,
GRUB에서 원하는 프런트엔드를 직접 선택할 수도 있다.

HTTP 패키지 저장소 테스트:

```bash
python tools/ki2build.py repo-index
python -m http.server 8080 --directory dist/ki2
ki2ctl repo set http://SERVER:8080
ki2ctl update
ki2ctl search curl
ki2ctl install curl --dry-run
```

오프라인/로컬 미러 테스트:

```bash
ki2ctl repo set /run/install-media/kiki
ki2ctl update
ki2ctl --repo file:///srv/kiki-mirror info systemd
ki2ctl repo remove
```

Go TUI:

```bash
go test ./cmd/kiki-installer-tui
go run ./cmd/kiki-installer-tui --render
go run ./cmd/kiki-installer-tui --profile kiki-kube-compute --render
go run ./cmd/kiki-installer-tui --write --plan ./install-plan.yaml
python tools/ki2stage2.py verify-install-plan --plan ./install-plan.yaml --runtime cri-o --role compute
```

## 설치 프런트엔드

설치기는 GTK 4 GUI, 전체 화면 TUI, 안전 CLI와 무인 설치가 동일한
`kiki-install-plan-v1` 계약을 사용합니다. 현재 기능은 다음과 같습니다.

- `minimal-systemd` 기본 패키지 선택
- `kiki-kube-bootstrap`, `kiki-kube-control`, `kiki-kube-compute` 쿠버네티스 역할별 패키지 세트 선택
- ISO에 포함된 전체 패키지 선택
- 저장소 인덱스의 패키지 레코드 수와 고유 패키지 이름 수 구분 표시
- 저장소 인덱스에서 개별 패키지 이름 추가
- 자동 디스크 구성: ESP + swap + root
- 수동 디스크 구성: TUI의 Disk 메뉴에서 `cfdisk`/`fdisk` 실행 후
  ESP/root/swap 후보를 설치 단계 기본값으로 사용
- `cfdisk`는 별도 편의 패키지로 제공하며, 실제 바이너리는
  `util-linux`, TUI 라이브러리는 `ncurses` 패키지가 담당합니다.
- fstab 안정화: `LABEL=KIKI_ROOT`, `LABEL=KIKI_EFI`, `LABEL=KIKI_SWAP` 기반 mount/swap
- 네트워크 기본값: `systemd-networkd` DHCP, 인터페이스 일치 조건 `en* eth*`, 선택 시 고정 IPv4
- 전체 디스크 대신 파티션 경로를 대상으로 입력하는 실수 차단
- 관리자 사용자 생성, root 직접 로그인 잠금 기본값
- `sudo` 그룹 정책 생성
- 기본 systemd 유닛 활성화
- UEFI 대체 부팅 경로 `BOOTX64.EFI` 설치
- 설치 전 선언형 YAML 설치 계획서 미리보기

GTK GUI는 Cage/Wayland 키오스크로 실행되며 Xorg를 요구하지 않습니다. 전체 화면
TUI에서는 방향키 또는 j/k로 이동하고 Enter로 항목을 선택하며, `:` 키로 프로필과
패키지 그룹을 포함한 세부 설정 명령을 입력합니다. 자세한 실행 및 폴백 규칙은
[설치 프런트엔드 문서](docs/kiki-installer-frontends.ko.md)를 참고합니다.

설치 계획서는 설치 전 `/run/kiki/install-plan.yaml`에 생성되고, 패키지 설치 후
설치된 시스템의 `/var/lib/ki2/install-plan.yaml`에 보존됩니다. 비밀번호는 계획서에
저장하지 않고 런타임 입력값으로만 처리합니다.

## 개발 단계

KIKI OS는 1단계부터 3단계까지 진행합니다.

- **1단계 V1**: 부팅 가능한 설치 미디어와 최소 systemd OS를 검증한 최종 기준선입니다.
- **2단계 V2**: 운영 가능한 최소 서버 배포판, 패키지 설치/업데이트 기반, 무인 설치, 오프라인 설치를 검증한 기준선입니다.
- **3단계 V3**: 자체 빌드가 가능하고 쿠버네티스/클러스터 운영을 자동화하는 독립 배포판으로 확장합니다.

자세한 기준은 [KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)를 따릅니다.

## Hyper-V 참고

생성된 미디어는 BIOS/MBR과 UEFI 부팅을 지원하지만 보안 부팅 서명은 아직 없습니다.
Hyper-V 2세대 가상 머신에서 테스트할 때는 보안 부팅을 끕니다.

```powershell
Set-VMFirmware -VMName "test-kiki-os" -EnableSecureBoot Off
```

그래픽 설치기는 Xorg가 아니라 `hyperv_drm`의 DRM/KMS 장치를 직접 사용합니다.
커널은 `CONFIG_DRM_HYPERV=y`, `CONFIG_DRM_FBDEV_EMULATION=y`,
`# CONFIG_FB_HYPERV is not set` 조합이어야 합니다. `hyperv_fb`와
`hyperv_drm`을 동시에 활성화하면 같은 합성 비디오 장치를 선점해 Cage가
`Found 0 GPUs`로 실패할 수 있습니다.

## 문서

- [KIKI OS 운영자 가이드](docs/kiki-os-guide.ko.md)
- [KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)
- [KIKI OS 1단계 V1 최종 문서](docs/kiki-stage1-v1-final.ko.md)
- [KIKI OS 2단계 V2 완료 문서](docs/kiki-stage2-v2-progress.ko.md)
- [KIKI OS 3단계 V3 전환 계획](docs/kiki-stage3-v3-plan.ko.md)
- [KIKI OS 3단계 V3 초안](docs/kiki-stage3-v3-draft.ko.md)
- [KIKI OS 홈페이지 콘텐츠 기준](docs/kiki-homepage-content.ko.md)
- [KIKI OS 네트워크 설정 도구](docs/kiki-network-config.ko.md)
- [배포판 빌드 시스템 문서](distro/README.md)
- [빌드 시스템 검토](distro/BUILD-SYSTEM-REVIEW.md)
- [컨테이너 빌더 문서](deploy/container/README.md)
- [ki2 패키지 스펙](distro/specs/ki2-package-v1.yaml)
- [ki2 레시피 스펙](distro/specs/ki2-recipe-v1.yaml)
- [ki2 프로파일 스펙](distro/specs/ki2-profile-v1.yaml)
- [KIKI 설치 계획서 스펙](distro/specs/kiki-install-plan-v1.yaml)

## 기존 BOS/CPM 실험 도구

초기 Go 도구는 아직 남겨두었습니다. `bosctl`은 로컬 BOS 패키지 DB와 저장소
인덱스를 다루고, `cpmctl`은 컨테이너 패키지 DB를 다루며, `bosbuild`는
`manifest.yaml`, `rootfs/`, `scripts/`를 포함한 `.bos` 아카이브를 만듭니다.

```bash
go mod tidy
go build -o bosctl ./cmd/bosctl
go build -o cpmctl ./cmd/cpmctl
go build -o bosbuild ./cmd/bosbuild
go test ./cmd/... ./internal/...
```

앞으로의 배포판 패키징 중심 이름은 `ki2`이며, BOS/CPM은 과거 실험과 호환 검토용
코드로 취급합니다.
