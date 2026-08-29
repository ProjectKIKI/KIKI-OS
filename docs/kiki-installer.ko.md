# KIKI OS 인스톨러 구성 및 동작

이 문서는 KIKI OS 설치 ISO에서 실행되는 인스톨러의 구성요소, 화면 전환,
설치 계획 전달, 디스크 작업과 빌드·검증 방법을 설명한다. 화면별 조작법은
[CLI/TUI/GTK 설치 프런트엔드](kiki-installer-frontends.ko.md)를 함께 참고한다.

## 현재 구현 범위

인스톨러는 GTK 4 GUI, 전체 화면 TUI, 번호 입력식 Stage-1 CLI와 무인 설치를
제공한다. 모든 프런트엔드는 `kiki-install-plan-v1` 형식의 YAML 계획을 사용하며,
실제 파티셔닝·포맷·패키지 추출은 initramfs의 Stage-1 실행기가 담당한다.

| 구성요소 | 위치 | 역할 |
| --- | --- | --- |
| GTK 프런트엔드 | `cmd/kiki-installer-gtk` | 한국어 설정 화면, 계획 검토·저장, 설치 시작 요청 |
| 공통 계획 생성기/TUI | `cmd/kiki-installer-tui` | 프로필·그룹 해석, 검증, YAML 생성, 전체 화면 TUI |
| Stage-1 실행기 | `tools/ki2bootiso.py`의 `INIT_C` | 디스크 확인, 포맷, 패키지 설치, 부트 파일과 설정 기록 |
| GUI 런타임 조립기 | `tools/ki2graphics.py` | Cage, wlroots, GTK, 폰트와 입력 장치 데이터 조립 |
| GUI 패키지 레시피 | `distro/recipes/installer-gui.toml` | `kiki-installer-gtk` `.ki2` 패키지 생성 |
| 계획 계약 | `distro/specs/kiki-install-plan-v1.yaml` | 설치 계획 필드와 검증 규칙 |

## 기본 실행 순서

설치 ISO의 GRUB 기본 항목은 `KIKI OS graphical installer (default)`이며
`kiki.ui=gui`를 커널에 전달한다.

```text
GRUB
  → Stage-1 initramfs
  → Cage/wlroots
  → GTK 설치기
      ├─ 암호와 INSTALL 확인
      ├─ Stage-1 설치 실행 + GUI 진행률 표시
      ├─ 설치 완료 확인 → 사용자 확인 후 재부팅
      └─ 설치 시작 전 창 닫기 또는 GUI 실패: 전체 화면 TUI
                                             → Stage-1 CLI
```

GUI에는 Xorg를 사용하지 않는다. Cage가 Wayland/DRM/KMS를 직접 사용하며,
Hyper-V의 가속 렌더 노드가 없는 환경에서는 CPU 기반 Pixman 렌더러를 사용한다.
그래픽 구성요소가 없거나 실행에 실패하면 설치 작업을 시작하지 않고 TUI로
폴백한다.

## GUI 메뉴

| 메뉴 | 설정 내용 |
| --- | --- |
| 시작 | 설치 모드와 InstallPlan 저장 경로 |
| 언어 및 지역 | 로케일, 콘솔 키맵, 시간대 |
| 디스크 | 설치 대상 전체 디스크와 swap 정책 |
| 네트워크 | DHCP, 고정 주소 또는 네트워크 끄기 |
| 계정 | 관리자 사용자와 호스트명 |
| 패키지 소스 | 로컬 미디어, 원격 저장소 또는 미러 계획 |
| 프로필 및 AI | OS 프로필, 컨테이너 런타임, AI 모드, 추가 패키지 그룹 |
| 검토 및 설치 | 계획 새로고침, 계획 저장, 설치 시작 |
| 설치 진행 | 단계별 진행률과 메시지, 설치 완료 후 재부팅 확인 |

`설치 계획 저장`은 디스크를 변경하지 않는다. `kiki-installer-tui --write`를
호출해 `/run/kiki/install-plan.yaml`을 생성하거나 갱신할 뿐이다.

## 설치 시작 동작

`설치 시작` 버튼을 누르면 다음 순서로 처리한다.

1. 전체 디스크 경로, 고정 IP, 원격 AI 엔드포인트 등 입력값을 검사한다.
2. 공통 계획 생성기로 `InstallPlan` YAML을 저장한다.
3. 관리자 암호·확인값, 해석된 `packages.selected` 목록과 GUI 선택값을
   `/run/kiki/gui-install.request`에 기록한다.
