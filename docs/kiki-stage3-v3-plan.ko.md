# KIKI OS 3단계 V3 전환 계획

`stage3-v3`는 KIKI OS를 “Kubernetes 노드 준비가 가능한 최소 서버 OS”에서
“자체 빌드와 클러스터 운영 자동화가 가능한 독립 배포판”으로 끌어올리는 단계다.

초기 설계 초안과 설정 계약은 [KIKI OS 3단계 V3 초안](kiki-stage3-v3-draft.ko.md)과
[`kiki-stage3-config-v1`](../distro/specs/kiki-stage3-config-v1.yaml)을 기준으로 시작한다.

## 전환 기준

2단계 V2는 다음 상태로 닫는다.

- `stage2-v2` 저장소 메타데이터와 채널 생성 가능
- `.ki2` 패키지 62개 기준 저장소 인덱스 생성
- `ki2ctl` HTTP/로컬 미러/오프라인 설치 흐름 검증
- CRI-O 기본, containerd 선택 Kubernetes 노드 프로파일 검증
- `kiki-kubeadm` 기반 kubeadm init/join 렌더링과 보호 조건 실행기 검증
- `kiki-netconfig` 기반 DHCP/고정/비활성 네트워크 설정 도구 포함
- 최신 2단계 ISO: `dist/iso/kiki-stage2-v2-installer-x86_64-20260711-rev9.iso`

3단계부터는 2단계 기능을 깨지 않는 범위에서 자체 빌드, 클러스터 자동화,
원격 설치, 보안 업데이트 운영을 추가한다.

## 목표

3단계의 목표는 다음과 같다.

1. KIKI OS 내부에서 KIKI OS 패키지를 다시 빌드할 수 있다.
2. 설치 계획서만으로 Kubernetes 부트스트랩/컨트롤/컴퓨트 노드를 구성할 수 있다.
3. `kubeadm init`과 `kubeadm join`을 자동화하되, 토큰/CA 해시/인증서 처리를 명확히 분리한다.
4. 원격 YAML 무인 설치 계획서를 가져와 검증하고 실행할 수 있다.
5. PXE 또는 네트워크 부팅 설치 경로를 설계한다.
6. 공개키 기반 저장소 서명과 릴리스 채널 운영으로 전환한다.
7. 패키지 업그레이드, 롤백, 커널/initramfs 업데이트 정책을 문서화한다.

## 1차 작업 큐

3단계 초입의 작업 순서는 다음을 권장한다.

0. TUI와 init 경계 전환
   - Go 기반 `kiki-installer-tui`를 단순 미리보기에서 3단계 설치 계획서 작성기로 승격한다.
   - 화면에는 설치 계획서 상태, initramfs handoff, systemd PID 1 경계를 명확히 표시한다.
   - 설치된 OS의 initramfs `/init`은 루트 파일시스템을 마운트하고 `/usr/lib/systemd/systemd`를 PID 1로 실행하는 최소 handoff 역할로 축소한다.
   - 완전한 `systemd-initramfs` 전환은 별도 단계에서 다루되, 3단계 초입에서는 현재 C `/init`을 `systemd handoff` 계약으로 정리한다.

1. `kiki-kubeadm` 운영 연결
   - 2단계의 `kiki-kubeadm render|init|join` 실행기를 첫 부팅 자동화 경로에 연결한다.
   - 부트스트랩 노드는 `kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml`을 안전하게 1회 실행한다.
   - 컨트롤/컴퓨트 노드는 엔드포인트/토큰/CA 해시 입력이 검증된 뒤 `kubeadm join`을 실행한다.
   - 실행 결과와 로그를 `/var/log/kiki/kubeadm.log`와 `/var/lib/kiki/kubernetes/state.json` 기준으로 수집한다.

2. `kiki-agent`와 Kubernetes 후처리 연결
   - 첫 부팅 후 `kiki-agent kube reconcile` 같은 명령으로 kubeadm 실행기를 호출한다.
   - kubelet 상태, CRI 소켓, CNI 디렉터리, 노드 조인 상태를 점검한다.
   - 실패 시 재시도 가능하지만 파괴적 재초기화는 명시 옵션으로만 허용한다.

3. CNI 적용 정책
   - 3단계 초기 기본값은 CNI 매니페스트를 자동 적용하지 않는다.
   - 부트스트랩 계획서에 `kubernetes.cni.provider`와 `manifest_url`이 있을 때만 적용한다.
   - 오프라인 환경에서는 ISO/로컬 미러 안의 매니페스트 경로를 사용한다.

