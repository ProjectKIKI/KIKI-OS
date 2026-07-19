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
