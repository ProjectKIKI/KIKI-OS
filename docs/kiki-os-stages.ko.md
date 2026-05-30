# KIKI OS 개발 단계 정의

KIKI OS는 stage 1, stage 2, stage 3까지 진행한다. 각 stage는 “무엇이 되는가”를
기준으로 나눈다. 기능이 늘어날 때마다 이 문서를 기준으로 현재 작업이 어느
단계에 속하는지 판단한다.

## 릴리스 라인 이름

- `stage1-v1`: Stage 1 부팅/설치 검증 라인. 저장소 metadata가 없는 `bootstrap-stage1` 산출물의 기본 릴리스 이름이다. 최종 기준은 [KIKI OS Stage 1 V1 최종 문서](kiki-stage1-v1-final.ko.md)를 따른다.
- `stage2-v2`: Stage 2 패키지 저장소/설치 미디어 라인. `ki2repo`의 기본 channel이며 설치 계획서의 기본 저장소 channel이다. 진행 기준은 [KIKI OS Stage 2 V2 진행 문서](kiki-stage2-v2-progress.ko.md)를 따른다.

## Stage 0: 실험과 빌드 기반

목표: 배포판을 만들 수 있는 최소 도구와 패키지 형식을 검증한다.

현재 위치:

- Go 기반 `bosctl`, `cpmctl`, `bosbuild` 실험 코드
- `ki2` 패키지 포맷 정의
- 레시피와 프로파일 로더
- `.ki2` 패키지 빌드
- 저장소 인덱스 생성
- rootfs 조립
- Rocky 9/WSL 빌더 환경 검증

Stage 0의 산출물은 완성된 OS가 아니라 “배포판을 만들기 위한 공장”이다.

## Stage 1: 부팅과 설치 가능성 증명

목표: VM에서 부팅하고, 디스크에 설치하고, systemd 기반 사용자 공간으로 진입한다.

필수 기능:

- BIOS/MBR 및 UEFI 부팅 ISO
- KIKI 로고가 나오는 stage-1 부팅 환경
- C 기반 syscall-only `/init`
- 콘솔 메뉴형 TUI 설치기
- Go 기반 `kiki-installer-tui` preview 패키지
- 자동 파티셔닝: ESP + swap + root
- 수동 파티셔닝: TUI의 Disk 메뉴에서 `cfdisk`/`fdisk`를 실행하고,
  편집한 디스크의 ESP/root/swap 후보를 설치 단계에서 기본값으로 제안
- `.ki2` 패키지를 rootfs로 추출
- 관리자 사용자 생성
- root 직접 로그인 잠금 기본값
- `systemd`, `dbus`, `systemd-logind`, getty 실행
- 기본 네트워크: `systemd-networkd` DHCP
- 선언형 YAML 설치 계획서 생성과 보존
- Go TUI preview로 같은 설치 계획서를 렌더링하고 테스트할 수 있음
- 설치 후 VM 재부팅 및 로그인 확인
- 설치 후 `kiki-stage1-check`로 systemd/dbus/network/login 기본 상태 점검

Stage 1의 완료 기준:

- 설치 ISO로 VM 부팅 가능
- TUI에서 디스크 설치 가능
- 설치된 디스크로 재부팅 가능
- 일반 사용자로 로그인 가능
- `systemctl`, `journalctl`, `loginctl`, `networkctl`이 기본 동작
- DHCP 환경에서 네트워크 링크와 DNS 확인 가능
- swap이 systemd에서 실패해도 emergency mode로 빠지지 않음
- `kiki-installer-tui --render`로 설치 계획서 상태판을 확인할 수 있음
- `kiki-stage1-check`가 치명적인 실패 없이 완료됨

Stage 1은 “실험용 배포판”이다. 아직 온라인 패키지 관리자, 저장소 서명, 업그레이드,
완전한 무인 설치는 필수가 아니다.

단, Stage 1 후반부터 `ki2ctl` HTTP 패키지 관리자 preview를 포함한다. 이 preview는
정적 HTTP 서버의 `repo/index.x86_64.json`과 `.ki2` 파일을 사용해 검색, 의존성
해석, 다운로드, 설치 기록을 검증하기 위한 것이다.

## Stage 2: 운영 가능한 최소 서버 배포판

목표: 반복 설치, 패키지 설치/업데이트, 원격 운영이 가능한 최소 서버 OS가 된다.

필수 기능:

