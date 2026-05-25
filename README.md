# KIKI OS

**첫 부팅부터 Kubernetes 노드까지.**

KIKI OS는 새 VM 또는 베어메탈 머신을 Kubernetes 노드로 바꾸기 위한 자동화
OS입니다. ISO 또는 디스크 이미지로 부팅하면 네트워크 준비, 노드 프로필 적용,
CRI-O/kubelet 구성, 클러스터 조인, 상태 보고까지 이어지는 흐름을 목표로 합니다.

현재 저장소는 KIKI OS의 빌드 시스템, `.ki2` 패키지 포맷, 패키지 저장소, rootfs
조립, BIOS/UEFI 부팅 미디어, stage-1 TUI 설치기, 빌드 웹 콘솔을 함께 다룹니다.

## 저장소

- Gitea: <https://git.vlab.dustbox.kr/dustbox/kiki-os>
- GitHub: <https://github.com/ProjectKIKI/KIKI-OS>

## 현재 상태

KIKI OS는 아직 초기 개발 단계입니다. 목표는 범용 서버 설치 미디어가 아니라,
Kubernetes 노드 수명주기 자동화를 위한 재현 가능한 독립 배포판입니다.

- stage-1 installer가 있습니다.
- `.ki2 package -> repo -> rootfs -> boot media` 파이프라인이 있습니다.
- `minimal-systemd` 프로필로 systemd 기반 최소 서버 이미지를 구성합니다.
- `kiki-kube-node` 프로필은 Kubernetes worker node 부트스트랩 대상으로 모델링 중입니다.
- 기본 네트워크는 DHCP 기반 `systemd-networkd`와 `systemd-resolved`입니다.
- 기본 실험 계정은 `kiki / kiki`이며 root 직접 로그인은 잠급니다.
- `sudo`, `systemctl`, `dbus`, `systemd-logind`를 일반 운영 기본 기능으로 맞추고 있습니다.

## 첫 부팅 흐름

1. **부팅 이미지**: ISO 또는 디스크 이미지로 VM/베어메탈을 부팅합니다.
2. **네트워크 준비**: DHCP로 기본 네트워크를 확보합니다.
3. **프로필 적용**: OS 패키지, systemd unit, 런타임 설정을 재현 가능하게 적용합니다.
4. **런타임 시작**: CRI-O, CNI, systemd, kubelet 구성을 정리하고 서비스를 올립니다.
5. **클러스터 조인**: bootstrap 설정과 join token을 사용해 Kubernetes control plane에 등록합니다.
6. **상태 보고**: `kiki-agent`가 노드 상태와 heartbeat를 보고합니다.

## 구조

| 영역 | 역할 |
| --- | --- |
| 레시피 + 프로필 | `.ki2` 패키지와 OS 이미지를 재현 가능하게 만듭니다. |
| VM / 베어메탈 | 같은 부팅 미디어를 여러 환경에서 테스트하고 설치합니다. |
| TUI 설치기 | 디스크 파티셔닝, 패키지 선택, 사용자 생성, 네트워크 기본값을 적용합니다. |
| systemd 기반 런타임 | `dbus`, `logind`, `networkd`, `resolved`, `sshd`, `sudo`를 운영 기본값으로 구성합니다. |
| KIKI Agent | 첫 부팅 자동화, 노드 프로필 적용, 클러스터 조인, 상태 보고를 담당할 예정입니다. |

## 노드 프로필

| 프로필 | 상태 | 설명 |
| --- | --- | --- |
| `minimal-systemd` | 기본 | 최소 systemd 서버 OS를 만들기 위한 기본 프로필입니다. |
| `kiki-kube-node` | 모델링 중 | Kubernetes worker node 부트스트랩을 위한 핵심 프로필입니다. |
| `control-plane` | 예정 | control plane node 자동화를 위한 확장 프로필입니다. |
| `edge-node` | 예정 | 작은 VM, 원격 지점, edge 환경을 위한 경량 노드 프로필입니다. |
| `gpu-node` | 예정 | GPU 런타임과 device plugin 구성을 포함하는 계산 노드 프로필입니다. |
| `storage-node` | 예정 | 스토리지 워크로드와 노드 로컬 데이터 구성을 위한 프로필입니다. |

