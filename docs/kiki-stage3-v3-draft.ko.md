# KIKI OS 3단계 V3 초안

이 문서는 3단계 V3의 초기 설계 초안이다. 2단계 V2는 패키지 저장소, 설치 계획서,
CRI 런타임, Kubernetes 역할별 패키지, `kiki-kubeadm init/join` 실행기까지 완료한
상태로 닫았다. 3단계는 이 기반 위에서 “클러스터를 자동 구성하고 운영할 수 있는
독립 배포판”으로 확장한다.

## 3단계 목표

3단계의 목표는 다음 다섯 가지다.

1. 기본 설정과 사용자 재정의를 분리한다.
2. Kubernetes 없는 일반 서버 OS 프로파일 `server-core`를 제공한다.
3. `bootstrap`, `control`, `compute` 노드를 설치 계획서만으로 구성한다.
4. `kiki-agent`가 첫 부팅 후 kubeadm, CNI, 상태 보고를 조정한다.
5. 원격 YAML 설치 계획서와 저장소 서명을 검증하고 실행한다.

3단계는 “무조건 모든 것을 자동 실행”하는 단계가 아니다. 파괴적 작업은 기본값으로
막고, 사용자가 설치 계획서에 명시한 경우에만 실행한다.

## 기준 노드 모델

3단계의 일반 서버 프로파일은 다음과 같다.

- `server-core`: Kubernetes 없이 SSH, systemd, dbus, networkd/resolved, sudo, `ki2ctl`,
  `kiki-netconfig`, nftables/firewalld, chrony, 기본 디스크/진단 도구를 제공한다.

역할은 2단계와 동일하게 유지한다.

- `bootstrap`: 최초 컨트롤 플레인 노드. `kubeadm init` 대상이다.
- `control`: 추가 컨트롤 플레인 노드. 검증된 토큰, CA 해시, 엔드포인트가 있을 때 `kubeadm join --control-plane` 대상이다.
- `compute`: 워커 노드. 검증된 토큰, CA 해시, 엔드포인트가 있을 때 일반 `kubeadm join` 대상이다.

테스트 기준 구성은 세 단계로 나눈다.

- 1대: `bootstrap` 단일 노드 컨트롤 플레인 스모크
- 2대: `bootstrap` + `compute` 최소 분리 스모크
- 3대: `bootstrap` + `control` + `compute` 역할 전체 스모크

운영 권장 고가용성 구성은 3단계 후반 기준으로 `bootstrap` 1대, `control` 2대 이상,
`compute` N대다.

## 설정 계층

3단계는 기본 설정 파일을 배포판이 제공하고, 사용자가 필요한 값만 재정의하는 형태로
구성한다.

우선순위는 낮은 값에서 높은 값 순서로 다음과 같다.

1. 배포판 기본값: `/usr/share/kiki/defaults/*.yaml`
2. 역할 기본값: `/usr/share/kiki/profiles/<profile>.yaml`
3. 설치 계획서: `/var/lib/ki2/install-plan.yaml`
4. 로컬 재정의: `/etc/kiki/overrides/*.yaml`
5. 일회성 실행 인자: CLI 플래그 또는 커널 파라미터

병합 규칙은 단순해야 한다.

- map은 key 단위로 병합한다.
- 스칼라 값은 높은 우선순위 값이 덮어쓴다.
- 목록은 기본적으로 교체한다.
- 목록 병합이 필요한 항목은 명시적으로 `merge_strategy: append`를 둔다.
- 비밀번호, 토큰, CA 키 같은 비밀값은 평문 계획서에 저장하지 않는다.

## 기본 파일 배치

3단계의 기본 파일 배치는 다음을 초안 기준으로 둔다.

```text
/usr/share/kiki/defaults/system.yaml
/usr/share/kiki/defaults/kubernetes.yaml
/usr/share/kiki/defaults/network.yaml
/usr/share/kiki/profiles/bootstrap.yaml
/usr/share/kiki/profiles/control.yaml
/usr/share/kiki/profiles/compute.yaml
/etc/kiki/overrides/system.yaml
/etc/kiki/overrides/kubernetes.yaml
/etc/kiki/overrides/network.yaml
/var/lib/ki2/install-plan.yaml
/var/lib/kiki/rendered/stage3-plan.yaml
/var/lib/kiki/kubernetes/state.json
/var/log/kiki/stage3.log
```

`/usr/share/kiki` 아래 파일은 패키지가 소유한다. `/etc/kiki/overrides` 아래 파일은 운영자가
소유한다. `/var/lib/kiki/rendered` 아래 파일은 실제 실행 직전의 최종 병합 결과다.

## Kubernetes 실행 흐름