- 온라인 패키지 관리자 `ki2ctl install/update/upgrade/remove`
- 런타임 의존성 자동 해석
- 설치된 시스템 패키지 DB: `/var/lib/ki2/`
- 파일 충돌 탐지와 설치 트랜잭션 기록
- 저장소 메타데이터 서명과 검증
- 패키지 충돌 탐지
- 패키지 install/remove hook 정책
- SSH 원격 운영 기본값
- `systemd-networkd` 기반 DHCP/static 설정
- 무인 설치 YAML
- disconnected 설치용 로컬 저장소/ISO
- 설치 로그와 설치 계획서 보존
- Go 기반 설치 계획서 TUI를 실제 주 설치기로 승격
- 빌드 웹 콘솔에서 패키지/프로파일 단위 빌드
- ISO와 패키지 저장소 정적 배포

Stage 2의 완료 기준:

- 새 VM을 무인 설치할 수 있음
- 네트워크 저장소에서 패키지를 설치할 수 있음
- disconnected 환경에서도 ISO 또는 로컬 mirror로 설치 가능
- 패키지 업데이트 후 롤백 또는 복구 경로가 있음
- 기본 보안 검사와 repo 서명 검증이 있음
- 운영자가 문서만 보고 서버 노드를 재현할 수 있음

Stage 2는 “내부 서버용 최소 배포판”이다. 쿠버네티스 노드 준비가 시작되지만,
클러스터 전체 운영 자동화는 Stage 3의 영역이다.

## 패키지와 확장 정책

KIKI OS는 코어 OS와 확장 애플리케이션을 분리한다.

- `ki2`: 커널, initramfs, systemd, dbus, 로그인, 네트워크, sudo, ssh,
  `ki2ctl`, CRI-O/kubelet처럼 OS 생존과 부팅에 직접 필요한 구성요소를 관리한다.
- `CRI-O`: Kubernetes가 pod를 실행하는 표준 CRI 런타임으로 둔다.
- `Podman`: Stage 2 이후 로컬 운영 도구, 개발 도구, 관리 UI, 확장 서비스 실행용
  OCI 런타임으로 추가한다.
- 데스크톱 환경: GNOME 같은 전체 데스크톱 세션은 컨테이너가 아니라 별도
  `desktop-gnome` 계열 ki2 프로파일로 다룬다.
- GUI 애플리케이션: 데스크톱 위에서 실행되는 앱은 Podman/OCI app bundle 또는
  향후 Flatpak 계열 모델로 분리한다.

이 정책의 목적은 코어 OS를 작고 복구 가능하게 유지하면서, 사용자가 원하는
확장 기능은 OCI 이미지나 별도 프로파일로 빠르게 추가할 수 있게 하는 것이다.

## Stage 3: 자기 빌드와 클러스터 운영 배포판

목표: KIKI OS가 자기 패키지를 안정적으로 빌드하고, 쿠버네티스/클라우드 노드를
운영할 수 있는 독립 배포판이 된다.

필수 기능:

- target sysroot toolchain 완성
- 2-stage 또는 3-stage bootstrap 체인
- KIKI OS 내부에서 KIKI 패키지 빌드
- signed repository 운영
- 패키지 업그레이드/롤백 정책
- 커널과 initramfs 업데이트 정책
- CRI-O 기반 쿠버네티스 노드 프로파일
- `kubelet`, `kubeadm`, `kubectl`, CNI, CRI 도구 패키징
- 클러스터용 sysctl, cgroup v2, 네트워크 기본값
- `nftables`, `iptables-nft`, `conntrack-tools`, `firewalld` 선택 프로파일
- 웹 기반 설치기 또는 원격 설치 UI
- PXE 또는 네트워크 부팅 설치
- 빌드 서버, mirror, release 채널 운영
- 보안 업데이트와 취약점 추적

Stage 3의 완료 기준:

- KIKI OS 위에서 KIKI OS 패키지를 빌드할 수 있음
- 쿠버네티스 bootstrap/control/compute 노드를 설치 계획서로 만들 수 있음
- 릴리스 채널과 서명된 저장소를 운영할 수 있음
- 패키지 업데이트, 커널 업데이트, 복구 절차가 문서화되어 있음
- 실험용 VM을 넘어 실제 lab 인프라 노드로 운영 가능

Stage 3은 “독립 서버/클러스터 배포판”이다.

## 단계별 네트워크 정책

- Stage 1: `systemd-networkd` DHCP 기본값
- Stage 2: DHCP와 static IP를 설치 계획서에서 선택
- Stage 3: 쿠버네티스 노드, PXE, mirror, CNI와 연동

`NetworkManager`는 기본값이 아니다. 데스크톱, Wi-Fi, VPN, 사용자 중심 GUI가
필요한 프로파일에서 선택 패키지로 추가한다.

## 단계별 설치기 정책

- Stage 1: C 기반 콘솔 메뉴형 TUI가 실제 설치를 담당하고, Go 기반 `kiki-installer-tui`는 preview/테스트용으로 포함
- Stage 2: Go 기반 선언형 설치 계획서 TUI를 주 설치기로 승격, 무인 설치, disconnected 설치
- Stage 3: 웹 기반 설치기, 원격 설치, PXE/네트워크 설치

