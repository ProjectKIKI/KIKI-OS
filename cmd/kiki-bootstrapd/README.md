# kiki-bootstrapd

`kiki-bootstrapd` is the Go bootstrap management server for KIKI node
installation.

## Stage 3 completion criteria

Stage 3 covers the initial bootstrap management boundary. It is complete when:

- administrators can issue node-bound, expiring registration tokens;
- an installer exchanges a one-time token for a node credential;
- later installation phases, heartbeats, logs, and bundles authenticate as that
  node and cannot impersonate another node;
- management reads and writes require a separate administrator credential;
- credentials are redacted from events and persisted only as digests;
- the authenticated dashboard, API tests, installer contract tests, and BIOS/
  UEFI dry-run matrix pass.

Kubernetes `KikiMachine` reconciliation and real BIOS/UEFI installation tests
remain later-stage work.

It provides:

- installer registration callbacks
- node heartbeats
- event collection
- one-time registration token issuing and consumption
- image mirror plan tracking
- artifact index for ISO, overlays, disk images, and uploaded log bundles
- installer/node log bundle upload
- a local dashboard
- read-only diagnostic summaries with optional LLM assistance

The daemon uses a JSON state file in this first Go implementation so it builds
with the Go standard library only. The storage boundary is isolated in
`internal/bootstrap.Store`, so moving to SQLite later is straightforward.

## Build

```bash
go build -o kiki-bootstrapd ./cmd/kiki-bootstrapd
```

## Run

```bash
./kiki-bootstrapd \
  -host 0.0.0.0 \
  -port 8088 \
  -state installer/bootstrap/state/kiki-bootstrap-state.json \
  -artifacts installer/dist \
  -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

Open:

```text
http://localhost:8088
```

## API

- `POST /api/v1/nodes/register`
- `POST /api/v1/nodes/heartbeat`
- `POST /api/v1/nodes/logs`
- `POST /api/v1/nodes/log-bundles`
- `POST /api/v1/tokens`
- `POST /api/v1/images`
- `POST /api/v1/nodes/{name}/diagnose`
- `GET /api/v1/artifacts`
- `GET /api/v1/nodes`
- `GET /api/v1/nodes/{name}`
- `GET /api/v1/events`
- `GET /api/v1/images`

## Token Enforcement

Stage 3 uses two separate credential classes:

- an administrator bearer token protects token issuance, inventory, events,
  artifacts, image plans, and diagnostics;
- a node-bound one-time registration token is exchanged for a random node
  bearer token. The node bearer token authenticates later installation phases,
  heartbeats, logs, and log-bundle uploads.

Only SHA-256 token digests are persisted. Raw registration and node tokens are
returned once and must be stored as secrets. A non-loopback listener refuses to
start unless `-admin-token-file` is configured. The administrator token must be
at least 32 characters and its file must not grant group or other permissions.

For a loopback-only lab server, registration enforcement remains optional. To
require pre-issued active tokens:

```bash
KIKI_REQUIRE_TOKEN=true ./kiki-bootstrapd
```

or:

```bash
./kiki-bootstrapd -require-token
```

Create a token:

```bash
curl -X POST http://localhost:8088/api/v1/tokens \
  -H "Authorization: Bearer $KIKI_BOOTSTRAP_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"nodeName":"kiki-node-001","ttlSeconds":3600}'
```

The initial `POST /api/v1/nodes/register` includes the returned one-time token
in `spec.registrationToken`. Its response contains `nodeToken`. Every later
node request sends that value as `Authorization: Bearer <nodeToken>` and does
not resend the registration token.

## LLM Diagnostics

LLM usage is intentionally outside the installation control path. Configure an
OpenAI-compatible endpoint; arbitrary shell commands are not accepted:

```bash
KIKI_LLM_ENDPOINT=http://kiki-inference.kiki-system.svc \
KIKI_LLM_MODEL=kiki-ops \
KIKI_LLM_API_KEY_FILE=/run/secrets/kiki/llm-api-key \
./kiki-bootstrapd
```

The key file is optional for trusted in-cluster endpoints. If the endpoint is
unset, fails, returns invalid output, or times out, diagnostics fall back to a
rule-based summary.