4. 요청 파일을 mode `0600`으로 제한한다.
5. GTK는 종료하지 않고 `설치 진행` 화면으로 전환한다.
6. Stage-1은 요청을 읽자마자 요청 파일을 0바이트로 잘라 암호 원문을 제거한다.
7. Stage-1이 암호 길이와 `INSTALL /dev/<disk>` 확인값을 다시 검증한다.
8. ISO 저장소에 요청된 모든 패키지가 있는지 확인한다.
9. 모든 확인이 통과할 때만 파티셔닝과 포맷을 시작한다.
10. Stage-1은 `/run/kiki/install-progress.state`를 원자적으로 갱신하고 GTK는
    이를 읽어 단계, 진행률, `설치 완료/전체 패키지` 개수와 현재 패키지를 표시한다.
11. 설치가 완료되면 GTK가 `확인 후 재부팅` 버튼을 표시한다.
12. 사용자가 버튼을 누르면 `/run/kiki/gui-reboot.request`가 생성되고,
    Stage-1이 이 명시적 확인을 받은 뒤에만 재부팅한다.

암호는 YAML InstallPlan이나 영구 디스크에 기록하지 않는다. GUI와 Stage-1이
서로 다른 프로세스이므로 mode `0600`인 `/run` tmpfs 요청 파일에 잠시 전달하며,
Stage-1이 메모리로 복사한 즉시 파일 내용을 제거한다. GUI 창을 그냥 닫으면 요청
파일이 생성되지 않으며 TUI가 실행된다.

계정 암호와 파괴적 확인부터 진행률, 완료 확인과 재부팅까지 GUI 안에서 처리한다.
정확한 작업량을 알 수 있는 패키지 설치는 선택 패키지 개수로 진행률을 계산하고
`패키지 설치 완료: 12 / 68개 · 현재: <이름>` 형식의 카운터를 표시하며,
파티션 생성·포맷·동기화는 단계별 가중치로 표시한다. 설치 완료만으로 자동
재부팅하지 않으며 사용자가 완료 화면을 확인하고 버튼을 눌러야 한다.

현재 실제 ISO 설치 시작은 `local` 패키지 소스만 지원한다. 원격 저장소와 미러는
계획 생성에는 사용할 수 있지만, GUI에서 실제 설치를 시작하려면 검증된 원격
다운로드 백엔드가 구현될 때까지 로컬 설치 미디어를 선택해야 한다.

## 디스크와 부팅 구성

자동 설치는 `/dev/sda`, `/dev/vda`, `/dev/nvme0n1` 같은 전체 디스크만 받는다.
파티션 경로를 대상 디스크로 지정하면 검증 단계에서 거부한다.

일반 서버 프로필의 기본 자동 레이아웃은 다음과 같다.

```text
1. EFI System Partition: vfat
2. swap: auto 또는 on일 때 생성
3. root: ext4
```

swap을 `off`로 지정하거나 Kubernetes 프로필을 사용하면 swap 파티션을 생략하고
root가 2번 파티션이 된다. 현재 Stage-1 자동 경로는 MBR 파티션 테이블에 EFI
파티션과 UEFI fallback 부트 파일을 설치한다. 설치된 시스템은 UEFI VM에서
부팅하는 경로가 검증 대상이며, BIOS/MBR 부트로더 설치는 아직 완료 범위가 아니다.
Hyper-V에서는 2세대 VM과 Secure Boot 끄기를 사용한다.

## 프로필과 패키지

프로필은 기본 패키지, 서비스, Kubernetes 역할과 컨테이너 런타임 정책을 정한다.
GUI의 `추가 그룹(쉼표)` 입력값은 공통 그룹 카탈로그
`/usr/share/ki2/package-groups.json`으로 해석된다. 생성된 패키지 목록은
InstallPlan의 `packages.selected`와 GUI 요청 파일에 모두 들어가며, Stage-1은
ISO 저장소에 없는 패키지가 하나라도 있으면 포맷 전에 중단한다.

주요 프로필은 다음과 같다.

- `minimal-systemd`: 최소 systemd 서버
- `server-core`: 일반 서버, 네트워크·방화벽·AI 관리 도구
- `kiki-kube-bootstrap`: 첫 Kubernetes control plane
- `kiki-kube-control`: 추가 control plane
- `kiki-kube-compute`: compute 노드
- `*-containerd`: 같은 역할을 containerd 런타임으로 구성

Kubernetes 프로필은 swap을 강제로 끄며 CRI-O 또는 containerd를 선택한다.

## 네트워크, 계정과 AI

네트워크는 대상 rootfs에 systemd-networkd 설정으로 기록한다. DHCP가 기본이며,
고정 주소에는 CIDR 주소가 필요하다. `off`를 선택하면 자동 네트워크 구성을 쓰지
않는다.

