# KIKI 운영 화면 — 완료 기능과 incident-ai 자동 연동 재개 기록

작성일: 2026-11-08, 한국 시간. 구현·VM 검증 결과는 2026-11-07 기록을 기준으로 한다.
이번 문서 작성에서는 로컬 파일만 확인했으며 서버 접속·VM 조작·빌드·배포를 재개하지 않았다.

## 현재 상태

**1~3단계와 4단계 수동 문맥 전달은 별도 Hyper-V 후보에서 검증 완료했다. 자동 채우기는 사용자 요청으로 보류 중이다.**
현재 사용할 수 있는 흐름은 서비스 선택 → 로그 조회 → 문맥 검토·복사 → incident-ai 질문 화면 열기 → 수동 붙여넣기 → 웹 로그인 후 전송이다.
자동 채우기 후보 소스는 작성했지만 컴파일·테스트·서버 통합·배포하지 않았다.

GNOME을 유지하는 독립 GTK4 앱이며 현재 구현 언어는 **C/GTK4 + Python 백엔드**다.
초기 논의의 Rust 앱이나 Xfce 같은 독립 compositor·데스크톱 전체가 완성된 상태는 아니다.
기존 관리자 재사용을 위한 Libadwaita 런타임과 기존 GNOME 앱은 유지한다.

## 완료 기능

| 단계 | 완료한 기능 | 범위·검증 |
|---|---|---|
| 0 | 삭제 승인 ISO를 반영한 보존 기준선, 기존 관리자·Console·브라우저 의존성 점검 | 남은 산출물과 승인된 삭제를 구분 |
| 1 | 독립 운영 창, 픽셀 스타일, 탐색, 라이트·다크·고대비, 작은 창 배치 | 실제 GTK 렌더링과 900×700 확인. GNOME 전역 테마는 변경하지 않음 |
| 2 | CPU·메모리·루트 디스크·실패 서비스, 서비스 목록·검색·실패 필터·선택 상세 | 실제 로컬 데이터, 3초 갱신, 중복 요청·시간 제한·닫기 시 취소 |
| 2 | 기존 관리자 요약·진단 화면 재사용, 앱 전용 설정 저장 | 기존 관리자·KI2·GNOME dconf 보존 |
| 3 | 선택 서비스의 이번 부팅 최근 200줄 로그, 사용자·시스템 조회 범위 구분 | 사용자 로그 조회와 기존 Polkit 인증 시스템 로그 조회 |
| 3 | 상태·로그 점검 명령 미리보기와 GNOME Console 실행 | 고정 argv·일반 사용자 권한. 임의 셸 실행·서비스 변경 API 없음 |
| 3 | 서비스 변경·제거 시 이전 로그·승인·명령 계획 무효화 | 늦게 도착한 이전 선택 응답 폐기 |
| 4 수동 | 서비스·호스트·로그 범위·시각을 담은 편집 가능한 문맥 | 로그 포함은 기본 해제. 패턴 마스킹·최근 부분 발췌·1,000 UTF-16 단위 제한 |
| 4 수동 | 문맥 복사, incident-ai `AI에게 묻기` 화면 열기 | 실제 VM Ctrl+V로 529자 붙여넣기, GTK 초안과 정확히 일치 |
| 4 의존성 | HTTPS 브라우저와 격리 GTK3 호환 라이브러리 추가 | 공용 GTK 교체 없이 Firefox 정상 실행·동적 연결 확인 |

4단계에서 AI 질문은 전송하지 않았다. 웹 로그인 필요 상태와 전송 요청 0건을 확인했다.
서비스 변경 시 앱 초안과 앱이 소유한 클립보드는 지우지만, 웹에 이미 붙여넣은 문맥은 별도 스냅샷이다.
마스킹은 완전하지 않으므로 사용자가 검토해야 한다. 로그가 비어 있어도 시스템 전체 로그가 없다고 판단하지 않는다.

