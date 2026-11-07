# KIKI 독립 운영 화면 — 1·2단계 구현과 검증

2026-11-06, Asia/Seoul. [0단계 점검](kiki-operations-stage0-20261106.ko.md)을 기준으로
독립 GTK 화면 골격과 실제 로컬 상태 연결을 구현했다. GA·KI2 37을 유지하며 새 앱만 추가했다.
로그인 자동 실행·로그/터미널 심화 연결·incident-ai 전달·권한 변경 작업은 후속 범위다.

## 구현 결과

| 단계 | 구현한 기능 | 결과 |
| --- | --- | --- |
| 1. 독립 UI | 자체 앱 ID, 픽셀 아이콘·색·카드·탐색, 라이트/다크, 고대비, 작은 창 배치 | 일반 GNOME에서 실제 렌더링 확인 |
| 1. 독립 설정 | `~/.config/kiki-operations/settings.ini`에 테마·실패 필터 저장 | 실제 파일 저장 확인, GNOME dconf SHA 유지 |
| 2. 상태 조회 | CPU·가용량 기준 메모리·루트 파일시스템·실패 서비스 수 | 실제 `/proc`·파일시스템·systemd 데이터 사용 |
| 2. 서비스 목록 | 현재 systemd 서비스 목록·검색·실패 필터·선택 상세 | 실제 서비스 상태와 설명 표시 |
| 2. 기존 관리자 재사용 | 기존 snapshot의 OS·패키지 요약, 진단 화면 진입 버튼 | 기존 관리자·KI2 API를 교체하지 않고 재사용 |
| 2. 갱신·오류 | 3초 갱신, 요청 중복 방지·시간 제한, 조회 중 닫기 취소, 미확인 값 구분 | 실제 갱신 시각 변화와 종료 검증 |

앱 ID는 `org.kiki.Operations`, 실행 파일은 `kiki-operations`, 조회 CLI는
`kiki-operationsctl`이다. UI는 C/GTK4와 json-glib로 작성했다. Libadwaita 위젯·셸 확장·전용
세션에 의존하지 않는다. 기존 관리자 재사용을 위한 패키지 의존성 때문에 Libadwaita 런타임은 유지된다.
GNOME Shell·Mutter·GDM·기존 GNOME 앱은 그대로 사용한다. 별도 데스크톱 환경 전체를 완성한 단계는 아니다.

## UI와 데이터 경계

KIKI 앱의 창에만 CSS를 적용한다. 시스템 GTK 테마·GNOME 셸 스타일·기본 앱 스타일을 강제하지 않는다.
일반 GNOME의 `--mode=user`에서 `KIKI_PAPER_PIXEL`·`DCONF_PROFILE` 없이 실행했다.
기존 픽셀 셸 확장은 비활성이며 전용 관리자 자동 실행 서비스도 inactive인 상태에서 확인했다.

1024px에서는 서비스와 상세를 나란히 표시한다. 좁은 화면에서는 세로 배치와 스크롤을 사용하며,
실제 900×700 창 폭을 검사했다. 서비스 이름·설명을 검색하고 실패 항목만 표시할 수 있다.
서비스를 새로 조회할 때 선택한 서비스 이름을 기준으로 상세를 유지한다.

새 CLI는 `kiki-operations-v1` JSON을 반환한다.

- `runtime`: CPU 120ms 측정 구간, 메모리·디스크·systemd 목록을 조회한다.
- `summary`: 기존 `kiki-adminctl snapshot`을 최초·수동 갱신 시 호출한다.
- 실시간 폴링에서는 KI2 패키지 카탈로그를 조회하지 않는다.
- 측정 불가 항목은 null과 warnings로 반환하고 UI에서 ‘조회 불가’로 표시한다.
- 조회 실패 시 이전 데이터가 최신이 아님을 알린다.
- 서비스 변경·임의 명령·권한 상승 API는 추가하지 않았다.