현재 C 기반 stage-1 `/init`은 계속 유지한다. Go TUI는 Stage 1부터 패키지와
테스트 대상으로 포함하지만, 부팅 초기 신뢰 경로를 흔들지 않기 위해 설치 ISO의
첫 진입점은 아직 C `/init`으로 둔다. 이 구조는 향후 웹 기반 설치기와 같은
설치 계획서 엔진을 공유하기 위한 전환 단계다.

## 단계별 swap 정책

- Stage 1 일반 설치: ESP + swap + root를 만들고, fstab은 `LABEL=KIKI_*`와
  `nofail` 옵션을 사용해 systemd 부팅 실패를 줄인다.
- Stage 2 서버 설치: 설치 계획서에서 swap on/off를 명시하고, VM/베어메탈
  메모리 용량에 따른 기본값을 조정한다.
- Stage 3 Kubernetes 노드: 기본값은 swap off이다. kubelet swap 지원을 켜는
  경우에만 별도 계획서 옵션으로 허용한다.

## 현재 판단

현재 KIKI OS는 Stage 1 마무리 단계에 있다. 부팅 ISO, 설치 ISO, 패키지 추출,
기본 systemd 유닛, 사용자 생성, DHCP 계획서, Go TUI preview, 디스크 편집 메뉴,
설치 후 점검 명령까지 연결되어 있다. 다음 큰 전환점은 Stage 2의 온라인 패키지
관리자 안정화, 설치된 시스템 패키지 DB, 저장소 서명, Go 기반 주 설치기다.

## Stage 1 마무리 메모

2026-05-26 기준으로 Stage 1은 "VM에서 설치 가능한 systemd 기반 최소 서버 OS"를
증명하는 단계로 정리한다. 이 단계의 목표는 완성형 운영 배포판이 아니라, 부팅,
설치, 로그인, 네트워크, systemd 서비스, 패키지 추출 경로가 한 사이클로 이어지는지
확인하는 것이다.

Stage 1에서 완료로 보는 항목:

- BIOS/MBR 및 UEFI 개발용 ISO 부팅 경로
- C 기반 stage-1 `/init` 설치기와 콘솔 메뉴형 TUI
- 자동 파티션 구성: ESP + swap + root
- 수동 디스크 편집: `cfdisk`/`fdisk` 실행 후 ESP/root/swap 후보 입력
- `.ki2` 패키지 미디어를 ISO에 포함하고 선택 패키지를 대상 rootfs로 추출
- 기본 사용자 `kiki` 생성, root 직접 로그인 잠금, sudo 사용 가능
- `systemd` PID 1 부팅, `dbus`, `systemd-logind`, getty, sshd 기본 실행
- `systemd-networkd` DHCP 기본 네트워크와 `systemd-resolved` 구성
- label 기반 fstab: `KIKI_ROOT`, `KIKI_EFI`, `KIKI_SWAP`
- `bash` 런타임 의존성에 `ncurses/libtinfo` 포함
- `sshd.service`에서 `ssh-keygen -A`로 host key 자동 생성
- `cfdisk`, `ncurses`, `ki2ctl`, `kiki-agent`, Go 기반 `kiki-installer-tui` preview 포함
- 설치 후 `kiki-stage1-check`로 기본 상태를 점검할 수 있는 기반

Stage 1에서 의도적으로 완료로 보지 않는 항목:

- 온라인 패키지 관리자 전체 기능과 설치된 시스템 패키지 DB
- 저장소 서명, 패키지 서명, 릴리스 채널 운영
- 안정적인 upgrade/remove/rollback 정책
- 무인 설치, disconnected mirror 설치, PXE 설치
- Go 기반 설치 계획서 TUI의 주 설치기 승격
- CRI-O, CNI, kubelet, kubeadm, kubectl의 실제 빌드 패키지
- nftables, iptables, conntrack-tools, firewalld의 실제 네트워크 운영 패키지
- KIKI OS 안에서 KIKI OS를 다시 빌드하는 self-hosting toolchain

Stage 2 진입 조건:

- Stage 1 ISO로 VM 설치와 로그인, sudo, systemctl, networkctl, sshd 동작을 반복 검증한다.
- 새 오류는 Stage 1 안정화 버그로 처리하되, 기능 범위 확장은 Stage 2 작업으로 넘긴다.
- Stage 2의 첫 목표는 `ki2ctl` 온라인 설치 흐름, 설치된 패키지 DB,
  CRI-O 기반 쿠버네티스 노드 준비 패키지, Go 기반 설치 계획서 TUI 승격이다.