GUI에서 지정한 관리자 사용자는 sudo 그룹에 추가되고 root 직접 로그인은 잠긴다.
암호와 암호 확인은 계정 화면에서 입력하고, 검토 화면에서
`INSTALL /dev/<disk>`를 정확히 입력해야 `설치 시작`이 동작한다. 설치 후 AI
모드가 `local`이면
llama.cpp 기반 로컬 런타임과 `tty1` AI 콘솔을 구성하고, `tty2`는 복구 셸로
유지한다. AI가 제안한 명령은 사용자가 확인한 후에만 실행한다.

## 무인 설치

무인 설치는 명시적인 `kiki.autoinstall` 커널 인자가 있을 때만 활성화된다.

```text
kiki.autoinstall=erase
kiki.target=/dev/sda
kiki.profile=server-core
kiki.hostname=kiki.local
kiki.locale=ko_KR.UTF-8
kiki.keymap=kr
kiki.timezone=Asia/Seoul
kiki.ai=local
```

`kiki.autoinstall=erase|quick-vm`은 콘솔의 파괴적 확인을 생략하므로 통제된 VM이나
랩 자동화에서만 사용한다. 일반 GUI/TUI 설치에서는 이 인자가 없어야 한다.

## 개발 빌드

GTK 프런트엔드와 공통 계획 생성기를 단독 빌드한다.

```sh
make -C cmd/kiki-installer-gtk
go build -o build/kiki-installer-tui ./cmd/kiki-installer-tui
```

GUI 런타임과 `.ki2` 패키지를 갱신한다.

```sh
python3 tools/ki2graphics.py prepare --jobs 4
python3 tools/ki2build.py build \
  --profile distro/profiles/server-core.toml \
  --only kiki-installer-gtk
python3 tools/ki2build.py repo-index
```

설치 ISO를 생성한다.

```sh
python3 tools/ki2bootiso.py \
  --profile server-core \
  --mode installer \
  --rootfs-dir dist/rootfs/server-core \
  --repo-dir dist/ki2/repo \
  --packages-dir dist/ki2/packages/x86_64 \
  --output dist/iso/kiki-stage3-v3-installer-x86_64.iso
```

## 검증

```sh
make -C cmd/kiki-installer-gtk clean all
GOCACHE=/tmp/kiki-go-cache go test ./cmd/kiki-installer-tui
PYTHONPATH=tools python3 -m unittest \
  tools.test_ki2bootiso tools.test_ki2build
sha256sum dist/iso/kiki-stage3-v3-installer-x86_64.iso
```

ISO 안의 GRUB 기본 항목이 `kiki.ui=gui`인지, installer runtime manifest가 최신
`kiki-installer-gtk` 패키지를 가리키는지, initramfs에
`/run/kiki/gui-install.request` 처리 코드가 포함됐는지도 함께 확인한다.

## 로그와 문제 해결

| 증상 | 확인 위치 또는 대응 |
| --- | --- |
| GUI 시작 실패 | `/run/kiki/gui-installer.log` |
| `Found 0 GPUs` | `/dev/dri/card0`, `CONFIG_DRM_HYPERV=y`, Secure Boot 끄기 확인 |
| 키맵 SHM 오류 | `/dev/shm`에 mode 1777 tmpfs가 마운트됐는지 확인 |
| libinput quirks 오류 | `/usr/share/libinput`, `/etc/libinput` 포함 여부 확인 |
| GUI를 닫자 TUI가 표시됨 | 정상 폴백 동작. 설치하려면 `설치 시작`을 사용 |
| 설치 시작 버튼에서 중단 | 로컬 소스, 전체 디스크 경로, 고정 IP와 AI 엔드포인트 검사 |
| 패키지 누락으로 중단 | ISO 저장소 인덱스와 `packages.selected` 목록 비교 |
| GUI 진행 상태 확인 | `/run/kiki/install-progress.state` |
| 완료 후 재부팅되지 않음 | 완료 화면의 `확인 후 재부팅` 버튼을 눌렀는지 확인 |

## 현재 제한 사항

- GUI 설치 실행은 로컬 설치 미디어만 지원한다.
- GUI는 주요 설치 단계와 현재 패키지를 표시하며, 하위 도구의 전체 원문 로그는 초기 콘솔에 남는다.
- 설치 대상의 디스크 암호화와 Secure Boot 키 등록은 아직 제공하지 않는다.
- 설치된 시스템의 검증 대상은 UEFI이며 BIOS 부트로더 설치는 후속 작업이다.
- GTK/Wayland 런타임은 현재 Stage 3 부트스트랩을 위해 빌드 호스트 ABI를 묶는다.
