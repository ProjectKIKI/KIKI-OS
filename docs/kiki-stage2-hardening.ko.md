# KIKI OS 2단계 보강 메모

이 문서는 2단계를 Kubernetes 노드 준비용 배포판 기준선으로 닫기 위해 추가한
보강 항목을 정리한다.

## 1. 저장소 신뢰 정책

`ki2ctl`은 이제 저장소 설정에 검증키 경로를 저장할 수 있다.

```bash
ki2ctl repo set http://repo.example.internal:8080 \
  --verify-key /etc/ki2/trust/stage2-v2-repo.hmac
ki2ctl update
```

`update`는 다음 순서로 검증키를 찾는다.

1. `ki2ctl update --verify-key <path>`로 직접 지정한 키
2. `ki2ctl repo set --verify-key <path>`에 저장된 키
3. `/etc/ki2/trust/<repo-name>.hmac`
4. `/etc/ki2/trust/stage2-v2-repo.hmac`

운영 저장소에서는 다음처럼 서명 검증을 강제한다.

```bash
ki2ctl update --require-signature
```

개발/격리 환경에서만 다음 옵션으로 검증을 끌 수 있다.

```bash
ki2ctl update --no-verify
```

현재 2단계 서명 알고리즘은 `hmac-sha256`이다. 공개키 기반 서명과 키 교체 정책은
3단계의 저장소 보안 항목으로 승격한다.

## 2. 패키지 제거 안정성

`ki2ctl remove`는 이제 설치된 다른 패키지가 의존하는 패키지를 기본적으로 제거하지
않는다.

```bash
ki2ctl remove containerd
```

위 명령은 `kube-node-config-containerd` 같은 설치된 패키지가 `containerd`에 의존하면
실패한다. 실험 환경에서 강제로 제거해야 할 때만 다음 옵션을 쓴다.

```bash
ki2ctl remove containerd --force
```

제거 작업도 `/var/lib/ki2/transactions/*.json`에 기록된다. 제거 중 실패하면 가능한
범위에서 파일과 설치 DB를 이전 상태로 되돌린다.

## 3. 설치/제거 훅

설치 훅과 제거 훅을 구분하기 위해 대기 중인 훅 항목에 `phase` 필드를 추가했다.

- `post-install`: 공유 라이브러리, systemd 유닛, tmpfiles 설치 후 처리
- `post-remove`: 공유 라이브러리, systemd 유닛, tmpfiles 제거 후 처리

확인은 다음 명령으로 한다.

```bash
ki2ctl hooks list
ki2ctl hooks apply
```

대상 루트가 `/`가 아닌 경우 훅은 설치된 시스템 내부에서 적용하도록 지연된다.

## 4. kubeadm 로컬 설정 렌더링

`tools/ki2kubeadm.py`는 2단계 설치 계획서와 kubeadm 템플릿을 이용해
`kubeadm.local.yaml`을 만든다.

부트스트랩 노드 예시:

```bash
python tools/ki2kubeadm.py \
  --plan distro/install-plans/kiki-kube-bootstrap-containerd.yaml \
  --root /mnt/target \
  --node-name cp-01
```

컴퓨트 노드 조인 예시:

```bash
python tools/ki2kubeadm.py \
  --plan distro/install-plans/kiki-kube-compute-containerd.yaml \
  --root /mnt/target \
  --node-name worker-01 \
  --endpoint 10.0.0.10:6443 \
  --token abcdef.0123456789abcdef \
  --ca-cert-hash sha256:<64-hex>
```

join 렌더링은 `--endpoint`, `--token`, `--ca-cert-hash`가 없으면 실패한다. 실험용으로
자리표시자를 허용해야 할 때만 `--allow-placeholders`를 사용한다.

## 5. 2단계 검증 강화

다음 검증 범위가 강화되었다.

- `tools/test_ki2ctl.py`
  - repo 설정에 저장된 검증 키로 메타데이터 자동 검증
  - `--require-signature` 실패 경로
  - 역의존성 제거 차단
  - 제거 트랜잭션 기록
- `tools/test_ki2kubeadm.py`
  - kubeadm join 필수값 검증
  - CRI-O 컴퓨트 join 렌더링
  - containerd 부트스트랩 init 렌더링
- `tools/ki2stage2.py verify-kubernetes`
  - kubeadm 렌더러 스모크 포함
- `tools/ki2stage2.py verify-package-manager`
  - Kubernetes containerd 노드 설정 설치 흐름 확인
  - runtime 패키지 제거 차단 확인

## 6. 남은 2단계/3단계 경계

2단계 기준선은 다음 조건을 충족해야 한다.

- 서명된 저장소 메타데이터 검증 경로가 기본 운영 흐름에 포함된다.
- CRI-O와 containerd Kubernetes 프로파일을 모두 설치 계획서로 검증한다.
- 부트스트랩/컨트롤/컴퓨트 역할의 kubeadm 템플릿을 로컬 설정으로 렌더링할 수 있다.
- 패키지 제거는 역의존성과 트랜잭션을 고려한다.
- HTTP 저장소와 오프라인 로컬 미러 설치 흐름이 모두 동작한다.

3단계로 넘길 항목은 다음과 같다.

- 공개키 기반 저장소 서명
- CRI-O, containerd, Kubernetes 바이너리의 소스 기반 빌드 전환
- CNI 실제 배포 자동화
- kubeadm 토큰/CA 해시 발급과 컨트롤 플레인 인증서 배포 자동화
- 원격 YAML 무인 설치 실행기
