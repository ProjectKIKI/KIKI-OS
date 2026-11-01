# KIKI Build v1.0 RC1 검증 기록

검증 종료일: 2026-11-01(한국시간). 기능 설명과 지원 범위는 [운영 안내](kiki-build-v1.ko.md)에 정리했다. 이 문서에는 비밀번호·토큰·개인키를 기록하지 않는다.

## 구현과 운영 반영

- 신규 패키지 등록: 문서 copy 및 HTTPS 소스 템플릿, 저장 전 검토, 중복·의존성·URL/SHA 검증, 작업별 입력 고정.
- 그룹 관리: 패키지/선행 그룹 검색 선택, 프로필 연결, 서비스 설정, 구성 미리보기, 충돌 감지와 입력값 보존.
- VM 그룹: `vm-common`, `vm-kvm`, `vm-hyperv`. 설치기·CLI 카탈로그 16개 그룹 동기화.
- 산출물 통합: 패키지·소스·ISO, SHA·명세·VM 보고서, 필터와 50개 단위 페이지 이동.
- 홈 집계: 보관 패키지·완료 ISO를 작은 요약 API로 표시. 이전 경로의 0개 집계와 혼동하던 문제 수정.
- Local LLM: 사용자 PC의 `127.0.0.1:8080/v1`, `kiki-ops` 실제 응답. 로그 분석과 KI2 TOML 초안, 자격증명 제거, 답변 이력, 자동 적용 없음.
- 운영 안정성: 종료 신호 처리, 이미지 digest 기록, 선택 프로필의 의존성 검사, 보관소 쓰기 잠금·세대 충돌 검사, 스냅샷보다 먼저 목록 영속화, 백업/새 경로 복원과 정리 미리보기.

웹 편집본은 r8이다. 원본 일반 레시피 150개와 웹 등록 문서 패키지 1개를 함께 관리한다. 별도 native SDK에서 만든 GNOME 서명 바이너리는 일반 레시피 수와 별도 집계한다.

## 자동 검사와 브라우저

| 검사 | 결과 |
|---|---|
| Linux Python 회귀 검사 | 490개 실행, 486개 통과, 환경 조건 4개 건너뜀 |
| 후속 로그 자격증명 제거 검사 | 헤더 접두사·JSON Authorization·쿠키·부분 개인키·URL 인증정보 포함 통과 |
| 설치기 Go 검사 | 통과 |
| 실제 빌드 서버 기본 검사 | 20단계 통과, 작업 `20261031-150446-4324` |
| 깨끗한 디렉터리의 패키지 재생성 | 고정 SOURCE_DATE_EPOCH에서 동일 아카이브 SHA |
| 실제 인증 DB·Ed25519 키 복원 | 로그인 유지, 키 일치, 기존 세션 폐기 확인 |
| 신규 등록→실제 KI2 빌드 | 격리 브라우저 및 운영 서버에서 통과 |
| 그룹 생성·미리보기·입력 오류 보존 | 브라우저 통과 |
| 1440px/390px 표시 | 검색 정렬·모바일 가로 넘침·콘솔 오류 검사 통과 |
| 실제 운영 계정 | 신규 메뉴·VM 그룹·산출물 검색/ISO 필터·페이지 이동·AI 답변 이력 확인 |

운영 등록 시험에는 `kiki-build-v1-guide` 문서 패키지를 사용했다. 최종 입력 기록을 갖는 작업은 `20261031-144253-7626`이다. 일반 패키지 빌드가 다른 미완성 레시피에 막히던 문제와 보존 소스/시험 파일의 버전 불일치를 수정했다. 전체 소스 감사는 미완성 항목을 계속 오류로 알린다.

## ISO와 실제 설치