전용 GSettings 스키마는 키파일 backend의 `preferences` 그룹을 사용한다.
이는 GNOME의 사용자 설정 DB와 별개다. 그룹 지정은
[GIO 키파일 backend 계약](https://docs.gtk.org/gio/func.keyfile_settings_backend_new.html)을 따른다.

## 후보와 빌드

- 최종 앱 패키지: **`kiki-operations 0.1.0-3`**.
- 후보: `dist/ki2/kiki-operations-ga-20261106-r3`.
- 기준 GA 오버레이: 232개 인덱스 항목, 실제 설치된 기존 패키지 221개와 일치.
- 새 후보: 인덱스 233개 항목, 제공 아카이브 3개. 기존 관리자·픽셀 세션 2개와 새 앱 1개다.
- 실제 설치: 기존 221개 유지 + 운영 앱 1개 = **222개**. KI2는 `0.1.0-37` 유지.
- 기존 파일을 덮어쓰지 않는 신규 패키지로 시작했고, UI 보완 리비전은 운영 앱만 갱신했다.
- 이 후보는 `not_for_iso=true`인 설치 환경 시험용 오버레이다. 새 ISO 공급본이 아니다.

빌드는 기존 빌드 서버의 `/build-kikios/kiki-build/kiki-operations-20261106-r1/` 별도 경로에서
수행했다. 기존 SDK를 읽기 전용 sysroot로 사용하고 호스트 cc GCC 11.5.0으로 네이티브 C 앱을
빌드했다. GTK4 4.22.4를 포함한 기존 SDK의 헤더·라이브러리에 연결했으며 실제 대상 VM에서 로더와 실행을 확인했다.
기존 서버 작업 경로·SDK·설치기·패키지·ISO를 덮어쓰지 않았다. 서명 개인키는 서버에만 남겼다.

| 대상 | SHA-256 |
| --- | --- |
| 기준 GA 인덱스 | `269b2f1683b781ea3d00f26d3b4a3466e67150a570140920824d1f92346c7f71` |
| 최종 후보 인덱스 | `47ca0b94e29d47c9943bb134f7526b4a89343703070cecc4d77a782b9e0e99ec` |
| 새 앱 패키지 | `f9ebfc04581b0837756f1053e9159b88351b9d5ba68c2acd901cc59c7d286cb1` |
| Ed25519 공개키 | `22122bb259fb1d61c21bf0db35c439cedbf631cb2f1c5cc8af07ef23e3a24f2f` |

전체 패키지 아카이브를 복제하거나 새 ISO를 만들지 않았다. 이전 시험 후보도 덮어쓰지 않고 보관했다.

## 실제 검증

시험 VM은 기존 독립 후보 **`kiki-paper-pixel-candidate-r4-20261105`**다.
이름의 r4는 VM 생성 시점이며 새 앱은 0.1.0-3이다. VM의 로그인 세션 선택을 일반 GNOME으로
전환하여 확장 독립성을 확인했다. 원본 GA VM과 보관한 다른 픽셀 VM은 정지 상태로 유지했다.
호스트의 왼쪽 화면·마우스·키보드를 조작하지 않았다. SSH와 VMMS의 가상 입력·프레임만 사용했다.

| 검사 | 결과 |
| --- | --- |
| 데이터 단위 시험 | CPU guest 중복 계산·카운터 역행, MemAvailable, 서비스 파싱·정렬, 패키지 조회 분리, 조회 불가의 null 처리, 기존 schema 검증 등 6개 통과 |
| GTK 화면 시험 | 실제 조회·선택·검색·실패 필터·라이트/다크·설정 파일 저장·900×700·고대비·조회 중 닫기 통과 |
| 지속 갱신 | 실제 창에서 갱신 시각이 `08:43:38` → `08:43:44`로 바뀜을 접근성 트리로 확인 |
| 단일 실행 | 두 번째 실행은 기존 앱으로 전달되고 실제 앱 프로세스 1개 유지 |
| 환경 분리 | 일반 GNOME `--mode=user`, 새 앱에 픽셀 세션 환경 변수 없음 |
| 서명·SHA | Ed25519와 인덱스·제공 아카이브 SHA 확인, 소스와 네이티브 후보 일치 |
| 기존 설치 패키지 | 221개 모두 기존 버전·SHA 유지 |
| 기존 게스트 파일 | 관리자·KI2·GNOME 실행 파일·세션·기본 dconf 등 14개 SHA·권한 일치 |
| 호스트 보호 목록 | 0단계 기준선 5,485개 파일 변경 없음, 종료 시 메타데이터 재확인 |
| 실패 단위 | 시스템·사용자 서비스의 실패 항목 없음 |

초기 화면 검사 중 GNOME 자동 잠금·절전으로 렌더링을 캡처하지 못한 기록은 보존했다.
정상 암호 인증으로 잠금을 해제하고, 최종 검사 동안만 세션의 일시적인 idle inhibitor를 사용했다.
검사 후 해제를 확인했으며 잠금·절전 정책 자체를 바꾸지 않았다. 각 GTK 검사의 설정 디렉터리도
분리해 이전 검사 값이 다음 검사를 오염시키지 않도록 했다.

CPU가 높은 GTK 시험 캡처는 실제 초기 측정값이다. 실제 운영 앱 실행 후에는 0.0%의 유휴 측정값과
지속 갱신을 별도로 확인했다. 시험 캡처를 성능 측정 결과로 사용하지 않는다.

증거: `artifacts/kiki-operations/20261106-stage12/acceptance.json`, `ui-test-final.log`,
`live-validation.json`, `original-runtime-preserved.json`, `gnome-final.json`, `install-final.log`.

## 실제 화면

![일반 GNOME에서 실행한 독립 운영 화면](../artifacts/kiki-operations/20261106-stage12/desktop-final.png)

![다크 모드](../artifacts/kiki-operations/20261106-stage12/final-operations-dark.png)

![900×700 작은 창](../artifacts/kiki-operations/20261106-stage12/final-operations-compact.png)

## 후속 범위

새 앱의 로그·터미널·incident-ai 메뉴는 현재 지원 범위를 안내한다. 관리자 진입 버튼은 제공하지만,
선택 서비스의 인라인 로그·Console 점검 명령·incident-ai 문맥 전달·새 앱 내부 변경 승인과
서비스 재시작은 아직 구현하지 않았다. 브라우저 공급과 HTTPS 기본 앱 등록도 후속이다.
로그인 자동 실행은 변경하지 않았으며 이번 실행은 수동 시험이다.

기존 portal Inhibit 인터페이스·Hyper-V 소프트웨어 EGL 경고는 남아 있다. 실제 화면 렌더링은 통과했으며,
새 앱의 GTK CSS 오류·치명 오류는 확인되지 않았다. 기존 SDK·선택 서비스 경고의 정리는 별도 범위다.
독립 compositor·패널·로그인 세션이나 Xfce 수준의 경량화 완료, 새 ISO 설치 통과를 의미하지 않는다.