로그인 자동 실행, 서비스 재시작·변경 승인, 원격 서버 관리, incident-ai 자산 ID 자동 매핑은 이번 완료 범위가 아니다.

## 마지막 검증 완료 후보

| 항목 | 위치·식별자 |
|---|---|
| VM | `kiki-paper-pixel-candidate-r4-20261105` / guest 도구 role `candidate-r4` |
| VM UUID | `eb043387-6b63-42a3-9e8b-239a2a482846` |
| 호스트 후보 | `E:\dev\KIKI-OS\dist\ki2\kiki-operations-ga-20261107-stage4-full-r2` |
| 빌드 서버 작업 루트 | `/build-kikios/kiki-build/kiki-operations-20261107-stage4` |
| 빌드 서버 후보 | 위 루트의 `candidate-full-r2` |
| VM 보관 후보 | `/var/lib/kiki-operations/candidate-20261107-stage4-full-r2` |
| 완료 증거 | `E:\dev\KIKI-OS\artifacts\kiki-operations\20261107-stage4` |
| 판정 기록 | 위 경로의 `acceptance.json`, `runtime-final.json`, `preservation-final.json`, `full-audits-r2.json` |
| 실제 웹 전달 증거 | 위 경로의 `web-draft-verified.json`, `web-draft-cleared.json` |
| 실제 화면 | 위 경로의 `screenshots\stage4-final-context.png`, `screenshots\stage4-web-handoff.png` |

이 후보는 **`not_for_iso=true`인 얇은 시험 오버레이**다. 인덱스 236개 레코드·보유 아카이브 6개이며
새 ISO 공급 저장소나 릴리즈 승격본이 아니다. 실제 설치 레코드는 225개다.
원본 GA 패키지 221개를 유지하고 운영 앱 및 브라우저 관련 패키지만 별도 후보에서 적용했다.

| 최종 패키지·산출물 | SHA-256 |
|---|---|
| `kiki-operations 0.1.0-7` | `2417fef1486904d0bd15f2c5452cfb96fdd360320b49cd3e19a8d4fb7a29f6b7` |
| `kiki-browser-x11-libs 2026.11.07-1` | `edaf46345d1afa18a0115760c56afd1a006f997de9d2c12bbeb2b2a6d5df2475` |
| `kiki-browser-gtk3 2026.11.07-1` | `ddb1023ba861c835f85ebcd7903e7889ac46b3b984ba858cdd45dd2c0ebf7231` |
| `kiki-incident-browser 153.6.0esr-3` | `2c0ff58fba2616a9753993c899c9604f432604629401a32b92639d98bec71810` |
| 후보 인덱스 | `4ae47bbd46c977f4bf2628cd53dc0bbe063fa9b72750fcdde26851083e8e207a` |
| 최종 전달 묶음 `full-results-r2.tar.gz` | `510101440e6cf987295c895ef7c84a08ec624a7a0462b6548507f80512c0d399` |
| 코드 입력 `source-r6.tar.gz` | `0b68211d16c4cabd4a403c157fdf79f512ecd62e48a2c4f13301100835a58dcf` |

코드 입력 묶음은 위 완료 증거 디렉터리에 있다. 이후 README·결과 문서가 추가됐으므로
현재 작업 트리 전체가 묶음과 동일하다는 뜻은 아니다. 컴파일 입력 대조는 `compiled-core-match.json`에 있다.

Firefox 자체는 Mozilla 공식 한국어 바이너리이며 서명·SHA를 검증했다. X11 클라이언트 라이브러리와
전용 GTK3·Cairo·Epoxy는 소스로 빌드했다. 전용 라이브러리는
`/usr/libexec/kiki-incident-browser/153.6.0esr/compat`에 두고 Firefox 프로세스에만 적용한다.
GNOME Shell·KIKI 운영 앱은 기존 `/usr/lib`의 공용 GTK4를 사용한다.

