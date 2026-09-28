# kiki-infraopsd

`kiki-infraopsd`는 인증이 필요한 KIKI InfraOps 관리 API와 최소 웹 콘솔이다. 시험용 상태를 원자적으로 갱신하는 권한 `0600` JSON 파일에 저장한다.

## 실행 전 조건

런타임·빌더 이미지는 불변 다이제스트로 고정한다. 빌드는 허용된 Git 호스트와 통제된 외부 연결 프록시가 필요하며, 프록시 CIDR은 빌드별 NetworkPolicy에 반영된다. 아래 주소·다이제스트·비밀 이름은 환경에 맞게 검증해 교체한다.

```bash
kiki-infraopsd \
  -host 0.0.0.0 -port 8090 \
  -state /var/lib/kiki/infraops-state.json \
  -token-file /run/secrets/kiki/infraops-token \
  -llama-image registry.local/kiki/llama@sha256:<digest> \
  -vllm-image registry.local/kiki/vllm@sha256:<digest> \
  -git-image registry.local/kiki/git@sha256:<digest> \
  -bos-builder-image registry.local/kiki/bos-builder@sha256:<digest> \
  -buildctl-image registry.local/kiki/buildctl@sha256:<digest> \
  -supply-chain-image registry.local/kiki/supply-chain@sha256:<digest> \
  -allowed-git-hosts git.example.com \
  -allowed-registries registry.example.com \
  -build-egress-proxy http://egress-proxy.kiki-system.svc:8080 \
  -build-egress-proxy-cidr 10.20.0.10/32 \
  -buildkit-address tcp://buildkitd.kiki-build.svc:1234 \
  -buildkit-cidr 10.30.0.20/32 -buildkit-port 1234 \
  -registry-auth-secret registry-auth \
  -signing-secret artifact-signing
```

모든 API 요청에는 `Authorization: Bearer <token>`과 감사 주체를 나타내는 `X-Kiki-Actor: <audited principal>` 헤더가 모두 필요하다.

## API와 빌드 수명주기

`PUT /api/v1/nodes/{name}/inventory`, `GET /api/v1/nodes`, `POST|GET /api/v1/models`, `POST|GET /api/v1/model-deployments`, `POST|GET /api/v1/builds`, `PUT /api/v1/builds/{id}/result`, `GET /api/v1/artifacts`, `GET /api/v1/audit`를 제공한다.

BOS·OCI/CPM 빌드는 대기, 가져오기, 검증, 빌드, 시험, 검사, 서명, 게시 순서로 진행한다. 성공 결과는 산출물·SBOM·출처 증명·서명의 SHA-256 다이제스트가 모두 있어야 승인된다. OCI/CPM 빌드는 제한된 `buildctl` 클라이언트 Pod와 별도 관리 BuildKit 서비스로 수행한다. Pod에는 Docker 소켓이나 호스트 마운트가 없으며 NetworkPolicy는 DNS·설정된 프록시·BuildKit CIDR만 허용한다. `kiki-supplychain` 마무리 단계는 셸 없이 Syft·Grype·Cosign을 실행하고 SLSA v1 출처 증명 및 증거 파일별 다이제스트를 보고한다.