| 항목 | 값 |
|---|---|
| ISO 작업 | `01e17ae15f454eca899e1314a49ff9ea` |
| 스냅샷 | `build-v1-rc1-vm-20261031` |
| ISO | `kiki-build-v1-rc1-vm-20261031-gnome50-x86_64-01e17ae1.iso` |
| 크기 | 1,252,876,288 bytes |
| ISO SHA-256 | `a2a44d3f9c508ffda5a3a53ae29208a33b5878ce6227365a9e98634532e46067` |
| 카탈로그 SHA-256 | `fa31119f8e4cf1edba351bb1c03be9ca28403a183a41eb8bfd22d904c9716222` |
| 내장 패키지 | 231개 |
| 설치 선택 | GNOME + 보안 검사 + vm-kvm, 의존성 포함 220개 |
| 설치된 VM | `kiki-iso-01e17ae15f45-installed` |
| VM UUID | `2705597e-4e64-49dd-8ec5-ce5b4c227698` |
| 프로젝트 | `custom-lab-user-7` |
| IP | `10.250.251.73` |

실제 ISO 무인 설치 후 디스크로 부팅하고, 재부팅해서 같은 검사를 반복했다. 두 부팅 ID는 다음과 같다.

- `f1153f93-959c-45e0-9106-cf3a5dc7fe8c`
- `a1e4ac21-69ad-432c-8ab1-339085a132d9`

각 부팅에서 34개 검사, 패키지 SHA/정확한 설치 집합 220개, 중요 파일 41개와 OpenSCAP 9/9가 통과했다. nmcli/readline, GNOME 기본 앱, 그래픽 대상, 기본 저장소 서명, 시각 동기화, SSH 정책, 실제 방화벽 패킷 차단도 포함한다. QEMU 설정·유닛·진단 명령의 SHA도 중요 파일에 포함했다.

GDM 로그인 화면을 하이퍼바이저에서 직접 캡처해 확인했다. 실제 GUI 사용자 세션 로그인은 자동화하지 않았으므로 `gdm_login_tested`는 false로 유지한다. BIOS·UEFI 구조 검사를 했으며 실제 VM 부팅은 UEFI다. Secure Boot는 서명하지 않았다.

프로젝트 RAM 할당량 때문에 디스크 VM 생성이 한 번 보류됐다. 설치가 끝난 이번 작업의 설치용 VM만 8GiB에서 2GiB로 줄여 재개했다. 서명 입력은 유지했고 사용 중이던 기존 GUI VM은 변경하지 않았다. 설치용 VM UUID는 `d8f7dfb0-34c0-460e-a35c-be45c7658aec`다.

## virtio 게스트 에이전트

확인한 설치 디스크 스냅샷에서 네트워크 없는 2GiB 시험 복제본을 만들고 부팅 볼륨에 `hw_qemu_guest_agent=yes`를 설정했다.

- VM: `kiki-v1-qga-isolated-20261031`
- UUID: `ae9934a8-310c-4b05-af9d-24e0b676c0ba`
- 복제 볼륨: `7d01a27e-02ac-46cd-858e-6cf16128b85e`
- 실제 virtio 채널의 QEMU agent 11.1.3 `guest-ping` 응답과 KIKI OS/커널 정보 조회 통과.
- `guest-exec`, `guest-file-open`, `guest-set-user-password` 비활성 확인.
- 원본 SDK의 실제 바이너리 Unix 소켓 시험도 통과.

시험 복제본은 증적을 저장한 뒤 종료했다. 사용자가 전원 종료 상태의 보존을 선택했으므로 VM과 32GB 복제 볼륨을 삭제하지 않는다. 설치 완료 VM과 스냅샷도 보존한다. 이 RC1 기록 이후의 Hyper-V 실기 검증은 정식 릴리즈 검증 문서에 별도로 기록한다.

## 증적

작업공간의 비공개 `artifacts/`에 다음 결과를 보관했다.

- `build-v1-regression-tests.log`, `build-v1-production-smoke.json`
- `build-v1-production-acceptance.json`, `build-v1-iso-result.json`
- `build-v1-openstack-validation.json`, `build-v1-virtio-agent-proof.json`
- `build-v1-runtime-gdm.png`, `build-v1-groups-ui.png`, `build-v1-registration-mobile.png`

안정 업데이트 채널은 `update-55f351d06ff14a20a8746e49f5e2e7de`로 유지했다. Git 커밋·푸시 또는 GA 태그 발행은 이번 구현 결과에 포함하지 않는다.
