# KIKI 운영 1단계 — 보존 기준선·후보 상태 재확인

2026-11-10, 한국 시간. 기존 보존 기준선을 교체하지 않고 현재 파일과 대조했다.
빌드 서버와 Hyper-V 후보는 읽기 전용으로 점검했다. incident-ai 자동 연동은 계속 보류한다.
호스트 화면·키보드·마우스·클립보드를 조작하지 않았고 VM 전원·로그인·잠금 상태도 바꾸지 않았다.

이 문서의 디스크 용량은 11월 10일 점검 당시 값이다. 이후 빌드 볼륨의 200GiB 확장과
서비스 복구는 [11월 12일 확장 완료 기록](kiki-build-disk-expand-20261111.ko.md)을 따른다.

## 판정

**보존·후보 정합성 재확인은 통과했다. 다음 대규모 빌드·ISO 작업 전에는 서버 용량 계획이 필요하다.**
현재 후보는 여전히 설치 환경 시험용 오버레이이며 새 ISO·릴리즈 공급본으로 승격하지 않았다.

| 검사 | 결과 |
|---|---|
| 기존 보존 기준선 | 5,485개 파일 SHA-256 재대조, 변경·누락 0개 |
| 이전 운영 후보 | 42개 파일 SHA-256 재대조, 변경·누락 0개 |
| 최신 후보 추가 검사 | 보유 패키지 6개와 인덱스 1개 SHA 일치 |
| 전체 | 5,534개 경로 확인. 동일 파일 식별자를 재사용해 실제 3,516개 파일·42,859,925,063바이트 해시 |
| 남은 ISO | 5개 모두 기존 SHA와 일치 |
| 승인 후 삭제한 ISO | 22개 모두 삭제 상태 유지. 복원·추가 삭제 없음 |
| 최신 후보 서명 | 고정 공개키 SHA 및 Ed25519 메타데이터 서명 재검증 통과 |
| 빌드 서버 후보 | 인덱스와 보유 패키지 6개 SHA 모두 일치 |
| VM 설치 레코드 | 225개 모두 후보 인덱스와 일치 |
| VM 실제 파일 | 운영 앱·브라우저 관련 패키지의 일반 파일 286개 SHA 및 심볼릭 링크 대상 일치 |
| 기존 GNOME·관리자·Polkit | 원본 파일 13개 SHA·모드 일치 |
| 공용 GTK 계열 | 원본 파일 21개 SHA 일치 |
| GNOME dconf | 이전 검증 SHA와 일치 |

이전 검증 결과를 재사용한 메타데이터 확인만 수행한 것이 아니라 이번에 전체 내용 SHA를 다시 계산했다.
원본 기준선·원본 패키지·기존 후보·설치기·ISO를 덮어쓰지 않았다.
가동 중인 VM의 VHDX 전체 SHA는 고정값으로 판정하지 않았다. 대신 VM 식별자·디스크 연결과 게스트 내부 파일을 검사했다.

## 빌드 서버

기존 빌드 서버 `lab@external.terminal-lab.kr:41816`에 접속했다. 실제 호스트는
`build-server.novalocal`이며 incident-ai 서버에 접속한 것이 아니다. 점검 후 SSH 연결을 종료했다.

| 항목 | 현재 상태 |
|---|---|
| 가동 시간 | 약 15일 22시간 |
| 루트 파일시스템 | 19GiB 중 약 7.4GiB 사용, 약 11GiB 여유 |
| 빌드 볼륨 | `/dev/vdb1`, XFS, `/build-kikios` 마운트 |
| 빌드 볼륨 UUID | `828cebec-78b6-476a-8950-e3394c1c9d22` |
| 빌드 볼륨 용량 | 100GiB, 사용률 94%, 여유 7,264,538,624바이트 ≈ 6.8GiB |
| 자동 마운트 설정 | `/etc/fstab`에 해당 UUID·경로 항목 존재 |
| SELinux | Enforcing 유지. 마운트 `mnt_t`, 작업 루트 `user_home_t` |
| 격리 Meson | 기존 venv의 `meson --version`이 1.9.2 반환 |
| 컴파일러 | GCC 11.5.0 |
| 기존 SDK | 존재. GLX 헤더·cairo-xlib pkg-config 추가 없이 이전 상태 유지 |
| 시스템 실패 유닛 | 0개 |
| 사용자 실패 유닛 | 아래 임시 서비스 2개 |
| 빌드 웹 | 로컬 80번 응답 HTTP 200. 외부 도메인·로그인 동작은 이번에 검증하지 않음 |
| 컨테이너 | buildd·release-worker·auth·LLM relay 4개 running |

사용자 실패 유닛은 다음과 같다. 실패 상태를 지우거나 재시작하지 않았다.

- `kiki-ingress-check.service`: transient, `Result=timeout`, 2026-10-25 실행·종료 기록.
- `kiki-temp-repo-20261028.service`: transient, `Result=timeout`, 2026-10-28~29 실행·종료 기록.

두 항목은 오래된 임시 점검의 시간 제한 종료 기록이다. 현재 운영 컨테이너는 실행 중이지만
이 사실만으로 모든 빌드 작업·외부 접속·백업 기능의 정상 동작까지 확인한 것은 아니다.

읽기 전용 `du`의 주요 사용량은 다음과 같다. 공유·reflink 여부에 따라 수치가 중복될 수 있어
이 값을 그대로 더해 회수 가능 용량으로 계산하면 안 된다.