## 주요 도구

- `tools/ki2build.py`: `.ki2` 패키지 빌드, 의존성 계획, rootfs 조립
- `tools/ki2ci.py`: CLI 파이프라인과 빌드 웹 콘솔
- `tools/ki2iso.py`: rootfs와 패키지 저장소를 담는 payload ISO 생성
- `tools/ki2bootiso.py`: BIOS/UEFI 부팅 ISO, stage-1 TUI 설치 ISO 생성
- `tools/ki2publish.py`: 패키지, 저장소, ISO, 디스크 이미지를 정적 배포 트리로 복사
- `bosctl`, `cpmctl`, `bosbuild`: 초기 BOS/CPM 실험용 Go 도구

## 빠른 시작

프로필 검증:

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 64
python tools/ki2build.py validate --profile distro/profiles/minimal-systemd.toml --max-packages 64
```

빌드 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-node.yaml
```

rootfs 조립:

```bash
python tools/ki2build.py rootfs --profile distro/profiles/bootstrap-stage1.toml --rootfs-dir dist/rootfs/bootstrap-stage1
```

빌드 웹 콘솔:

```bash
python tools/ki2ci.py serve --host 127.0.0.1 --port 8090
```

컨테이너 기반 빌드 콘솔:

```bash
podman build -f deploy/container/Containerfile -t kiki-buildd:rocky9 .
podman run --rm -it -p 8090:8090 -v "$PWD:/work" -e KIKI_JOBS="$(nproc)" kiki-buildd:rocky9
```

설치 ISO 생성:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1 --mode installer
```

## TUI 설치기

설치기는 부팅 시 KIKI 로고를 출력하고 콘솔 TUI를 실행합니다. 현재 기능은 다음과
같습니다.

- `minimal-systemd` 기본 패키지 선택
- ISO에 포함된 전체 패키지 선택
- 저장소 인덱스에서 개별 패키지 이름 추가
- 자동 디스크 구성: ESP + swap + root
- 수동 디스크 구성: `fdisk` 또는 `cfdisk` 실행 후 ESP/root/swap 직접 입력
- 네트워크 기본값: `systemd-networkd` DHCP, interface match `en* eth*`
- 전체 디스크 대신 파티션 경로를 대상으로 입력하는 실수 차단
- 관리자 사용자 생성, root 직접 로그인 잠금 기본값
- `sudo` 그룹 정책 생성
- 기본 systemd 유닛 활성화
- UEFI fallback `BOOTX64.EFI` 설치
- 설치 전 선언형 YAML 설치 계획서 미리보기

설치 계획서는 설치 전 `/run/kiki/install-plan.yaml`에 생성되고, 패키지 설치 후
설치된 시스템의 `/var/lib/ki2/install-plan.yaml`에 보존됩니다. 비밀번호는 계획서에
저장하지 않고 런타임 입력값으로만 처리합니다.

## 개발 단계

KIKI OS는 stage 1부터 stage 3까지 진행합니다.

- **stage 1**: 부팅 가능한 설치 미디어와 최소 systemd OS를 검증합니다.
- **stage 2**: 운영 가능한 최소 서버 배포판, 패키지 업데이트, 무인 설치, disconnected 설치를 구현합니다.
- **stage 3**: 자기 빌드가 가능하고 Kubernetes/클러스터 운영을 자동화하는 독립 배포판으로 확장합니다.

자세한 기준은 [KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)를 따릅니다.

## Hyper-V 참고

생성된 미디어는 BIOS/MBR과 UEFI 부팅을 지원하지만 Secure Boot 서명은 아직 없습니다.
Hyper-V Generation 2에서 테스트할 때는 Secure Boot를 끕니다.

```powershell
Set-VMFirmware -VMName "test-kiki-os" -EnableSecureBoot Off
```

## 문서

- [KIKI OS 운영자 가이드](docs/kiki-os-guide.ko.md)
- [KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)
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
