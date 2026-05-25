# KIKI OS 개발 단계 정의

KIKI OS는 stage 1, stage 2, stage 3까지 진행한다. 각 stage는 “무엇이 되는가”를
기준으로 나눈다. 기능이 늘어날 때마다 이 문서를 기준으로 현재 작업이 어느
단계에 속하는지 판단한다.

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
- 자동 파티셔닝: ESP + swap + root
- 수동 파티셔닝: `fdisk`/`cfdisk` 후 ESP/root/swap 직접 지정
- `.ki2` 패키지를 rootfs로 추출
- 관리자 사용자 생성
- root 직접 로그인 잠금 기본값
- `systemd`, `dbus`, `systemd-logind`, getty 실행
- 기본 네트워크: `systemd-networkd` DHCP
- 선언형 YAML 설치 계획서 생성과 보존
- 설치 후 VM 재부팅 및 로그인 확인

Stage 1의 완료 기준:

- 설치 ISO로 VM 부팅 가능
- TUI에서 디스크 설치 가능
- 설치된 디스크로 재부팅 가능
- 일반 사용자로 로그인 가능
- `systemctl`, `journalctl`, `loginctl`, `networkctl`이 기본 동작
- DHCP 환경에서 네트워크 링크와 DNS 확인 가능

Stage 1은 “실험용 배포판”이다. 아직 온라인 패키지 관리자, 저장소 서명, 업그레이드,
완전한 무인 설치는 필수가 아니다.

## Stage 2: 운영 가능한 최소 서버 배포판

목표: 반복 설치, 패키지 설치/업데이트, 원격 운영이 가능한 최소 서버 OS가 된다.

필수 기능:

- 온라인 패키지 관리자 `ki2ctl install/update/remove`
- 런타임 의존성 자동 해석
- 설치된 시스템 패키지 DB: `/var/lib/ki2/`
- 저장소 메타데이터 서명과 검증
- 패키지 충돌 탐지
- 패키지 install/remove hook 정책
- SSH 원격 운영 기본값
- `systemd-networkd` 기반 DHCP/static 설정
- 무인 설치 YAML
- disconnected 설치용 로컬 저장소/ISO
- 설치 로그와 설치 계획서 보존
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
- 웹 기반 설치기 또는 원격 설치 UI
- PXE 또는 네트워크 부팅 설치
- 빌드 서버, mirror, release 채널 운영
- 보안 업데이트와 취약점 추적

Stage 3의 완료 기준:

- KIKI OS 위에서 KIKI OS 패키지를 빌드할 수 있음
- 쿠버네티스 worker/control-plane 노드를 설치 계획서로 만들 수 있음
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

- Stage 1: 콘솔 메뉴형 TUI
- Stage 2: 선언형 설치 계획서 기반 TUI, 무인 설치, disconnected 설치
- Stage 3: 웹 기반 설치기, 원격 설치, PXE/네트워크 설치

현재 C 기반 stage-1 `/init`은 계속 유지한다. 더 풍부한 UI는 stage-2 또는
stage-3의 사용자 공간에서 `dialog`, `whiptail`, 웹 UI 중 하나로 확장한다.

## 현재 판단

현재 KIKI OS는 Stage 1 후반에 있다. 부팅 ISO, 설치 ISO, 패키지 추출, 기본
systemd 유닛, 사용자 생성, DHCP 계획서까지 연결되어 있다. 다음 큰 전환점은
Stage 2의 온라인 패키지 관리자와 설치된 시스템 패키지 DB다.