3단계의 kubeadm 흐름은 다음 순서로 진행한다.

1. `kiki-agent kube reconcile` 실행
2. 설치 계획서와 재정의 병합
3. CRI 소켓, kubelet 유닛, swap 정책 점검
4. `kiki-kubeadm render` 실행
5. 역할별 보호 조건 확인
6. `bootstrap`이면 `kiki-kubeadm init`
7. `control` 또는 `compute`이면 `kiki-kubeadm join`
8. kubelet 상태 확인
9. 선택된 CNI 적용
10. 상태 파일과 하트비트 보고

`join`은 다음 값이 모두 있어야 실행한다.

- `kubernetes.cluster.control_plane_endpoint`
- `kubernetes.join.token`
- `kubernetes.join.ca_cert_hash`

`control` 역할은 추가로 컨트롤 플레인 인증서 전달 방식이 명시되어야 한다. 3단계 초안의
기본값은 “자동 전달하지 않음”이다.

## CNI 정책

3단계 초기 기본값은 CNI를 자동 적용하지 않는다. 자동 적용은 다음 조건이 모두 참일 때만
허용한다.

- `kubernetes.cni.enabled: true`
- `kubernetes.cni.provider`가 허용 목록에 있음
- `manifest_url`, `manifest_path`, 또는 `package` 중 하나가 명시됨
- 오프라인 설치라면 로컬 미러 또는 ISO 안에서 매니페스트를 찾을 수 있음

초기 허용 공급자 후보는 다음이다.

- `flannel`: 단순 스모크용
- `calico`: 운영 검토용
- `cilium`: 3단계 후반 검토

## 원격 설치 계획서

3단계의 원격 YAML 설치 계획서는 다음 커널 파라미터로 시작한다.

```text
kiki.plan.url=http://repo.example/kiki/install-plan.yaml
kiki.plan.sha256=<sha256>
kiki.plan.signature=<url-or-inline-ref>
```

실행 규칙은 다음과 같다.

- URL만 있고 해시 또는 서명이 없으면 실행하지 않는다.
- 다운로드한 계획서는 `/run/kiki/remote-install-plan.yaml`에 둔다.
- 검증을 통과한 계획서만 `/run/kiki/install-plan.yaml`로 승격한다.
- initramfs C `/init`은 전체 YAML 파싱을 담당하지 않는다.
- 3단계 실행기가 검증, 병합, 실행 여부 판단을 담당한다.

## 보안 경계

3단계에서 기본 차단할 작업은 다음이다.

- 기존 클러스터 `kubeadm reset`
- 기존 `/etc/kubernetes/pki` 삭제
- 컨트롤 플레인 인증서 자동 복사
- CNI 매니페스트 무조건 적용
- 검증되지 않은 원격 설치 계획서 실행
- 서명되지 않은 저장소 메타데이터 사용

운영자가 명시적으로 허용해야 하는 값은 다음처럼 별도 필드로 둔다.

```yaml
safety:
  allow_cluster_reset: false
  allow_unsigned_repository: false
  allow_unverified_remote_plan: false
  allow_control_plane_cert_upload: false
```

## 1차 구현 순서

3단계 초입 구현 순서는 다음이 적절하다.

1. `kiki-stage3-config-v1` 스펙 확정
2. 기본 설정 파일과 override 병합 도구 추가
3. `kiki-agent kube reconcile --dry-run` 추가
4. `kiki-agent kube reconcile`에서 `kiki-kubeadm render` 호출
5. 부트스트랩 단일 노드 `init` 스모크
6. 컴퓨트 노드 `join --dry-run` 스모크
7. 원격 YAML 설치 계획서 검증 도구 추가
8. CNI 매니페스트 적용을 명시 옵션으로 추가
9. 3단계 검증기 `tools/ki2stage3.py` 추가

## 완료 기준 초안

3단계 V3 완료 기준은 다음으로 둔다.

- `bootstrap` 1대가 `kiki-agent kube reconcile`로 컨트롤 플레인을 만든다.
- `compute` 역할 1대가 검증된 토큰/CA 해시/엔드포인트로 조인한다.
- `control` 역할 1대가 명시된 인증서 정책 아래 컨트롤 플레인으로 조인한다.
- 원격 YAML 설치 계획서가 해시 또는 서명 검증 후 실행된다.
- 기본 설정과 재정의 병합 결과가 `/var/lib/kiki/rendered/stage3-plan.yaml`에 남는다.
- CNI는 사용자가 명시한 공급자와 매니페스트에 한정해 적용된다.
- 서명되지 않은 저장소 메타데이터는 기본 거부된다.
- 2단계 V2의 설치, 패키지 관리자, 로컬 미러, Kubernetes 패키지 검증은 계속 통과한다.
