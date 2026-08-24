# KIKI OS Stage 3 VM 검증

`tools/ki2stage3vm.py`는 이미 설치되고 네트워크가 연결된 KIKI OS VM을 대상으로
1대, 2대, 3대 Kubernetes 매트릭스를 실행한다. VM을 생성하거나 디스크를
초기화하지 않으며 기존 클러스터를 reset하지 않는다.

## 매트릭스

- 1대: `bootstrap`에서 실제 `kubeadm init`, kubelet 상태, 재실행 멱등성 검증
- 2대: `bootstrap` + `compute`, 단기 토큰과 CA 공개키 해시로 실제 join 검증
- 3대: `bootstrap` + `control` + `compute`, 전체 노드와 재실행 멱등성 검증

각 VM에는 역할에 맞는 KIKI OS 프로파일과 설치 계획서, 활성화된 CRI-O 또는
containerd, `kiki-agent`, `kiki-kubeadm`, `kubeadm`, `kubelet`이 있어야 한다.
`require_ready: true`이면 CNI도 계획서 또는 로컬 override로 명시해 노드가
`Ready`가 되도록 준비한다.

각 VM에서는 Kubernetes 매트릭스 실행 전에 `dbus.service`와 `firewalld.service`가
active인지, `firewall-cmd --state`가 `running`을 반환하는지, `nft list ruleset`이
오류 없이 현재 규칙을 읽는지 확인한다. 이 검사는 빌드 호스트의 격리 세션 D-Bus
스모크를 실제 KIKI OS system bus와 커널 nftables 백엔드에서 확정하는 최종 게이트다.

컨트롤 플레인 join의 개인 인증서는 자동 복사하지 않는다. 운영자가 문서화된
PKI 절차로 먼저 배포한 후에만 해당 노드의
`control_plane_certificates_ready: true`를 설정한다.

## SSH 신뢰 준비

검증기는 비밀번호 입력을 허용하지 않고 `sudo -n`만 사용한다. SSH 키와 별도의
known-hosts 파일을 준비한다.

```bash
ssh-keyscan -H 10.20.0.10 10.20.0.11 10.20.0.12 \
  > ~/.ssh/kiki-stage3-known-hosts
chmod 600 ~/.ssh/kiki-stage3 ~/.ssh/kiki-stage3-known-hosts
```

키 지문은 VM 콘솔이나 별도 신뢰 채널에서 대조해야 한다. 검증기는
`StrictHostKeyChecking=yes`를 강제하며 새 호스트 키를 자동 수락하지 않는다.

## 실행

[예제 설정](../distro/specs/kiki-stage3-vm-matrix.example.yaml)을
복사해 엔드포인트, 노드 주소, SSH 파일을 수정한다.

```bash
python3 tools/ki2stage3vm.py --config stage3-vm.yaml --size 3 --dry-run run
python3 tools/ki2stage3vm.py --config stage3-vm.yaml --size 1 validate
python3 tools/ki2stage3vm.py --config stage3-vm.yaml --size 1 run
python3 tools/ki2stage3vm.py --config stage3-vm.yaml --size 2 run
python3 tools/ki2stage3vm.py --config stage3-vm.yaml --size 3 run
```

2대와 3대 실행에서는 bootstrap 노드가 30분짜리 토큰을 발급한다. 토큰은 명령행,
로그, 결과 JSON에 기록하지 않고 SSH 표준 입력을 통해 각 join 노드의
`/run/secrets/kiki/kubeadm-token`에 `0600`으로 설치한다. CA 해시는 공개 정보로
명령행에 전달한다.

최종 검증은 다음을 요구한다.

- 예상한 노드 이름이 Kubernetes API에 모두 나타난다.
- `require_ready: true`이면 모든 대상 노드의 `Ready=True`가 확인된다.
- 각 노드의 `kubelet.service`가 active다.
- 동일한 `kiki-agent kube reconcile` 재실행이 `kubeadm_skipped=true`를 반환한다.

실패 시 토큰은 30분 후 만료되지만 즉시 폐기하려면 bootstrap 노드에서
`sudo kubeadm token delete <token-id>`를 실행한다. 검증기는 안전 원칙상 클러스터
reset이나 인증서 삭제를 자동 수행하지 않는다.
