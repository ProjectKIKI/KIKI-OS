# KIKI OS 패키징 및 배포판 빌드 시스템 v0.0.3

이 저장소는 KIKI OS 독립 배포판을 만들기 위한 초기 빌드 시스템이다.
기존 Go 기반 `bosctl`, `cpmctl`, `bosbuild` 실험 코드와 함께, 현재 개발
중심은 `ki2` 패키지 빌드, 저장소 생성, rootfs 조립, ISO/부팅 미디어,
TUI 설치기, 빌드 웹 콘솔이다.

## 주요 도구

- `tools/ki2build.py`: `.ki2` 패키지 빌드, 의존성 계획, rootfs 조립
- `tools/ki2ci.py`: CLI 파이프라인과 빌드 웹 콘솔
- `tools/ki2iso.py`: rootfs와 패키지 저장소를 담는 payload ISO 생성
- `tools/ki2bootiso.py`: BIOS/UEFI 부팅 ISO, stage-1 TUI 설치 ISO 생성
- `tools/ki2publish.py`: 패키지, 저장소, ISO, 디스크 이미지를 정적 배포 트리로 복사
- `bosctl`, `cpmctl`, `bosbuild`: 초기 BOS/CPM 실험용 Go 도구

## 현재 방향

KIKI OS의 기본 운영체제는 `systemd`, `glibc`, `dbus`, `shadow`, `openssh`,
`systemd-networkd`, `systemd-resolved`를 기반으로 한다. 서버, 쿠버네티스
노드, 무인 설치, disconnected 설치를 우선 목표로 하므로 기본 네트워크는
`systemd-networkd`로 둔다.

`NetworkManager`는 데스크톱, Wi-Fi, VPN, 복잡한 운영자 인터페이스가 필요할
때 선택 패키지 또는 별도 프로파일로 추가하는 방향이 맞다. 최소 배포판과
쿠버네티스 노드 프로파일에는 `systemd-networkd`가 더 작고 자동화하기 쉽다.

개발 단계는 stage 1부터 stage 3까지 간다. 현재는 “부팅과 설치 가능성 증명”인
stage 1 후반이며, stage 2는 운영 가능한 최소 서버 배포판, stage 3은 자기 빌드와
쿠버네티스/클러스터 운영이 가능한 독립 배포판으로 정의한다. 자세한 기준은
[KIKI OS 개발 단계 정의](docs/kiki-os-stages.ko.md)를 따른다.

## 빠른 명령

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 40
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-node.yaml
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --dry-run
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

payload ISO 생성:

```bash
python tools/ki2iso.py --profile bootstrap-stage1
```

부팅 테스트 ISO 생성:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1
```

stage-1 TUI 설치 ISO 생성:

```bash
python tools/ki2bootiso.py --profile bootstrap-stage1 --mode installer
```

## TUI 설치기

설치기는 부팅 시 KIKI 로고를 출력하고 콘솔 TUI를 실행한다. 현재 기능은 다음과
같다.

- `minimal-systemd` 기본 패키지 선택
- ISO에 포함된 전체 패키지 선택
- 저장소 인덱스에서 개별 패키지 이름 추가
- 자동 디스크 구성: ESP + swap + root
- 수동 디스크 구성: `fdisk` 또는 `cfdisk` 실행 후 ESP/root/swap 직접 입력
- 네트워크 기본값: `systemd-networkd` DHCP, interface match `en* eth*`
- `/dev/sda1` 같은 파티션 경로를 전체 디스크 대상으로 잘못 입력하는 실수 차단
- 관리자 사용자 생성, root 직접 로그인 잠금 기본값
- `sudo` 그룹 정책 생성
- 기본 systemd 유닛 활성화
- UEFI fallback `BOOTX64.EFI` 설치
- 설치 전 선언형 YAML 설치 계획서 미리보기

설치 계획서는 설치 전 `/run/kiki/install-plan.yaml`에 생성되고, 패키지 설치 후
설치된 시스템의 `/var/lib/ki2/install-plan.yaml`에 보존된다. 비밀번호는 계획서에
저장하지 않고 런타임 입력값으로만 처리한다.

## Hyper-V 참고

생성된 미디어는 BIOS/MBR과 UEFI 부팅을 지원하지만 Secure Boot 서명은 아직 없다.
Hyper-V Generation 2에서 테스트할 때는 Secure Boot를 끈다.

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

초기 Go 도구는 아직 남겨두었다. `bosctl`은 로컬 BOS 패키지 DB와 저장소
인덱스를 다루고, `cpmctl`은 컨테이너 패키지 DB를 다루며, `bosbuild`는
`manifest.yaml`, `rootfs/`, `scripts/`를 포함한 `.bos` 아카이브를 만든다.

```bash
go mod tidy
go build -o bosctl ./cmd/bosctl
go build -o cpmctl ./cmd/cpmctl
go build -o bosbuild ./cmd/bosbuild
go test ./cmd/... ./internal/...
```

앞으로의 배포판 패키징 중심 이름은 `ki2`이며, BOS/CPM은 과거 실험과 호환
검토용 코드로 취급한다.