## 보류한 자동 연동 — 실제 작성 범위

목표는 **선택 서비스와 검토한 로그 문맥이 웹 질문란에 자동 표시되고, 사용자가 검토·승인한 뒤에만 분석 요청을 전송하는 것**이다.
사용자가 서버 연결 준비를 나중으로 미루겠다고 하여 작업을 보류했다. 이 보류는 아직 해제되지 않았다.

후보 소스는 incident-ai 원본 저장소 안이 아니라 KIKI-OS 작업 공간에 보관했다.

| 파일 | 상태 |
|---|---|
| `E:\dev\KIKI-OS\integrations\incident-ai\desktopcontext\go.mod` | 독립 후보 Go 모듈 명세. 모듈 경로 `kiki.local/desktopcontext` |
| `E:\dev\KIKI-OS\integrations\incident-ai\desktopcontext\handler.go` | POST 수신·질문란 채우기·승인 UI 후보. 서버 등록·컴파일·실행 전 |
| `E:\dev\KIKI-OS\integrations\incident-ai\desktopcontext\handler_test.go` | 정상·길이 경계·HTML 주입·출처·버전·메서드 시험 소스. 실행 전 |
| `E:\dev\KIKI-OS\artifacts\kiki-operations\20261107-stage4-auto\source-before.tar.gz` | 자동 연동 착수 직전 운영 앱·레시피 백업 |
| 위 디렉터리의 `source-before.json` | 백업 대상별 SHA 목록 |

2026-11-08 로컬 대조에서 위 백업 대상 운영 앱·레시피의 변경은 **0개**였다.
따라서 GTK의 `incident_launch`는 여전히 복사·기본 브라우저 열기 방식이며 자동 POST 생성 기능은 없다.
incident-ai 원본 `E:\dev\kiki-incident-ai`는 당시 읽기 전용으로 참고했으며 수정하지 않았다.

### 후보가 가정한 계약 — 확정·검증 전

- 목적지: `POST https://incident-ai.lab.terminal-lab.kr/desktop-context#ask`. 실제 HTTP 경로는 `/desktop-context`다.
- 형식: `application/x-www-form-urlencoded`, 필드 `version=1`, `question=검토한 초안`.
- 후보 제한: 본문 16KiB 이하, 질문은 비어 있지 않은 1,000 UTF-16 단위 이하.
- 후보 출처: 로컬 파일 폼의 `Origin: null` 또는 지정한 incident-ai HTTPS 출처.
  **이 출처 검사만으로 신뢰된 데스크톱 앱을 인증할 수는 없다.** 공개 입력으로 취급하고 계속 검토해야 한다.
- 서버는 기존 `web/index.html`을 읽고 JSON의 HTML 이스케이프를 거쳐 질문란 `.value`로 문맥을 넣는다.
- 표시용 수신 자체는 AI 질의·조치 실행을 하지 않는다. 이후 분석 API의 기존 로그인·역할·CSRF 검증을 유지한다.
- `no-store`·`no-referrer`·프레임 금지 헤더와 전송 승인 체크 항목을 추가한다.
- 입력 수정 시 승인을 해제하고 미승인 `submit`을 막는 후보 로직이 있다.
- 화면 표시는 `/#ask`로 주소를 바꾸도록 작성했다. POST 재전송 방지와 실제 라우팅 동작은 브라우저에서 검증해야 한다.

로컬 비공개 HTML 폼을 브라우저로 열어 HTTPS POST하는 송신 방식을 검토했지만 **아직 구현하지 않았다**.
문맥을 URL·프로세스 명령 인수·호스트 클립보드에 넣지 않는 방향을 유지한다.
로그 문맥이 서버로 전달되는 시점과 AI 분석 요청이 실행되는 시점은 서로 다르므로 UI에서 구분해야 한다.

### 후보 소스 SHA-256

