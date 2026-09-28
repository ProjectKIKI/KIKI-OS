# KIKI 부트스트랩 노드

부트스트랩 관리 서버는 Go로 이전했다. 저장소 루트에서 실행한다.

```bash
go run ./cmd/kiki-bootstrapd \
  -host 0.0.0.0 \
  -port 8088 \
  -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

API, 토큰, 대시보드, LLM 진단에 대한 설명은 [kiki-bootstrapd 문서](../../cmd/kiki-bootstrapd/README.md)를 참조한다. 실제 공개 서비스에는 TLS와 별도 접근 통제를 적용한다.
