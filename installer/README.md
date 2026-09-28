# KIKI Alpine/Debian 초기 인스톨러: 과거 실험 경로

이 디렉터리는 KIKI 노드 부트스트랩을 위한 초기 MVP다. Alpine 이미지는 인스톨러 실행 환경이고, 설치 대상 OS는 Debian이다. 현재 KI2 기반 KIKI OS Stage3 인스톨러와는 별도 경로이며 현행 ISO 빌드 지침으로 사용하지 않는다. 현행 빌드는 [Stage3 로컬 빌드 가이드](../docs/kiki-stage3-local-builder.ko.md)를 따른다.

실험 흐름은 Alpine 인스톨러 부팅 → `/etc/kiki/install.yaml` 읽기 → 대상 디스크 파티셔닝·포맷 → `debootstrap`으로 Debian 설치 → 호스트 이름·네트워크·`kiki-agent` 설정 → GRUB 설치 → Debian 컨트롤 또는 컴퓨트 노드로 재부팅이다.

## 주요 파일

| 경로 | 용도 |
| --- | --- |
| `configs/` | 설치·UEFI·이미지·KikiMachine YAML 예제 |
| `alpine/overlay/` | 설정과 `kiki-install` 실행 파일 |
| `alpine/iso/` | Containerfile, Alpine 프로필, ISO 빌드 도구 |
| `scripts/` | 오버레이·ISO 빌드, Debian 설치, 미러, 검증, 로그 전송 |
| `crds/` | `KikiInstallConfig`·`KikiMachine` CRD |
| `dist/` | 로컬 산출물. Git 배포 대상이 아님 |

Alpine 실행 환경에는 `python3`, `py3-yaml`, `debootstrap`, `parted`, `gptfdisk`의 `sgdisk`, `e2fsprogs`, `dosfstools`, `util-linux`, `grub`, `grub-bios`, `grub-efi`, `efibootmgr`, `mount`, 필요한 init 도구가 필요하다. 정확한 패키지 이름은 Alpine 릴리스와 이미지 프로필에 따라 다를 수 있다.

## 오버레이·ISO 빌드와 사전 검토

저장소 루트에서 실행한다. 처음에는 네트워크 접근이 필요하다.

```bash
bash installer/scripts/build-alpine-overlay.sh
bash installer/scripts/build-alpine-iso.sh --runner podman --release v3.20
bash installer/scripts/build-alpine-iso.sh --runner podman --dry-run
```

오버레이는 `installer/dist/kiki-alpine-overlay.tar.gz`, ISO는 `installer/dist/iso/`에 생성된다. Alpine 로컬 빌드는 [별도 가이드](alpine/iso/README.md)를 참조한다.

## 이 경로의 커널 고정 정책

이 과거 경로는 더 새로운 커널을 임의 선택하지 않고 버전이 다르면 빌드를 실패시킨다. 임시 Alpine v3.20 ISO/PXE는 `profile_kiki.sh`에서 `linux-lts=6.6.139-r0`, 설치 대상 Debian Bookworm은 `linux-image-6.1.0-51-amd64=6.1.177-1`로 고정한다. 인스톨러는 `bookworm-security` 미러에서 후자를 받고 hold 처리한 뒤 GRUB 설치 전 `dpkg-query`로 검증한다. 이 두 핀은 현행 KI2 Stage3 커널 핀을 설명하지 않는다.

재현 가능한 운영 배포에는 버전을 보존하는 내부 Alpine·Debian 미러를 사용한다. 커널 보안 업데이트는 패키지·버전 상수 변경, ISO/PXE/디스크 이미지 재빌드·서명, BIOS/UEFI 및 GPU 수용 시험, InfraOps 승격을 거치는 명시적 릴리스 변경으로 다룬다.

## VM·드라이런 검증

디스크를 바꾸기 전에 항상 드라이런을 수행한다.

```bash
bash installer/scripts/test-qemu-install.sh --iso installer/dist/iso/kiki.iso --mode bios --dry-run
bash installer/scripts/test-qemu-install.sh --iso installer/dist/iso/kiki.iso --mode uefi --dry-run
installer/scripts/install-debian-node.py --config installer/configs/install.example.yaml --dry-run
bash installer/scripts/smoke-dry-run.sh
```