| 파일 | SHA-256 |
|---|---|
| `go.mod` | `c20a34e925d6a25e83b93f90e190be7a02919278a26b0b54e0a41d3367ec0213` |
| `handler.go` | `0f50e1671c47964eb27ceb534c2e8c07ca961bcc9613f1ee1dc11a9c9d93f5bd` |
| `handler_test.go` | `561c2c3c7afd5118954bf2bc12d3c3f5e5536dafe76ddb0d84597706f65db5d8` |
| `source-before.tar.gz` | `4360e1a55ec5176fb1fcec626186d592f5a59be89dd38b69159fac1f5113402e` |

이 SHA는 소스 식별용이며 컴파일·기능·보안 검증 통과를 의미하지 않는다.

## 재개할 순서

1. **자동 연동 작업 재개 지시와 incident-ai 관리 접속 경로를 확인한다.**
   문서에 있던 `lab@external.terminal-lab.kr:41554`에 대한 기존 키 인증은 거절됐다.
   빌드 서버 `lab@external.terminal-lab.kr:41816`은 별도 서버이므로 혼동하지 않는다.
   관리 가능한 기존 SSH 별칭·키 또는 승인된 접속 방법을 확인하며 비밀번호·개인키를 문서나 명령 인수에 넣지 않는다.
   보류 직후 준비 중이던 추가 SSH 연결도 자동 승인 검토에서 차단됐고 실행되지 않았다.
2. **보존 기준선과 실제 서버 상태를 다시 확인한다.**
   마지막 후보의 SHA·VM 역할·현재 실행 패키지·incident-ai 실행 이미지·웹 파일·인증 구성을 대조한다.
   기존 설치기·패키지·ISO·GNOME 앱과 서버 데이터·계정·토큰·정책을 덮어쓰지 않는다.
   원본 저장소의 작업 중 변경과 이번 후보를 분리한다.
3. **수신 계약을 검토하고 독립 시험을 통과시킨다.**
   Go 도구가 있는 격리 환경에서 후보 모듈에 `gofmt`, `go test ./...`, 필요 시 `go test -race ./...`를 실행한다.
   이는 재개 시 수행할 명령이며 현재 실행 결과는 없다. 실제 분석 화면 HTML·인증 스크립트·라우터와의 호환성을 확인한다.
   기존 페이지의 CSP·압축·정적 파일 경로 및 middleware를 조사한 뒤 서버 등록 방식을 결정한다.
4. **별도 incident-ai 시험 인스턴스에 연결한다.**
   `Register`는 후보 함수일 뿐 원본 서버에서 호출되지 않는다. 기존 모듈과 통합하는 방법을 결정해야 한다.
   시험용 데이터·설정·포트를 분리하고 운영 감시·노드 조치·자동 복구가 시작되지 않게 구성한다.
   현재 운영 서버 바이너리를 개발 작업 트리 전체 빌드로 무조건 교체하지 않는다.
5. **GTK 송신을 구현한다.**
   현재 `E:\dev\KIKI-OS\cmd\kiki-operations\incident.h`의 수동 연결을 바탕으로 별도 후보에서 수정한다.
   검토된 현재 서비스 초안만 전달하며, 서비스 세대·조회 범위·길이 검증을 재사용한다.
   비공개 임시 HTML 폼을 쓴다면 디렉터리 0700·파일 0600, HTML 이스케이프, 실행 시간 제한과 정리를 구현한다.
   브라우저 기본 핸들러가 HTTPS와 로컬 HTML에서 다를 수 있으므로 실제 실행 경로도 검증한다.
6. **새 앱 후보를 빌드하고 VM에서 종단 검증한다.**
   기존 후보·백업을 보존하고 새 패키지 release와 새 작업 디렉터리를 사용한다.
   기존 잠금 파일과 서명 검증 흐름을 재사용하되 이전 완료 후보에 새 파일을 덮어쓰지 않는다.
   SSH와 `E:\dev\KIKI-OS\tools\ki2pixelguest.py --role candidate-r4`를 우선 사용한다.
   VM의 실제 실행·IP·로그인 상태는 다시 확인한다. 이전 세션 번호나 임시 시험 서비스를 그대로 가정하지 않는다.
