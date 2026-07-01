# KIKI OS Stage 3 V3 전환 계획

`stage3-v3`는 KIKI OS를 “Kubernetes 노드 준비가 가능한 최소 서버 OS”에서
“자기 빌드와 클러스터 운영 자동화가 가능한 독립 배포판”으로 끌어올리는 단계다.

## 전환 기준

Stage 2 V2는 다음 상태로 닫는다.

- `stage2-v2` 저장소 metadata와 channel 생성 가능
- `.ki2` 패키지 62개 기준 저장소 인덱스 생성
- `ki2ctl` HTTP/local mirror/disconnected 설치 흐름 검증
- CRI-O 기본, containerd 선택 Kubernetes 노드 프로파일 검증
- `kiki-kubeadm` 기반 kubeadm init/join 렌더링과 guard 실행기 검증
- `kiki-netconfig` 기반 DHCP/Static/Off 네트워크 설정 도구 포함
- 최신 Stage 2 ISO: `dist/iso/kiki-stage2-v2-installer-x86_64-20260612-rev8.iso`

Stage 3부터는 Stage 2 기능을 깨지 않는 범위에서 self-hosting, 클러스터 자동화,
원격 설치, 보안 업데이트 운영을 추가한다.

## 목표

Stage 3의 목표는 다음과 같다.

1. KIKI OS 내부에서 KIKI OS 패키지를 다시 빌드할 수 있다.
2. 설치 계획서만으로 Kubernetes bootstrap/control/compute 노드를 구성할 수 있다.
3. `kubeadm init`과 `kubeadm join`을 자동화하되, 토큰/CA hash/인증서 처리를 명확히 분리한다.
4. 원격 YAML unattended 설치 계획서를 가져와 검증하고 실행할 수 있다.
5. PXE 또는 네트워크 부팅 설치 경로를 설계한다.
6. 공개키 기반 저장소 서명과 릴리스 채널 운영으로 전환한다.
7. 패키지 업그레이드, 롤백, 커널/initramfs 업데이트 정책을 문서화한다.

## 1차 작업 큐

Stage 3 초입의 작업 순서는 다음을 권장한다.

1. `kiki-kubeadm` 운영 연결
   - Stage 2의 `kiki-kubeadm render|init|join` 실행기를 첫 부팅 자동화 경로에 연결한다.
   - bootstrap 노드는 `kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml`을 안전하게 1회 실행한다.
   - control/compute 노드는 endpoint/token/CA hash 입력이 검증된 뒤 `kubeadm join`을 실행한다.
   - 실행 결과와 로그를 `/var/log/kiki/kubeadm.log`와 `/var/lib/kiki/kubernetes/state.json` 기준으로 수집한다.

2. `kiki-agent`와 Kubernetes 후처리 연결
   - 첫 부팅 후 `kiki-agent kube reconcile` 같은 명령으로 kubeadm 실행기를 호출한다.
   - kubelet 상태, CRI socket, CNI 디렉터리, node join 상태를 점검한다.
   - 실패 시 재시도 가능하지만 destructive 재초기화는 명시 옵션으로만 허용한다.

3. CNI 적용 정책
   - Stage 3 초기 기본값은 CNI manifest를 자동 적용하지 않는다.
   - bootstrap 계획서에 `kubernetes.cni.provider`와 `manifest_url`이 있을 때만 적용한다.
   - disconnected 환경에서는 ISO/local mirror 안의 manifest 경로를 사용한다.

4. 원격 YAML unattended executor
   - `kiki.plan.url=http://.../install-plan.yaml` 같은 커널 파라미터를 정의한다.
   - 다운로드, signature/hash 검증, 스키마 검증 후 설치한다.
   - initramfs C `/init`에 전체 YAML 파서를 넣지 않고, Stage 3 executor 바이너리 또는 Python 도구로 분리한다.

5. source-backed build 승격
   - `network userspace`의 `host-files` 패키징을 source-backed 또는 reproducible upstream artifact로 전환한다.
   - CRI-O/conmon/crun/containerd/kubernetes 바이너리 패키지를 단계적으로 재현 빌드한다.
   - unpinned core recipe hash를 줄인다.

6. 저장소 보안 전환
   - 개발용 `hmac-sha256` metadata signing을 공개키 기반 서명으로 교체한다.
   - root trust store와 key rotation 정책을 정의한다.
   - `ki2ctl update --require-signature`를 운영 기본값으로 승격한다.

## Kubernetes 자동화 경계

Stage 3에서 자동화할 것:

- kubeadm local config 렌더링
- bootstrap/control/compute 역할별 `init`/`join` 실행
- token/CA hash 입력값 검증
- CRI-O/containerd endpoint 검증
- kubelet 상태 확인
- CNI 적용 옵션화

Stage 3에서도 조심할 것:

- control-plane 인증서 배포는 명시적인 계획서 입력 없이는 자동화하지 않는다.
- 기존 클러스터 reset은 기본 제공하지 않는다.
- CNI manifest 자동 적용은 사용자가 명시한 provider/manifest에 한정한다.

## 완료 기준

Stage 3 V3 완료 기준은 다음이다.

- KIKI OS 안에서 최소 패키지 재빌드 smoke가 통과한다.
- `kiki-kubeadm init`이 단일 노드 control-plane을 구성한다.
- `kiki-kubeadm join --role compute`가 기존 bootstrap 노드에 join한다.
- disconnected ISO/local mirror 환경에서 같은 흐름을 재현한다.
- 원격 YAML unattended 설치가 signature/hash 검증 후 실행된다.
- 저장소 metadata가 공개키 기반 서명으로 검증된다.
- 운영자가 문서만 보고 bootstrap/control/compute 노드 3대를 재현할 수 있다.

## Stage 2 호환성 원칙

Stage 3 작업 중에도 다음은 깨지면 안 된다.

- Stage 1 설치 ISO 부팅과 디스크 설치
- `minimal-systemd` 로그인, sudo, systemd, dbus, networkd
- `ki2ctl` HTTP/local mirror 설치 흐름
- `stage2-v2` 저장소 metadata와 패키지 인덱스 검증
- `kiki-kube-*` 프로파일의 CRI-O/containerd 분리