Alpine 안에서는 `kiki-install --dry-run`으로 확인한다. 실제 설치는 대상 디스크를 변경하므로 명시적 `kiki-install --yes`가 필요하다. 기본 설정 경로는 `/etc/kiki/install.yaml`이다.

## MVP 구현·남은 작업

YAML 필수값 검증, 드라이런, 파괴적 설치의 `--yes` 보호, BIOS/UEFI 파티션 계획, ext4 루트, `debootstrap`, 호스트 이름·hosts·systemd-networkd DHCP, `/etc/kiki/node.yaml`, 부팅 시 에이전트 등록·하트비트, 선택적 Kubernetes 패키지 부트스트랩, 관리 API 콜백, CRD 매니페스트, SSH·에이전트 활성화, GRUB, 마운트 정리 경로가 있다. 운영용 에이전트 패키지, 실제 BIOS/UEFI VM 설치 시험, `KikiMachine`·`KikiInstallConfig` 컨트롤러 조정은 별도 검증이 필요하다.

## 관리 API와 노드 자격 증명

```bash
go run ./cmd/kiki-bootstrapd \
  -host 0.0.0.0 -port 8088 -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

설치 중 인스톨러는 `{spec.agent.managementUrl}{spec.agent.callbackPath}`로 가능한 범위에서 JSON 콜백을 보낸다. 기본 경로는 `/api/v1/nodes/register`다. 일시적인 관리 API 장애는 설치 실패가 아니라 경고로 취급한다. 첫 성공 콜백이 일회성 등록 토큰을 노드 Bearer 토큰으로 교환하며 설치 대상에는 노드 토큰만 기록한다. API가 일시적으로 없으면 첫 부팅 에이전트가 교환하고 토큰을 원자적으로 대체한다. 후속 등록·하트비트·로그·번들은 `Authorization` 헤더의 노드 토큰을 쓴다. 운영 환경에서는 YAML의 평문 토큰보다 `spec.agent.registrationTokenFile`을 사용한다.

## Kubernetes와 GPU 선택 경로

`spec.bootstrap.installKubernetesTools: true`이면 설치 대상 Debian에 `kubelet`, `kubeadm`, `kubectl`을 설치하는 `kiki-bootstrap-kubernetes.service`를 만들고 선택적으로 지정된 join 명령을 실행한다. 초기 부트스트랩 전용 노드에는 `false`를 두어도 containerd 미러와 이미지 사전 가져오기를 설정할 수 있다.

NVIDIA 컴퓨트 노드에서만 `spec.accelerators.nvidia.enabled: true`를 쓴다. HTTPS 저장소·키 URL, 예상 키 SHA-256, 정확한 드라이버·도구 버전, 다이제스트 고정 장치 플러그인 이미지가 필요하다. 첫 부팅 유닛은 패키지 설치, `nvidia-ctk`로 containerd 설정, 재시작, `nvidia-smi` 확인 뒤 완료 표시를 남긴다. 노드에는 `kiki.io/accelerator=nvidia`, `kiki.io/runtime-vllm=true` 레이블이 붙는다. 장치 플러그인 매니페스트는 `/etc/kiki/manifests/nvidia-device-plugin.yaml`에 쓰고 InfraOps·컨트롤러 신뢰 경계에서 적용한다. 컴퓨트 노드에 cluster-admin 권한을 주지 않는다.

## 이미지 미러·설정 렌더링

`install.yaml`의 `spec.images.mirrors`와 `prePull`로 미러와 사전 가져올 이미지를 설정한다. containerd 미러는 `/etc/containerd/certs.d/<registry>/hosts.toml`에 기록하고 사전 가져오기는 `kiki-prepull-images.service`를 활성화한다.

```bash
bash installer/scripts/mirror-images.sh --dry-run installer/configs/images.example.yaml
python3 installer/scripts/render-install-config.py \
  --hostname kiki-node-002 --role compute --boot-mode uefi \
  --management-url http://bootstrap.local:8088 \
  --output installer/dist/kiki-node-002.install.yaml
```

대시보드는 노드·설치 단계·하트비트·이벤트·이미지 계획·산출물·로그 번들·진단 요약을 보여준다. 진단은 기본적으로 규칙 기반이며 별도 LLM 설정 시 읽기 전용 보조 요약을 사용한다.

```bash
bash installer/scripts/upload-log-bundle.sh \
  --node kiki-node-001 --server http://bootstrap.local:8088 \
  --token-file /etc/kiki/registration-token
```