7. **판정·복구 기록을 남긴다.**
   SHA·의존성·런타임·승인 전 미전송·정리·보존을 통과한 결과만 완료로 표시한다.
   운영 서버 반영은 후보 검증 결과와 배포 범위를 구체화한 뒤 진행한다. 이번 문서는 배포 승인이나 재개 지시가 아니다.

## 자동 연동의 남은 검증 항목

- [ ] 수신기 Go 컴파일·단위 테스트, 실제 incident-ai 서버 통합·회귀 테스트.
- [ ] 원문 한글·줄바꿈·이모지·HTML 문자가 질문란에 정확히 보존됨. 로그 속 HTML·스크립트가 실행되지 않음.
- [ ] 1,000 UTF-16 경계·초과·빈 값·잘못된 인코딩·NUL·중복/추가 필드·잘못된 버전·본문 초과의 거절.
- [ ] 메서드·출처·Content-Type 처리, OPTIONS와 CORS 정책, 공개 입력의 요청 제한·타임아웃·메모리 한도.
- [ ] 기존 HTML의 종료 태그·질문란·폼이 없거나 달라졌을 때 조용한 실패 대신 명확한 오류.
- [ ] URL·질의 문자열·접속 로그에 문맥이 남지 않음. 요청 본문 로깅·추적·오류 응답도 확인.
- [ ] 캐시·뒤로/앞으로·새로고침·POST 재전송·브라우저 종료/복구에 따른 문맥 잔존 확인.
- [ ] 기존 웹 초안이 있는 경우 덮어쓰기 정책, 연속 가져오기·여러 탭·오래된 서비스 문맥 구분.
- [ ] 자동 채우기만으로 AI 요청이 발생하지 않음. 분석 POST·작업 생성·조치 실행 모두 0건.
- [ ] 승인 체크 전 버튼·Enter·기존 keydown 핸들러·기존 send 함수 등 모든 실제 전송 경로 차단.
- [ ] 승인 후 내용 수정 시 승인 해제. 로그인 전후 문맥·승인 상태 유지/초기화 정책 확인.
- [ ] 기존 로그인·역할·CSRF가 유지됨. UI 체크 항목은 서버 권한 검증을 대체하지 않음.
- [ ] 승인 후 한 번의 명시적 전송만 발생. 가능하면 시험 서버의 모의 분석 응답으로 먼저 검증.
- [ ] 실제 운영 데이터·노드에 시험 질문이나 조치가 실행되지 않음.
- [ ] 브라우저 없음·실행 실패·네트워크 오류·수신기 미배포에서 오류와 수동 전달 대안 표시.
- [ ] 임시 파일이 사용자 외에 노출되지 않고 정상 종료·오류·서비스 변경·다음 실행 시 정리됨.
- [ ] GNOME·Console·파일·Settings와 원본 관리자 권한 흐름 회귀 확인.
- [ ] 앱·수신기·인덱스의 SHA/서명·의존성, 원본 패키지 및 남은 ISO 보존 재확인.

## 유지할 제약과 남은 환경 문제

**왼쪽 화면은 조작하지 않는다.** 호스트 마우스·키보드·포커스·클립보드를 사용하지 않고
후보 VM 식별을 확인한 SSH·VM 내부 API·해당 VM의 가상 입력만 사용한다.

