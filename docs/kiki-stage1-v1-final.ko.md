# KIKI OS 1단계 V1 최종 문서

`stage1-v1`은 KIKI OS의 첫 번째 완료 기준선이다. 이 문서는 1단계에서
완료로 보는 범위, 유지 정책, 검증 절차를 고정한다. 이후 작업에서 기능을 더하는
경우에는 1단계를 확장하지 않고 `stage2-v2` 진행 문서로 넘긴다.

## 상태

- 릴리스 라인: `stage1-v1`
- 상태: 최종 기준선
- 목적: VM에서 부팅, 설치, 로그인, 기본 systemd 운영까지 한 사이클로 검증
- 기본 프로필: `bootstrap-stage1`, `minimal-systemd`
- 산출물 이름 기준: 저장소 메타데이터가 없으면 `stage1-v1`을 사용
- 유지 방식: 버그 수정, 문서 정정, 재현성 보강만 허용

## 완료 범위

1단계 V1은 완성형 운영 배포판이 아니라 “설치 가능한 최소 systemd OS”의
증명이다. 다음 항목은 1단계 V1에 포함한다.

- BIOS/MBR 및 UEFI 개발용 ISO 부팅 경로
- C 기반 시스템 호출 전용 1단계 `/init`
- 콘솔 메뉴형 TUI 설치기
- KIKI 로고 출력
- 자동 파티셔닝: ESP + swap + root
- 수동 파티셔닝: `cfdisk` 또는 `fdisk` 실행 후 설치 단계에서 파티션 입력
- `.ki2` 패키지 미디어 검사와 선택 패키지 루트 파일시스템 추출
- 기본 사용자 `kiki` 생성
- root 직접 로그인 잠금
- `sudo` 사용 가능
- `systemd` PID 1 부팅
- `dbus`, `systemd-logind`, getty, sshd 기본 실행
- `systemd-networkd` DHCP 기본 네트워크
- `systemd-resolved` 기본 DNS 구성
- label 기반 fstab: `KIKI_ROOT`, `KIKI_EFI`, `KIKI_SWAP`
- swap 실패가 긴급 모드로 이어지지 않도록 `nofail` 정책 적용
- SSH 호스트 키 자동 생성
- 설치 후 `kiki-stage1-check` 기본 점검
- Go 기반 `kiki-installer-tui` 미리보기 패키지 포함

## 완료로 보지 않는 범위

다음 항목은 1단계 V1의 완료 범위가 아니다. 구현이 시작되어 있어도 2단계
또는 3단계 작업으로 관리한다.

- 온라인 패키지 관리자 전체 기능
- 설치된 시스템 패키지 DB의 안정화
- 저장소 서명과 키 운영
- 패키지 업그레이드/삭제/롤백 정책
- 무인 설치
- 오프라인 미러 설치
- PXE 또는 네트워크 부팅 설치
- Go TUI를 단독 설치기로 승격
- CRI-O, CNI, kubelet, kubeadm, kubectl의 2/3단계 패키징
- Kubernetes 부트스트랩/컨트롤/컴퓨트 노드 자동 가입
- KIKI OS 안에서 KIKI OS를 다시 빌드하는 자체 빌드 도구체인

## 유지 정책

1단계 V1에는 새 기능을 계속 추가하지 않는다. 새 요구사항이 들어오면 다음
기준으로 처리한다.

- 부팅 실패, 설치 실패, 로그인 실패: 1단계 V1 안정화 버그
- 문서와 실제 동작 불일치: 1단계 V1 문서 정정
- 패키지 관리자, 저장소, Kubernetes, 무인 설치: 2단계 V2 작업
- 자체 빌드, 클러스터 운영 자동화, 웹 설치기: 3단계 후보

이 기준을 두는 이유는 1단계를 계속 늘리면 부팅/설치 기준선이 흔들리기
때문이다. 1단계는 작고 반복 검증 가능한 상태로 보존한다.

## 검증 체크리스트

1단계 V1 ISO 또는 디스크 이미지는 다음 흐름으로 검증한다.

1. BIOS/MBR VM 부팅
2. UEFI VM 부팅
3. 설치기 메뉴 진입
4. 자동 파티션 설치
5. 수동 파티션 설치 또는 `cfdisk` 실행 확인
6. 설치된 디스크로 재부팅
7. `kiki` 사용자 로그인
8. `sudo -i` 동작 확인
9. `systemctl status` 기본 동작 확인
10. `networkctl` DHCP 링크 확인
11. `systemd-logind` 동작 확인
12. `sshd.service` 기동 확인
13. `kiki-stage1-check` 실행

## 개발 명령

1단계 V1 관련 기본 검증 명령:

```bash
python tools/ki2build.py validate --profile distro/profiles/bootstrap-stage1.toml --max-packages 64
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py rootfs --profile distro/profiles/bootstrap-stage1.toml --rootfs-dir dist/rootfs/bootstrap-stage1
python tools/ki2bootiso.py --profile bootstrap-stage1 --mode installer --release-name stage1-v1
```

ISO 생성을 요청하지 않은 일반 작업에서는 마지막 명령을 실행하지 않는다.

## 2단계로 넘기는 기준

다음 작업은 `stage2-v2` 완료 문서와 3단계 계획에서 관리한다.

- `ki2ctl` 온라인 설치 흐름
- HTTP 저장소 메타데이터와 채널 운영
- 저장소 서명
- Go TUI 설치 계획서 단독 설치기 승격
- Kubernetes 패키지 프로파일
- CRI-O/containerd 런타임 선택
- 부트스트랩/컨트롤/컴퓨트 노드 역할
- 오프라인 설치
- 빌드 웹 콘솔 운영

1단계 V1은 이 흐름의 안전한 출발점이다.
