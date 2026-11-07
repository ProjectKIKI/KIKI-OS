# KIKI 운영 3단계: 서비스 로그와 Console 연결

2026-11-07 별도 후보에서 구현·네이티브 빌드·Hyper-V 검증을 마쳤다.
최종 패키지는 `kiki-operations 0.1.0-6`이다. 기존 GNOME Wayland 세션 안에서
KIKI 앱 자체 화면만 확장했으며, GNOME Shell·기존 관리자·설치기를 교체하지 않았다.

## 사용 흐름

1. 운영 개요 또는 서비스 목록에서 서비스를 선택한다.
2. **관련 로그**를 누르면 이번 부팅의 해당 서비스 최근 200줄을 사용자 권한으로 조회한다.
   시스템 저널 접근 제한 안내와 사용자/시스템 범위를 구분한다. `No entries`는 전체 시스템에
   로그가 없다는 뜻이 아니다. 로그는 버튼으로 갱신하며 지속 추적 스트림은 아니다.
3. **시스템 로그 인증 조회**에서는 대상 서비스와 조회 명령을 먼저 표시한다.
   **인증하고 조회**를 누르면 기존 GNOME Polkit 창이 열린다.
4. 인증 성공 시 선택한 서비스의 시스템 로그를 표시한다. 취소·거부 시 인증 결과를 표시하지 않는다.
5. **Console 점검**에서 서비스 상태 또는 최근 사용자 로그 명령을 확인하고
   **Console에서 점검 실행**으로 기존 GNOME Console을 연다.
   종료 코드와 출력은 Enter까지 유지한다. 이후 Console이 읽기 전용 결과 창을 남길 수 있으므로
   창은 닫기 버튼으로 닫는다. 안내도 이 동작에 맞췄다.

서비스를 바꾸거나 선택한 서비스가 목록에서 사라지면 로그·승인 창·명령 계획을 초기화한다.
조회 시작 시의 서비스와 세대 번호가 현재 선택과 일치하지 않으면 늦은 응답을 버린다.
같은 서비스의 정기 목록 갱신은 진행 중인 정상 인증을 무효화하지 않는다.

## 재사용과 구현 경계

| 경로 | 동작 |
|---|---|
| `kiki-adminctl logs UNIT` | 기존 사용자 로그 API 재사용 |
| `kiki-adminctl plan system-logs UNIT` | 기존 조회 계획·대상·확인 토큰 재사용 |
| `pkexec /usr/libexec/kiki-admin-helper system-logs UNIT TOKEN` | 기존 Polkit 정책·PAM·helper로만 인증 조회 |
| `kiki-operationsctl logs / log-plan / terminal-plan` | 앱용 스키마·서비스 검증·고정 Console 실행 계획 |
| `kgx -- /usr/libexec/kiki-operations-console status UNIT` | 일반 사용자 `systemctl --no-pager --full status -- UNIT` |
| `kgx -- /usr/libexec/kiki-operations-console logs UNIT` | 일반 사용자 `journalctl --boot --no-pager --output=short-iso --lines=200 --unit=UNIT` |

서비스명은 기존 관리자와 같은 제한된 `.service` 형식으로 검증한다. Console 프로그램·래퍼·모드·대상은
고정 argv를 대조하며 임의 명령이나 셸 실행 API를 추가하지 않았다. GAppInfo의 명령 문자열은
각 인수를 GLib 규칙으로 인용하고, 래퍼도 `subprocess.run(argv)`로 실행한다.
Console에는 sudo·pkexec·자동 비밀번호 입력 기능이 없다.

기존 `org.kiki.admin.apply` 정책·helper·백엔드의 SHA와 모드는 유지했다.
따라서 기존 공용 Polkit의 “시스템을 변경하려면…” 문구도 그대로다. 이 화면에서 실행하는 작업은
선택 서비스의 읽기 전용 로그 조회이며 새 관리자 권한이나 인증 우회 규칙을 만들지 않았다.

일반 연결 조회 제한은 35초, 인증 대기는 150초다. 서비스 변경·닫기·만료 시 필요한 정리와
콜백 수명 처리를 수행한다. 시스템 로그는 GUI 버퍼에만 표시하며 별도 로그 파일로 자동 저장하지 않는다.
이번 검증에서 만든 증거 파일은 명시적 시험 기록이다.

## 빌드와 후보

- 입력 잠금: `distro/manifests/kiki-operations-20261107-baseline.json`을 `--lock`으로 명시.
  실제 GA의 221개 패키지 SHA와 Console 의존성 build key를 고정했다.
- 기존 SDK 사용: GTK 4.22.4, Libadwaita 1.9.3, VTE 0.84.1, GNOME Console 50.0.
  GCC 11.5로 대상 sysroot를 명시하고 경고를 오류로 취급했다.
- 최종 호스트 후보: `dist/ki2/kiki-operations-ga-20261107-r3`.
- 빌드 서버: `/build-kikios/kiki-build/kiki-operations-20261107-r1/candidate-r3`.
- 게스트 후보: `/var/lib/kiki-operations/candidate-20261107-r3`.
- 시험 VM: `kiki-paper-pixel-candidate-r4-20261105`, 일반 GNOME `--mode=user`, Wayland.
- 설치 계획은 `kiki-operations` 하나만 변경했다. 기존 221개 기록 유지, 총 222개.
  기존 KI2는 `0.1.0-37`을 유지했다. 최종 payload 파일 10개의 SHA가 설치 후 일치했다.
