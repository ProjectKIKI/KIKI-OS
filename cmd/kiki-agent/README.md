# kiki-agent Stage3 명령

Go 기반 `kiki-agent`는 기존 인벤토리·InfraOps 보고 기능에 보호 장치가 있는 Stage3 설정 경로를 더한다. 배포 패키지는 실행 파일을 `/usr/libexec/kiki-agent-stage3`에 설치하며, 기존 Python `/usr/bin/kiki-agent`는 Stage3 하위 명령을 이 파일에 위임한다.

## 설정 병합 및 조정

설정은 다음 순서로 병합한다. 뒤의 계층이 앞의 계층보다 우선한다.

1. `/usr/share/kiki/defaults/*.yaml`
2. `/usr/share/kiki/profiles/<role>.yaml`
3. `/var/lib/ki2/install-plan.yaml`
4. `/etc/kiki/overrides/*.yaml`
5. 일회성 명령행 인자

맵은 키별로 병합하고, 일반 목록은 앞선 목록을 대체한다. 목록을 덧붙이려면 `{merge_strategy: append, items: [...]}`를 명시한다. 병합된 계획은 권한 `0600`으로 저장한다. 평문 토큰·비밀번호·개인키 필드는 가리고 비밀 참조는 유지한다.

```bash
kiki-agent kube reconcile --dry-run \
  --token-file /run/secrets/kubeadm-token \
  --endpoint 10.0.0.10:6443 \
  --ca-cert-hash sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

조인 시 엔드포인트나 토큰 참조가 없거나 CA 해시가 잘못되면 거부한다. 컨트롤 플레인 조인에는 명시적 인증서 정책이 필요하다. CRI 소켓 사전 점검은 기본으로 켜져 있다. `--skip-preflight`는 이미지·대상 rootfs 검증에만 사용한다.

CNI는 기본으로 비활성화된다. 활성화하면 허용 목록에 있는 공급자만 실행할 수 있으며, 매니페스트 URL·파일 경로·패키지 중 하나를 제공해야 한다. `--dry-run`은 CNI 명령을 출력하지만 적용하지 않는다.

## 원격 설치 계획

원격 계획은 격리 경로에 먼저 내려받고 SHA-256 또는 Ed25519 서명 검증 후에만 승격한다.

```bash
kiki-agent plan fetch \
  --url https://repo.example/kiki/install-plan.yaml \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

서명 방식에서는 YAML의 정확한 바이트를 서명하고 대상 노드에는 공개키만 설치한다.

```bash
kiki-agent plan fetch \
  --url https://repo.example/kiki/install-plan.yaml \
  --signature https://repo.example/kiki/install-plan.yaml.sig \
  --public-key /etc/kiki/trust/install-plan.ed25519.pub
```

서명 값으로 `base64:<signature>`, `@/path/to/plan.sig`, `file://` URL도 사용할 수 있다. SHA-256과 서명을 모두 지정하면 두 검증을 모두 통과해야 한다. 설치된 노드에 개인키를 두지 않는다.

`--url`이 없으면 `/proc/cmdline`의 `kiki.plan.url`, `kiki.plan.sha256`, `kiki.plan.signature`를 읽는다. 검증되지 않은 계획은 운영자가 명시적으로 `--allow-unverified`를 지정하지 않는 한 거부한다.