4. 원격 YAML 무인 설치 실행기
   - `kiki.plan.url=http://.../install-plan.yaml` 같은 커널 파라미터를 정의한다.
   - 다운로드, 서명/해시 검증, 스키마 검증 후 설치한다.
   - initramfs C `/init`에 전체 YAML 파서를 넣지 않고, 3단계 실행기 바이너리 또는 Python 도구로 분리한다.

5. 소스 기반 빌드 승격
   - 네트워크 사용자 공간의 `host-files` 패키징을 소스 기반 또는 재현 가능한 upstream 산출물 기반으로 전환한다.
   - CRI-O/conmon/crun/containerd/kubernetes 바이너리 패키지를 단계적으로 재현 빌드한다.
   - 고정되지 않은 코어 레시피 해시를 줄인다.

6. 저장소 보안 전환
   - 개발용 `hmac-sha256` 메타데이터 서명을 공개키 기반 서명으로 교체한다.
   - 루트 신뢰 저장소와 키 교체 정책을 정의한다.
   - `ki2ctl update --require-signature`를 운영 기본값으로 승격한다.

## 구현 진행 상황 (2026-08-22)

- [x] Stage 2 V2 기준선과 Stage 3 관리 플랫폼 기능 브랜치를 통합했다.
- [x] 배포판 기본값, 역할 프로필, 설치 계획서, 운영자 override, 일회성 인자를
  순서대로 병합하는 `internal/stage3` 설정 계층을 구현했다.
- [x] 병합 결과를 `0600`으로 기록하고 평문 토큰·비밀번호·개인키 필드를 제거한다.
- [x] `kiki-agent kube reconcile --dry-run`에서 역할과 보호 조건을 검증하고
  `kiki-kubeadm init|join` 렌더러를 호출한다.
- [x] compute 조인 dry-run을 실제 `kiki-kubeadm`과 연결해 kubeadm 설정 및 상태
  JSON 생성을 검증했다.
- [x] CNI는 허용 공급자와 URL/로컬 경로/패키지가 명시된 경우에만 계획하거나 적용한다.
- [x] `kiki.plan.url`과 `kiki.plan.sha256` 커널 파라미터를 읽는 원격 계획서
  다운로드·격리·SHA-256 검증·승격 흐름을 구현했다.
- [x] 원격 계획서 원문과 저장소 메타데이터의 Ed25519 공개키 서명 검증을
  구현하고, 설치된 `ki2ctl` 정책에서 서명 및 알고리즘을 기본 강제한다.
- [x] Go 의존성을 vendor로 고정하고 Stage 3 바이너리와 호환 래퍼, 기본 설정을
  포함하는 `kiki-agent` `.ki2` 패키지 빌드를 검증했다.
- [ ] 실제 VM에서 bootstrap 단일 노드 `kubeadm init` 스모크를 통과시킨다.
- [ ] compute/control 노드의 실제 join 스모크와 재시도/멱등성 정책을 검증한다.
- [x] 원격 계획서와 저장소 메타데이터의 공개키 서명 검증을 구현한다.
- [x] `tools/ki2stage3.py` 계약·compute 조인 dry-run 종합 검증기를 추가했다.
- [x] `tools/ki2stage3vm.py`와 고정 host key 기반 1대/2대/3대 실제 VM 검증
  매트릭스 및 예제 설정을 추가했다.
- [x] `ethtool 6.15`, `chrony 4.8`, `socat 1.8.1.3`, `bridge-utils 1.7.1`을 SHA-256으로
  고정한 upstream 소스 빌드로 승격하고, chrony 전용 시스템 계정과 디렉터리
  소유권을 추가했다. socat은 OpenSSL 기능을 유지하면서 릴리스 태그 시각으로
  빌드 시각을 고정하고, bridge-utils는 실제 `brctl`만 제공해 `iproute2`의
  `/usr/sbin/bridge` 파일 소유권과 충돌하지 않게 한다.
- [x] `libmnl 1.0.5`, `libnfnetlink 1.0.2`, `libnetfilter_conntrack 1.1.1`을
  KIKI 패키지로 추가하고, 그 sysroot를 사용해 `conntrack-tools 1.4.9`의 실제
  `conntrack` CLI를 빌드한다. 호스트 부트스트랩 glibc 계층만 명시적으로 제외한다.