| 경로 | `du` 사용량 |
|---|---|
| `/build-kikios/kiki-build/candidates` | 약 89GiB |
| `/build-kikios/kiki-build/kiki-operations-20261107-stage4` | 약 6.9GiB |
| `/build-kikios/kiki-build/host-prep-20261023` | 약 1.7GiB |

소스·캐시·과거 후보의 삭제 가능 여부는 아직 분류하지 않았다. 이번에는 어떤 항목도 삭제하지 않았다.
추가 볼륨 확장 또는 보존 대상과 분리된 재생성 가능 작업 공간 확보 방안을 먼저 정해야 한다.
현재 정보만으로 다음 전체 빌드·ISO 생성에 정확히 필요한 용량을 확정하지 않는다.

## Hyper-V와 GNOME 후보

실행 중인 KIKI VM은 `kiki-paper-pixel-candidate-r4-20261105` 하나다.
원본 GA와 baseline·이전 픽셀 후보·다른 KIKI 시험 VM은 모두 Off 상태였다.

| 항목 | 확인값 |
|---|---|
| 후보 UUID | `eb043387-6b63-42a3-9e8b-239a2a482846` |
| MAC / IP | `00155D01036A` / `172.22.249.207` |
| 디스크 | `E:\dev\KIKI-OS\artifacts\server-shell\20261105-stage1\candidate-r4\independent.vhdx` |
| 호스트 E: 여유 | 37,018,218,496바이트 ≈ 34.5GiB, 점검 시작 시점 |
| 게스트 | `kiki-v1-hyperv`, 약 4일 15시간 가동 |
| 게스트 루트 | 24GiB 중 약 2.9GiB 사용, 약 20GiB 여유 |
| GDM | active |
| 사용자 세션 | Wayland, active, `LockedHint=yes` |
| 실패 유닛 | 시스템 0개·사용자 0개 |
| 기존 프로세스 | GNOME Shell·KIKI 운영·전용 Firefox 실행 상태 유지 |
| 동적 연결 | KIKI 운영 실행 파일·Firefox libxul의 `ldd` 누락 없음 |
| 임시 시험 자원 | 이전 시험 서비스 없음, 디버그 2828 포트 폐쇄 상태 |

실제 프로세스 매핑에서 GNOME Shell과 KIKI 운영은 공용 `/usr/lib` GTK4/Cairo/Epoxy를 사용하고,
Firefox는 전용 `compat` GTK3/Cairo/Epoxy를 사용한다. 공용 라이브러리를 교체하지 않았다.

설치 레코드의 주요 버전은 GTK4 4.22.4, GTK3 3.24.52, Libadwaita 1.9.3, VTE 0.84.1,
GNOME Console 50.0, Nautilus 50.2.2, Settings 50.4, GNOME Shell 50.4, GDM 50.2,
KIKI 운영 0.1.0-7이다.

잠금을 해제하거나 앱 창을 새로 열지 않았다. 따라서 이번 결과는 기존 GNOME 앱 파일 보존·
라이브러리 연결·세션 상태에 대한 확인이며 새 로그인·Polkit 인증창·재부팅·시각적 UI 재시험 결과는 아니다.
이전 EGL·portal Inhibit 경고의 해소 여부도 이번 범위에서 다시 판정하지 않았다.

## 후보 식별과 증거

최종 후보 인덱스 SHA-256:
`4ae47bbd46c977f4bf2628cd53dc0bbe063fa9b72750fcdde26851083e8e207a`

고정 공개키 SHA-256:
`22122bb259fb1d61c21bf0db35c439cedbf631cb2f1c5cc8af07ef23e3a24f2f`

- 호스트: `E:\dev\KIKI-OS\dist\ki2\kiki-operations-ga-20261107-stage4-full-r2`
- 서버: `/build-kikios/kiki-build/kiki-operations-20261107-stage4/candidate-full-r2`
- 게스트: `/var/lib/kiki-operations/candidate-20261107-stage4-full-r2`
- 이번 증거: `E:\dev\KIKI-OS\artifacts\kiki-operations\20261110-stage1`
- 증거 파일: `preservation-result.json`, `preservation-current-files.json`, `candidate-signature.json`,
  `hyperv-state.json`, `guest-state.json`, `build-server-state.json`, `build-server-details.json`, `acceptance.json`.

서버 후보도 동일 인덱스 236개 레코드·보유 패키지 6개다. 서버의 모든 기존 산출물 전체를
해시한 것은 아니며 서버 후보 6개와 인덱스, SDK 존재·특정 기능 부재 상태를 확인한 범위다.
현재 서버 컨테이너가 Gitea 최신 커밋을 사용하는지는 이번 점검으로 확정하지 않았다.

## 다음 작업의 선행 조건

1. 서버 여유 공간 확보 계획을 수립한다. 기존 설치기·원본 패키지·남은 ISO·필요 후보는 보존한다.
2. 새 운영 앱용 후보 프로필 구성 전에 서버 빌드 소스의 Git 커밋과 의존성 잠금을 확인한다.
3. 기존 픽셀 세션 프로필과 별도로 운영 앱 포함 범위를 정하고 새 작업 경로에서 구성한다.
4. 새 프로필 단계에서 로그인 자동 실행·재실행·GNOME 앱 회귀와 이후 ISO 시험을 진행한다.

이번 작업은 위 후속 단계·삭제·재빌드·배포를 실행한 것이 아니다.
incident-ai 자동 연동 후보 소스는 수정·테스트·배포하지 않았으며 보류를 유지했다.
Git 커밋·푸시도 수행하지 않았다.

[기능 완료·보류·재개 기록](E:/dev/KIKI-OS/docs/kiki-operations-progress-and-resume-20261108.ko.md)