마지막 검증에서 보존 대상 5,485개 파일의 전체 SHA 검사를 통과했고, 최종 메타데이터 변경은 0개였다.
이전 운영 후보 42개 파일의 SHA도 일치했다. 남은 ISO 5개는 유지했고 승인 후 삭제한 ISO 22개는 복원하지 않았다.
VM의 원본 런타임 파일 13개·공용 GTK 파일 21개·기존 dconf를 보존했다.
서명 검증과 6개 보유 아카이브 감사, 실제 설치 파일 286개 검증을 통과했다.
이는 2026-11-07 결과이며 재개 시점의 보존 상태는 다시 확인해야 한다.

시스템·사용자 실패 유닛은 당시 0개, Wayland 세션은 활성이었다. 임시 시험 서비스·브라우저 디버그 포트·
유휴 방지기는 정리했고 웹 질문 초안도 지웠다. 재개 시 시험 리소스를 새로 만들어야 한다.
기존 EGL·portal Inhibit 경고는 남아 있으며 GPU 가속 정상화 완료를 의미하지 않는다.
새 ISO 생성·재부팅·실제 AI 답변 생성은 4단계 검증 범위 밖이었다.

## 관련 기록

### 2026-11-08 커밋 준비 확인

자동 연동 수신기 폴더에 미완성·미검증·미배포 상태를 명시한 `README.ko.md`를 추가했다.
이 안내 문서 추가는 자동 연동 개발이나 서버 작업 재개가 아니다.
완료 소스와 문서는 Gitea `stage3`에 보관하고, 로컬 `artifacts/`·`dist/`의 설치기·패키지·ISO·
시험 자격증명·원시 검증 자료는 커밋에 포함하지 않는다. 이 문서에 적힌 로컬 증거 경로는
다른 PC에서 저장소를 clone하는 것만으로 생기지 않는다.

커밋 준비 시 운영 앱 Python 시험 18개, 픽셀 후보 경계 시험 4개, 화면 JavaScript 시험 4개,
CI 시험 9개가 통과했다. Linux XFS 백업 시험 6개는 Windows에서 건너뛰었다.
릴리즈 시험 32개 중 `test_unchanged_commit_does_not_rewrite_catalog` 1개는 Windows에서 실패했다.
기존 HEAD와 현재 소스를 같은 환경에서 비교해 동일 실패이며 추가 오류가 없음을 확인했다.
전체 릴리즈 시험 통과로 해석하면 안 된다. 자동 연동 Go 후보 시험은 실행하지 않았다.

보존 기준선 중 설치기·패키지·ISO 파일 5,339개의 크기·mtime이 모두 동일함을 확인했다.
기준선 SHA는 이전 검증 기록을 유지하며, 이번 확인에서 해당 대용량 파일을 전부 재해시하지는 않았다.
추가 확인 기록은 `E:\dev\KIKI-OS\artifacts\kiki-operations\20261108-gitea-publish`에 보관한다.

- [0단계 보존·의존성 점검](E:/dev/KIKI-OS/docs/kiki-operations-stage0-20261106.ko.md)
- [1·2단계 독립 운영 화면](E:/dev/KIKI-OS/docs/kiki-operations-stage12-20261106.ko.md)
- [3단계 로그·Console](E:/dev/KIKI-OS/docs/kiki-operations-stage3-20261107.ko.md)
- [4단계 수동 incident-ai 전달·검증](E:/dev/KIKI-OS/docs/kiki-operations-stage4-20261107.ko.md)
- [운영 앱 설명](E:/dev/KIKI-OS/cmd/kiki-operations/README.ko.md)
- [4단계 판정 원본](E:/dev/KIKI-OS/artifacts/kiki-operations/20261107-stage4/acceptance.json)
- [보류 수신기 소스](E:/dev/KIKI-OS/integrations/incident-ai/desktopcontext/handler.go)

재개 요청 예시: “이 문서 기준으로 incident-ai 자동 채우기 작업을 재개해줘. 서버 접속부터 확인하고,
별도 후보에서 승인 전 미전송·승인 후 전송을 검증해줘. 기존 산출물과 GNOME 앱은 보존하고 왼쪽 화면은 건드리지 마.”
