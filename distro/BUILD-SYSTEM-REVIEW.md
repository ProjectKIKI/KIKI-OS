# KIKI 빌드 시스템 검토

## 현재 상태

저장소에는 패키지 빌드부터 OS 이미지 조립까지 이어지는 기본 뼈대가 있다.
전체 로드맵은 stage 1, stage 2, stage 3으로 나누며 상세 정의는
`docs/kiki-os-stages.ko.md`를 기준으로 한다. 현재 위치는 stage 2 개발 라인이다.

- `tools/ki2build.py`
  - TOML/YAML 레시피 로드
  - 패키지와 프로파일 의존성 그래프 검증
  - 런타임/빌드 계획 출력
  - `.ki2` 패키지 빌드
  - `dist/ki2/repo/index.<arch>.json` 저장소 인덱스 생성
  - 패키지 payload에서 rootfs 트리 조립
- `tools/ki2ci.py`
  - CLI 파이프라인 제공
  - 웹 대시보드 제공
  - 패키지 카탈로그, 프로파일, 산출물, 보안 점검, 작업 로그 표시
- `tools/ki2iso.py`
  - rootfs와 패키지 저장소를 payload ISO로 패키징
- `tools/ki2bootiso.py`
  - BIOS/UEFI 부팅 가능한 VM 미디어 생성
  - stage-1 TUI 설치 미디어와 Hyper-V용 VHDX 출력 생성
- `cmd/kiki-installer-tui`
  - Stage 1부터 패키지로 포함하는 Go 기반 설치 계획서 TUI preview
  - `/run/kiki/install-plan.yaml` 상태판 렌더링과 Stage 2 설치기 전환 검증
- `tools/ki2publish.py`
  - 패키지, 저장소, ISO, 디스크 이미지를 정적 배포 트리로 복사
- `distro/sources/ki2ctl/usr/bin/ki2ctl`
  - HTTP 저장소 인덱스 다운로드
  - 패키지 검색, 정보 조회, 의존성 해석, 설치/삭제 preview
  - 파일 충돌 탐지, 설치 트랜잭션 기록, 실패 시 기본 rollback
  - HTTP, `file://`, 로컬 경로 저장소와 서명 metadata 검증

## 패키지 범위

`.ki2` 패키지는 archive 내부 `rootfs/` 아래에 OS 소유 경로를 담는다. 따라서
패키지는 `/etc`, `/usr`, `/boot`, `/lib/modules`, systemd 유닛 같은 파일을
소유할 수 있다.

패키지에 넣지 않아야 하는 경로:

- `/dev`
- `/proc`
- `/sys`
- `/run`
- `/tmp`

이 경로들은 런타임 pseudo filesystem이며 init 또는 systemd가 만든다.

패키지 manifest에는 다음 정보가 들어간다.

- 빌드/런타임 의존성
- payload 메타데이터
- 생성 파일 목록
- 빌드 키와 레시피 digest

## CLI 기능

동작 중:

- 레시피/프로파일 검증
- 의존성 계획
- 패키지 빌드
- 저장소 인덱스 생성
- rootfs 조립
- payload ISO와 부팅 ISO 생성
- 배포 트리 생성

부족하거나 진행 중인 부분:

- install/remove script 실행
- 설치된 시스템 내부 패키지 DB 고도화
- 패키지 업그레이드 정책 고도화
- 공개키 기반 저장소 서명

## 웹 콘솔 기능

동작 중:

- 파이프라인 실행 버튼
- 작업 목록과 작업별 로그
- 의존성 및 산출물 상태가 포함된 패키지 카탈로그
- 프로파일 개요
- 패키지, rootfs, ISO, VHDX/이미지 산출물 목록
- source pin과 shell script 점검용 보안 페이지

부족하거나 진행 중인 부분:

- 패키지별 빌드 버튼
- 프로파일별 rootfs/ISO 빌드 버튼
- 패키지 충돌 리포트의 웹 표시
- 설치 계획서 미리보기의 웹 통합
- 저장소 서명 상태 표시

## 네트워크 방향

기본 네트워크 스택은 `systemd-networkd`와 `systemd-resolved`로 간다.

이유:

- 기본 systemd 구성과 잘 맞는다.
- 서버/VM/쿠버네티스 노드 자동화에 단순하다.
- 무인 설치 YAML에서 `.network` 파일 생성만으로 네트워크 구성을 표현하기 쉽다.
- `NetworkManager`보다 초기 패키지 수와 런타임 복잡도가 작다.

`NetworkManager`는 추후 데스크톱, Wi-Fi, VPN, 운영자용 GUI 네트워크 설정이
필요한 프로파일에서 선택 패키지로 추가한다.

## 쿠버네티스 방향

쿠버네티스 프로파일은 CRI-O를 기본 런타임으로 두고, Stage 2에서는 containerd 변형
프로파일도 함께 검증한다.

- `cri-o`
- `conmon`
- `crun`
- `cni-plugins`
- `cri-tools`
- `kubelet`
- `kubeadm`
- `kubectl`
- `containerd`
- `runc`
- `kube-node-config-containerd`

현재 일부 레시피는 resolver-visible metadata 또는 local config 패키지다. Stage 2의
네트워크 userspace는 `host-files` payload로 실제 명령을 제공하며, 다음 실제 패키지
작업은 `crun`, `conmon`, `cri-o`와 네트워크 userspace를 source-backed build recipe로
바꾸는 것이다.

네트워크와 방화벽 계층은 `nftables`, `iptables`, `conntrack-tools`, `firewalld`,
`bridge-utils`, `socat`, `ethtool`, `chrony`를 Stage 2 검증용 `.ki2` payload로
제공한다. 기본 bridge 점검은 `iproute2`의 `bridge` 명령을 기준으로 하고,
`brctl`은 호환 wrapper로 둔다.

## 다음 점검 항목

- `distro/recipes/core.toml`의 남은 source hash pin 처리
- 설치된 시스템의 `/var/lib/ki2/` 패키지 DB 고도화
- repo metadata 공개키 서명 전환
- 웹 UI에 패키지별 빌드 버튼과 로그 추가
- 설치 계획서 YAML을 웹 설치기와 무인 설치에서 재사용
