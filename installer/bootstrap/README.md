# KIKI Bootstrap Node

The bootstrap server has been moved to Go:

```bash
go run ./cmd/kiki-bootstrapd \
  -host 0.0.0.0 \
  -port 8088 \
  -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

See [cmd/kiki-bootstrapd/README.md](../../cmd/kiki-bootstrapd/README.md) for the
API, token, dashboard, and LLM diagnostic details.
