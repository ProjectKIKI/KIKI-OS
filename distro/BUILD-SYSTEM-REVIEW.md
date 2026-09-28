# KIKI 빌드 시스템 검토

> 이 문서는 초기 2단계 빌드 시스템 검토 기록이다. 현재 개발 라인은 Stage3이며,
> 최신 로컬 빌드 절차는 [Stage3 로컬 빌더 가이드](../docs/kiki-stage3-local-builder.ko.md)를 따른다.

## 현재 상태

저장소에는 패키지 빌드부터 OS 이미지 조립까지 이어지는 기본 뼈대가 있다.
전체 로드맵은 1단계, 2단계, 3단계로 나누며 상세 정의는
`docs/kiki-os-stages.ko.md`를 기준으로 한다. 아래 평가는 작성 당시의 2단계 개발 상태를 설명한다.

- `tools/ki2build.py`
  - TOML/YAML 레시피 로드
  - 패키지와 프로파일 의존성 그래프 검증
  - 런타임/빌드 계획 출력
  - `.ki2` 패키지 빌드
  - `dist/ki2/repo/index.<arch>.json` 저장소 인덱스 생성
  - 패키지 페이로드에서 루트 파일시스템 트리 조립
- `tools/ki2ci.py`
  - CLI 파이프라인 제공
  - 웹 대시보드 제공
  - 패키지 카탈로그, 프로파일, 산출물, 보안 점검, 작업 로그 표시
- `tools/ki2iso.py`
  - 루트 파일시스템과 패키지 저장소를 페이로드 ISO로 패키징
- `tools/ki2bootiso.py`
  - BIOS/UEFI 부팅 가능한 VM 미디어 생성
  - 1단계 TUI 설치 미디어와 Hyper-V용 VHDX 출력 생성
- `cmd/kiki-installer-tui`
  - 1단계부터 패키지로 포함하는 Go 기반 설치 계획서 TUI 미리보기
  - `/run/kiki/install-plan.yaml` 상태판 렌더링과 2단계 설치기 전환 검증
- `tools/ki2publish.py`
  - 패키지, 저장소, ISO, 디스크 이미지를 정적 배포 트리로 복사
- `distro/sources/ki2ctl/usr/bin/ki2ctl`
  - HTTP 저장소 인덱스 다운로드
  - 패키지 검색, 정보 조회, 의존성 해석, 설치/삭제 미리보기
  - 파일 충돌 탐지, 설치 트랜잭션 기록, 실패 시 기본 롤백
  - HTTP, `file://`, 로컬 경로 저장소와 서명 메타데이터 검증

## 패키지 범위

`.ki2` 패키지는 아카이브 내부 `rootfs/` 아래에 OS 소유 경로를 담는다. 따라서
패키지는 `/etc`, `/usr`, `/boot`, `/lib/modules`, systemd 유닛 같은 파일을
소유할 수 있다.

패키지에 넣지 않아야 하는 경로:

- `/dev`
- `/proc`
- `/sys`
- `/run`
- `/tmp`

이 경로들은 런타임 의사 파일시스템이며 init 또는 systemd가 만든다.

패키지 매니페스트에는 다음 정보가 들어간다.

- 빌드/런타임 의존성
- 페이로드 메타데이터
- 생성 파일 목록
- 빌드 키와 레시피 다이제스트

## CLI 기능

동작 중:

- 레시피/프로파일 검증
- 의존성 계획
- 패키지 빌드
- 저장소 인덱스 생성
- 루트 파일시스템 조립
- 페이로드 ISO와 부팅 ISO 생성
- 배포 트리 생성

부족하거나 진행 중인 부분:

- 설치/삭제 스크립트 실행
- 설치된 시스템 내부 패키지 DB 고도화
- 패키지 업그레이드 정책 고도화
- 공개키 기반 저장소 서명

## 웹 콘솔 기능

동작 중:

- 파이프라인 실행 버튼
- 작업 목록과 작업별 로그
- 의존성 및 산출물 상태가 포함된 패키지 카탈로그
- 프로파일 개요
- 패키지, 루트 파일시스템, ISO, VHDX/이미지 산출물 목록
- 소스 고정값과 셸 스크립트 점검용 보안 페이지

부족하거나 진행 중인 부분:

- 패키지별 빌드 버튼
- 프로파일별 루트 파일시스템/ISO 빌드 버튼
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

쿠버네티스 프로파일은 CRI-O를 기본 런타임으로 두고, 2단계에서는 containerd 변형
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

현재 일부 레시피는 해석기가 볼 수 있는 메타데이터 또는 로컬 설정 패키지다. 2단계의
네트워크 사용자 공간은 `host-files` 페이로드로 실제 명령을 제공하며, 다음 실제 패키지
작업은 `crun`, `conmon`, `cri-o`와 네트워크 사용자 공간을 소스 기반 빌드 레시피로
바꾸는 것이다.

네트워크와 방화벽 계층은 `nftables`, `iptables`, `conntrack-tools`, `firewalld`,
`bridge-utils`, `socat`, `ethtool`, `chrony`를 2단계 검증용 `.ki2` 페이로드로
제공한다. 기본 브리지 점검은 `iproute2`의 `bridge` 명령을 기준으로 하고,
`brctl`은 호환 래퍼로 둔다.

## 다음 점검 항목

- `distro/recipes/core.toml`의 남은 소스 해시 고정값 처리
- 설치된 시스템의 `/var/lib/ki2/` 패키지 DB 고도화
- 저장소 메타데이터 공개키 서명 전환
- 웹 UI에 패키지별 빌드 버튼과 로그 추가
- 설치 계획서 YAML을 웹 설치기와 무인 설치에서 재사용