- [x] `iptables 1.8.13`과 `nftables 1.1.6`을 SHA-256으로 고정한 upstream 소스
  빌드로 승격했다. `iptables` 기본 명령은 nft 백엔드에 연결하고 절대 심볼릭
  링크를 제거했으며, `nftables`는 readline CLI, JSON, xtables 기능을 유지한다.
  `GMP 6.3.0`, `Jansson 2.15.0`, `Readline 8.3`, `libnftnl 1.3.1`도 KIKI
  패키지와 sysroot 의존성으로 추가했다. 실제 빌드, nft 변환, ELF/RPATH,
  빌드 경로 누출, 패키지 파일 충돌 검사를 통과했다.
- [x] `firewalld 2.5.1`을 공식 GitHub 릴리스 SHA-256으로 고정한 소스 빌드로
  승격했다. 서버 패키지는 데몬, `firewall-cmd`, `firewall-offline-cmd`, systemd
  서비스, D-Bus 정책, 기본 zone/service 데이터와 Python 3.12 모듈을 제공한다.
  GTK 설정 도구와 애플릿은 서버 패키지에서 분리했으며, nftables 패키지에는
  upstream Python 바인딩을 추가했다. 이에 따라 레시피의 `host-files` 빌드 타입은
  0개다.
- [x] firewalld의 upstream 필수 의존성인 Python 3.12, D-Bus 1.14.10,
  GLib 2.84.4, GObject Introspection 1.84.0, `python3-dbus 1.4.0`,
  `python3-gobject 3.52.3`을 자체 패키지로 추가했다. 조합한 KIKI 패키지 루트에서
  GLib/GObject/Gio import와 격리된 D-Bus 세션 연결, nftables/iptables 실행,
  firewalld 서버 모듈 import 및 ELF RPATH·빌드 경로 누출 검사를 통과했다.
  최종 런타임 조합은 `.pyc`, 절대 심볼릭 링크, 정적 아카이브, 빌드 경로와
  ELF RPATH/RUNPATH가 모두 0건이며, 이를 위해 zlib·XZ·Expat·OpenSSL·Python
  기반 패키지의 정적 산출물과 빌드 메타데이터 정리를 레시피에 고정했다.
- [ ] 실제 KIKI OS VM의 systemd system bus에서 firewalld 서비스를 기동하고
  nftables 백엔드 적용 및 재기동 상태를 검증한다.
- [ ] 준비된 KIKI OS VM에서 1대/2대/3대 매트릭스를 실제 통과시키고 결과를 보관한다.

현재 소스 승격 패키지는 호스트 컴파일러와 개발 헤더를 부트스트랩 도구로 사용하되,
호스트 바이너리 자체는 복사하지 않는다. 완전한 자기 호스팅은 대상 sysroot의 개발
헤더와 정적 빌드 의존성 패키지를 확충한 뒤 동일 레시피를 sysroot 빌드로 재검증한다.

## Kubernetes 자동화 경계

3단계에서 자동화할 것:

- kubeadm 로컬 설정 렌더링
- 부트스트랩/컨트롤/컴퓨트 역할별 `init`/`join` 실행
- 토큰/CA 해시 입력값 검증
- CRI-O/containerd 엔드포인트 검증
- kubelet 상태 확인
- CNI 적용 옵션화

3단계에서도 조심할 것:

- 컨트롤 플레인 인증서 배포는 명시적인 계획서 입력 없이는 자동화하지 않는다.
- 기존 클러스터 reset은 기본 제공하지 않는다.
- CNI 매니페스트 자동 적용은 사용자가 명시한 공급자/매니페스트에 한정한다.

## 완료 기준

3단계 V3 완료 기준은 다음이다.

- KIKI OS 안에서 최소 패키지 재빌드 스모크가 통과한다.
- `kiki-kubeadm init`이 단일 노드 컨트롤 플레인을 구성한다.
- `kiki-kubeadm join --role compute`가 기존 부트스트랩 노드에 조인한다.
- 오프라인 ISO/로컬 미러 환경에서 같은 흐름을 재현한다.
- 원격 YAML 무인 설치가 서명/해시 검증 후 실행된다.
- 저장소 메타데이터가 공개키 기반 서명으로 검증된다.
- 운영자가 문서만 보고 부트스트랩/컨트롤/컴퓨트 노드 3대를 재현할 수 있다.

## 2단계 호환성 원칙

3단계 작업 중에도 다음은 깨지면 안 된다.

- 1단계 설치 ISO 부팅과 디스크 설치
- `minimal-systemd` 로그인, sudo, systemd, dbus, networkd
- `ki2ctl` HTTP/로컬 미러 설치 흐름
- `stage2-v2` 저장소 메타데이터와 패키지 인덱스 검증
- `kiki-kube-*` 프로파일의 CRI-O/containerd 분리