- 인덱스 233개, 실제 아카이브 3개의 설치된 GA 전용 오버레이다. `not_for_iso=true`이며 새 ISO를 만들지 않았다.
  11월 6일 후보와 이번 r1·r2는 덮어쓰지 않았다. 개인 서명 키는 빌드 서버 밖으로 복사하지 않았다.

| 최종 항목 | SHA-256 |
|---|---|
| 소스 번들 `source-r3.tar.gz` | `5838e717cfa95f31fb8ee2fb142a033b21bc94b0c934d43b717cd454bd8721a8` |
| `kiki-operations-0.1.0-6.x86_64.ki2` | `2e35251c9f98386c785dcdaec84bd63cd931d1cbb9c2216eafd5dde706edaa82` |
| `index.x86_64.json` | `32154c2c694f0cdc1d652609d14520cba7e3d179883b818decc9c6d136e1d865` |
| 결과 번들 `results-r3.tar.gz` | `768d59d0ed92d91338afb65477d1964b3d1d401479e35e4247c80cdf04afb5af` |

SHA·Ed25519 서명·의존성 폐쇄·payload audit 통과 후에만 게스트에 설치했다.
원본/후보 경로와 서명 키 경로는 빌더에서 분리한다.

## 실제 검증 결과

| 검사 | 결과와 증거 |
|---|---|
| Python 단위 시험 12개 | 로컬·네이티브 서버 통과. 잘못된 서비스명, 대상 불일치, 권한 계획, 셸 없는 argv, 결과 유지, 오류 전달 포함 |
| 실제 GTK 시험 | 최종 후보 `ui-test-r4.log` 통과. 검색·실패 필터·선택·실제 로그 조회·미리보기·승인 전 취소·서비스 변경 후 이전 응답 폐기·조회 중 닫기 |
| 테마·창 크기 | 라이트·다크·고대비와 실제 900×700 통과. 숨은 페이지의 최소 크기 영향을 줄이고, 시험은 최대화 해제가 완료된 후 크기를 검사 |
| 시스템 로그 성공 | 시험 서비스 A의 고유 journal marker만 표시. 기존 pkexec·Polkit PAM 세션 기록 확인. 최종 0.1.0-6에서도 재확인 |
| 실제 인증 취소 | 서비스 B는 새 인증 창이 열림. Escape 취소 후 빈 로그·취소 안내 표시, 이전 A marker 없음. 동일 연결 코드의 0.1.0-5에서 실행 |
| Console 상태 | 시험 서비스 B와 실제 NetworkManager에서 정확한 서비스 인수·UID/EUID 1000·결과·종료 코드 확인. 최종 0.1.0-6의 보완 안내도 확인 |
| Console 사용자 로그 | B의 `journalctl` 고정 인수·UID 1000·접근 제한 안내·Enter까지 대기 확인. 0.1.0-5에서 실행, 최종 변경은 공통 결과 안내 문구 |
| 서비스 제거 | 시험 서비스 제거 후 선택이 해제되고 인증 로그가 즉시 비워짐 |
| 최종 런타임 | 동적 라이브러리 누락 없음. 시스템·사용자 실패 서비스 없음. GNOME Wayland 활성 유지 |
| 시험 정리 | 내용 SHA를 확인한 `/run/systemd/system/kiki-ops-log-{a,b}.service`만 삭제. 점검 Console과 래퍼 종료. 임시 idle inhibitor 해제, `IsInhibited(8)=false` |

시험은 SSH·게스트 접근성 API·후보 VM의 가상 키보드/프레임 API로 수행했다.
호스트 왼쪽 화면의 입력·포커스·마우스와 기존 VM은 조작하지 않았다.

## 보존과 남은 범위

- 보호 파일 **5,485개 전체 SHA 재검증 통과**, 변경 0개. 설치기·원본 패키지·남은 ISO 5개와
  기존 후보를 유지했다. 이미 승인받아 삭제했던 ISO 22개는 복원하거나 새로 삭제하지 않았다.
- 게스트 GNOME 세션·Shell·Console·Files·설정·KI2·관리자·Polkit 불변 파일 13개의 SHA와 모드가 과거 기준과 같다.
- 사용자 dconf의 과거 SHA는 달랐지만 수정 시각이 **2026-11-06 09:25:43 KST**로 이번 시험 전이다.
  기존 사용자 변경을 초기화하지 않았다. 현재 SHA
  `4c1acecb8e7aaa5ff7b05b161bd30c656a59ffe843791255a1f2004fe8c5e511`이 최종까지 유지됨을 확인했다.
  KIKI 테마·필터와 GTK 시험 설정은 자체 키파일에 저장한다.
- 기존 portal Inhibit 인터페이스 경고와 EGL 경고는 남아 있다. 이번 GTK 화면·Console 실행은 통과했지만
  하드웨어 GPU 가속이 검증됐다는 뜻은 아니다.
- incident-ai 문맥 연결, 서비스 재시작 승인, 로그인 자동 실행은 후속 범위다.
  웹 UI 변경·릴리즈 승격·원본 저장소 덮어쓰기·ISO 생성은 이번 단계에 포함하지 않았다.

기계 판정과 원시 증거는 `artifacts/kiki-operations/20261107-stage3/acceptance.json`,
`build-r3.json`, `install-r3.log`, `ui-test-r4.log`, `final-runtime.jsonlog`,
`original-runtime-final.json`, `screenshots/`에 보관한다.
이전 기록은 [0단계](kiki-operations-stage0-20261106.ko.md),
[1·2단계](kiki-operations-stage12-20261106.ko.md)를 참고한다.
