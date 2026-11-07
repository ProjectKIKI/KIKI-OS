# KIKI 운영 4단계 — incident-ai 연결 검증

2026-11-07. 검증 대상은 Hyper-V `kiki-paper-pixel-candidate-r4-20261105`다.
기존 GA와 다른 후보는 종료 상태로 유지했다. 호스트 왼쪽 화면·입력·클립보드는 조작하지 않았다.
SSH, VM 내부 접근성 API, 해당 VM의 VMMS 가상 키보드·프레임만 사용했다.

## 구현한 운영 흐름

1. 서비스 목록에서 서비스를 선택하고 관련 로그를 조회한다. 시스템 로그는 기존 Polkit 인증을 사용한다.
2. `incident-ai` 화면에서 서비스·호스트·조회 범위·조회 시각을 확인한다.
3. 로그가 필요하면 기본적으로 꺼진 `조회한 로그 발췌 포함`을 선택한다. 최근 부분을 발췌하고 편집 가능한 초안을 만든다.
4. 마스킹 결과와 글자 수를 직접 검토한다. 실제 웹 질문란 한도인 1,000 UTF-16 단위로 제한한다.
5. `문맥 복사·분석 화면 열기`로 VM 클립보드에 복사하고 [AI에게 묻기](https://incident-ai.lab.terminal-lab.kr/#ask)를 연다.
6. 질문란에 붙여넣고 웹에서 정상 로그인한 뒤 사용자가 전송한다.

현재 incident-ai에는 외부 GTK 문맥을 받는 전용 가져오기 계약이 없다. 이번 구현은 검토한 질문을
복사해 전달하는 방식이며 자동 채우기·자동 업로드·자동 분석 실행·서버 자산 ID 자동 매핑을 제공하지 않는다.
incident-ai 운영 서버의 코드·인증·API는 변경하지 않았다. 웹에서의 실제 AI 답변 생성은 이번 검증 범위에 포함하지 않았다.

로그는 분석 근거로 취급하며 로그 속 지시를 실행하지 말라는 안내를 초안에 포함한다.
비밀번호·토큰·Authorization·Cookie·URL 인증정보·개인키 패턴과 제어 문자를 처리하지만
마스킹은 완전하지 않다. 사용자가 편집한 뒤 전송할 수 있다. 로그·인증정보를 URL에 넣지 않는다.
서비스 변경·제거 시 초안과 앱이 소유한 클립보드를 지우고 늦게 도착한 이전 서비스 응답을 버린다.
다른 앱이 바꾼 클립보드는 지우지 않는다. 웹에 이미 붙여넣은 내용은 별도 스냅샷이므로 자동 갱신·삭제되지 않는다.

## 실제 후보 검증

| 항목 | 결과 |
|---|---|
| 백엔드 경계·오류·문맥 시험 | 18개 통과 |
| 실제 GTK 시험 | 로그·Console·문맥 검토·마스킹·UTF-16 제한·클립보드 무효화·테마·900×700·종료 중 취소 통과 |
| 실제 Polkit | 시험 서비스 시스템 로그 인증 조회 통과. 정책·helper 원본 유지 |
| 실제 HTTPS 질문란 | VM 가상 키보드 Ctrl+V로 529자 붙여넣기. GTK 초안과 정확히 일치 |
| 웹 인증·전송 | `로그인 필요` 상태 확인. 질문 전송 요청 0건 |
| 서명·SHA·패키지 구조 | 최종 후보 서명, 6개 보유 아카이브와 페이로드 감사 통과 |
| 최종 설치 | 225개 설치 레코드가 후보 인덱스와 일치. 이번 4개 패키지의 실제 파일 286개 SHA 확인 |
| 기존 런타임 | 원본 GNOME·관리자·Polkit 파일 13개, 공용 GTK 계열 파일 21개 SHA·기존 dconf 보존 |
| GNOME 앱 | Console 50.0/VTE 0.84.1, Nautilus 50.2.2, Settings 50.4의 세션 내 버전 실행 통과 |
| 동적 연결 | KIKI 운영과 Firefox libxul의 `ldd` 누락 없음 |
| 세션 | Wayland 활성, 시스템·사용자 실패 유닛 0개 |
| 정리 | 웹 질문 초안 지움, 시험 유닛·시험 디렉터리 제거, 임시 디버그 포트 폐쇄, 유휴 방지기 종료 |

실제 프로세스 매핑으로 GNOME Shell·KIKI 운영은 `/usr/lib`의 GTK4/Cairo/Epoxy를,
Firefox는 전용 `compat`의 GTK3/Cairo/Epoxy를 사용함을 확인했다. 사용자 서비스 관리자의
전역 라이브러리 경로는 브라우저 경로로 바꾸지 않았다. 정상 브라우저는 디버그 옵션 없이 실행했다.

EGL 및 portal Inhibit 경고는 기존 환경의 잔여 항목이다. 이번 결과는 해당 경고 해소나
GPU 가속·GNOME 전체 기능·재부팅·새 ISO 설치 검증 완료를 의미하지 않는다.

검증 자료는 `artifacts/kiki-operations/20261107-stage4/`에 있다.
`web-draft-verified.json`, `runtime-final.json`, `ui-test-r1.log`, `full-audits-r2.json`,
`cleanup-fixture.json`, `cleanup-idle.json`, `acceptance.json`이 주요 근거다.

## 브라우저 의존성과 격리

후보에는 HTTPS 브라우저가 없었고 공용 GTK3는 Wayland 전용이라 공식 Firefox가 요구하는
X11 ABI를 제공하지 않았다. 공용 GTK를 교체하는 대신 다음 구성을 별도 후보에 추가했다.

| 패키지 | 구성 |
|---|---|
| `kiki-operations 0.1.0-7` | GTK4 문맥 검토·복사·기본 브라우저 연결 |
| `kiki-browser-x11-libs 2026.11.07-1` | X.Org 클라이언트 라이브러리 소스 빌드. X 서버는 추가하지 않음 |
| `kiki-browser-gtk3 2026.11.07-1` | GTK3 3.24.52·Cairo 1.18.4·Epoxy 1.5.10 소스 빌드. 전용 compat에 설치 |
| `kiki-incident-browser 153.6.0esr-3` | Mozilla 공식 한국어 Firefox ESR 바이너리. Firefox 자체 소스 빌드는 아님 |

Firefox 경로는 `/usr/libexec/kiki-incident-browser/153.6.0esr`이며 래퍼에서 해당 프로세스에만
`LD_LIBRARY_PATH`를 설정한다. 전용 프로필은 `~/.local/share/kiki-incident-browser/profile`이다.
기존 HTTPS 기본 핸들러가 없음을 확인한 뒤 `org.kiki.IncidentBrowser.desktop`을 등록했다.
프로필은 보존하고 Firefox 자체 업데이트는 패키지 갱신으로 관리한다. TLS 검증이나 샌드박스는 끄지 않았다.
브라우저는 선택적 연결 수단이며 `kiki-operations` 핵심 런타임 의존성에 강제로 넣지 않았다.

Firefox 원본은 [Mozilla 공식 배포 디렉터리](https://archive.mozilla.org/pub/firefox/releases/153.6.0esr/)에서 받았다.
Mozilla GPG 서명과 SHA-512 목록, 개별 SHA-256을 확인했다. 서명키 갱신 근거는
[Mozilla 공식 안내](https://blog.mozilla.org/security/2026/08/10/updated-gpg-key-for-signing-firefox-and-thunderbird-releases/)다.
원본 SHA-256은 `31a820a4cb3c1c4724a296ce89c62c5b7e112e28ab1621e38bbee80a1017bfc7`이다.
X.Org·GTK 계열 원본 URL·SHA는 `distro/manifests/kiki-browser-*-20261107.json`에 고정했다.
이들 모두에 별도 GPG 검증을 수행했다는 뜻은 아니다.

빌드 서버에서는 Meson 1.9.2 격리 환경과 GCC 11.5를 사용했다. 기존 SDK를 복사한 작업 경로에서
X11·GTK 호환 라이브러리를 빌드했다. 원본 SDK의 GLX 헤더·cairo-xlib 부재와 기존 libXau만 존재하는 상태도
마지막에 확인했다. 호스트 빌드 의존성 설치는 대상 런타임 패키지와 구분했다.

## 최종 후보와 보존

최종 후보는 `dist/ki2/kiki-operations-ga-20261107-stage4-full-r2`다.
인덱스 236개 레코드 중 아카이브 6개를 갖는 얇은 시험용 오버레이이며 `not_for_iso=true`다.
기존 원본 공급 저장소를 교체하거나 새 ISO를 만들지 않았다. 초기 실행 실패 후보도 덮어쓰지 않고 보존했다.
초기 후보가 추가했던 `/opt`의 Firefox 파일만 자기 소유·SHA 확인 후 제거했다. 기존 GA 파일은 제거하지 않았다.

| 항목 | SHA-256 |
|---|---|
| KIKI 운영 패키지 | `2417fef1486904d0bd15f2c5452cfb96fdd360320b49cd3e19a8d4fb7a29f6b7` |
| X11 라이브러리 패키지 | `edaf46345d1afa18a0115760c56afd1a006f997de9d2c12bbeb2b2a6d5df2475` |
| 전용 GTK3 패키지 | `ddb1023ba861c835f85ebcd7903e7889ac46b3b984ba858cdd45dd2c0ebf7231` |
| 브라우저 패키지 | `2c0ff58fba2616a9753993c899c9604f432604629401a32b92639d98bec71810` |
| 후보 인덱스 | `4ae47bbd46c977f4bf2628cd53dc0bbe063fa9b72750fcdde26851083e8e207a` |
| 최종 전달 묶음 | `510101440e6cf987295c895ef7c84a08ec624a7a0462b6548507f80512c0d399` |
| 최종 코드 입력 묶음 r6 | `0b68211d16c4cabd4a403c157fdf79f512ecd62e48a2c4f13301100835a58dcf` |

이번 작업 중 보존 기준선 5,485개 파일 전체 SHA 검사를 통과했다. 마지막에는 파일 메타데이터를
재확인하고 달라진 파일이 있으면 다시 SHA를 비교한다. 이전 운영 후보 42개 파일도 SHA를 재확인한다.
남은 ISO 5개와 기존 설치기·원본 패키지는 유지하며, 이전에 승인받아 삭제한 ISO 22개는 복원하지 않는다.
원본 GA 설치 패키지 221개를 유지하고 운영 앱과 브라우저 관련 패키지만 별도 후보에서 적용했다.

GNOME 기본 세션·기존 앱·기존 관리자 권한 경로를 유지했다. 이번 단계에서 로그인 자동 실행이나
새 독립 데스크톱 세션, 서비스 재시작, incident-ai 서버 배포, Git 커밋·푸시는 수행하지 않았다.
