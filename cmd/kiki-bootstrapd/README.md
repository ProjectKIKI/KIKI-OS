# kiki-bootstrapd

`kiki-bootstrapd`는 KIKI 노드 설치와 최초 등록을 위한 Go 기반 관리 서버다. 인스톨러 등록 콜백, 노드 하트비트·이벤트, 일회성 등록 토큰, 이미지 미러 계획, ISO·오버레이·디스크 이미지·로그 번들 인덱스, 로컬 대시보드, 읽기 전용 진단을 제공한다. 초기 구현은 Go 표준 라이브러리만 쓰는 JSON 상태 파일에 저장하며 저장소 경계는 `internal/bootstrap.Store`로 분리한다.

## Stage3 완료 기준

- 관리자가 노드별 만료 등록 토큰을 발급한다.
- 인스톨러가 일회성 토큰을 노드 자격 증명으로 교환한다.
- 이후 설치 진행·하트비트·로그·번들 요청은 해당 노드로 인증하며 다른 노드를 사칭할 수 없다.
- 관리 조회·변경은 별도 관리자 자격 증명으로 보호한다.
- 이벤트에는 자격 증명을 가리고 상태에는 다이제스트만 저장한다.
- 인증 대시보드, API·인스톨러 계약 테스트와 BIOS/UEFI 드라이런을 통과한다.

`KikiMachine` 조정과 실제 BIOS/UEFI 설치 시험은 후속 과제다. 위 목록은 완료 기준이지 모두 검증되었다는 뜻은 아니다.

## 빌드와 실행

```bash
go build -o kiki-bootstrapd ./cmd/kiki-bootstrapd
./kiki-bootstrapd \
  -host 0.0.0.0 -port 8088 \
  -state installer/bootstrap/state/kiki-bootstrap-state.json \
  -artifacts installer/dist \
  -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

로컬 대시보드는 `http://localhost:8088`에 있다. 외부 노출 시 TLS·접근 통제를 별도로 적용한다.

## 인증

관리자 Bearer 토큰은 토큰 발급·인벤토리·이벤트·산출물·이미지 계획·진단을 보호한다. 노드별 일회성 등록 토큰은 임의의 노드 Bearer 토큰으로 교환하며, 이후 설치 단계·하트비트·로그·번들 업로드에 쓴다. 원문 토큰은 한 번만 반환하고 저장 상태에는 SHA-256 다이제스트만 남긴다. 루프백이 아닌 주소에서는 `-admin-token-file`이 없으면 시작하지 않는다. 관리자 토큰은 32자 이상이고 파일에 그룹·기타 사용자 접근 권한이 없어야 한다.

루프백 실험 환경에서도 사전 발급 토큰을 강제하려면 `KIKI_REQUIRE_TOKEN=true` 또는 `-require-token`을 사용한다.

```bash
curl -X POST http://localhost:8088/api/v1/tokens \
  -H "Authorization: Bearer $KIKI_BOOTSTRAP_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"nodeName":"kiki-node-001","ttlSeconds":3600}'
```

첫 `POST /api/v1/nodes/register`의 `spec.registrationToken`에 일회성 토큰을 넣는다. 응답의 `nodeToken`을 이후 모든 노드 요청에 `Authorization: Bearer <nodeToken>`으로 전송하며 등록 토큰을 재사용하지 않는다.

## API

| 경로 | 기능 |
| --- | --- |
| `POST /api/v1/nodes/register`, `POST /api/v1/nodes/heartbeat` | 등록·하트비트 |
| `POST /api/v1/nodes/logs`, `POST /api/v1/nodes/log-bundles` | 로그·번들 업로드 |
| `POST /api/v1/tokens`, `POST /api/v1/images` | 토큰·이미지 계획 생성 |
| `POST /api/v1/nodes/{name}/diagnose` | 진단 요청 |
| `GET /api/v1/artifacts`, `GET /api/v1/nodes`, `GET /api/v1/nodes/{name}` | 산출물·노드 조회 |
| `GET /api/v1/events`, `GET /api/v1/images` | 이벤트·이미지 조회 |

## LLM 보조 진단

LLM은 설치 제어 경로 밖에서 읽기 전용 진단에만 쓴다. OpenAI 호환 엔드포인트를 지정하며 임의 셸 명령은 허용하지 않는다.

```bash
KIKI_LLM_ENDPOINT=http://kiki-inference.kiki-system.svc \
KIKI_LLM_MODEL=kiki-ops \
KIKI_LLM_API_KEY_FILE=/run/secrets/kiki/llm-api-key \
./kiki-bootstrapd
```

신뢰된 내부 엔드포인트에서는 키 파일을 생략할 수 있다. 엔드포인트 미설정·실패·시간 초과·잘못된 응답 시 규칙 기반 요약으로 돌아간다.
