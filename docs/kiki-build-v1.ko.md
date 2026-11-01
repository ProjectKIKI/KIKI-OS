# KIKI Build 1.0.0

2026-11-01 기준. x86_64 단일 Linux 빌드 서버용 정식 빌드 도구다. KIKI OS 전체의 범용 하드웨어 지원 선언과 구분한다. 패키지·ISO 생성 성공과 실제 설치·보안·GUI 검증은 별개 상태로 표시한다.

## 웹에서 사용하는 기능

- **패키지 → 새 패키지 등록**: HTTPS 소스 압축파일(GNU/CMake/Meson) 또는 로컬 문서 copy 템플릿을 선택한다. 이름·버전·라이선스·의존성·소스 SHA를 검사한다. 미리보기는 저장하지 않으며, 저장한 레시피는 편집본 이력으로 보관한다. 실제 컴파일에는 해당 의존성과 SDK가 필요하다.
- **패키지 상세**: 메타정보를 수정하고 해당 패키지의 개별 빌드로 이동한다. 이미 보관된 바이너리의 메타정보를 바꾸지 않는다.
- **패키지 그룹 관리**: 필수·기본·선택 패키지와 선행 그룹을 검색해 추가하고 프로필에 연결한다. 펼친 구성과 서비스 충돌을 저장 전에 확인한다. 오류가 있으면 입력값을 유지한다. 편집본 번호가 달라지면 충돌을 알린다.
- **산출물**: 보관 패키지·소스 압축파일·작업별 ISO와 아직 보관소에 동기화되지 않은 완료 패키지를 함께 조회한다. 검색·종류 필터·페이지 이동을 지원한다. 다운로드, SHA, 명세, VM 검사 보고서로 연결한다.
- **운영·복구**: 지원 범위, 저장 공간, 보존·정리 미리보기와 백업·복원 방법을 확인한다. 임시 작업 정리는 자동으로 실행하지 않는다.
- **Local LLM 보조**: 선택한 작업의 로그 분석이나 KI2 TOML 레시피 초안을 요청한다. 최근 답변, 모델, 입력 SHA, 자격증명 제거 건수를 보관한다. 답변을 명령 실행·레시피 저장·빌드·배포로 자동 연결하지 않는다.

그룹 편집만으로 이미 만든 ISO나 설치된 시스템이 바뀌지 않는다. 동일 카탈로그의 `ki2ctl`, GTK/TUI 설치기를 다시 패키징하고 새 서명 스냅샷과 ISO를 생성해야 한다. 이번 설치기 카탈로그 SHA는 `fa31119f8e4cf1edba351bb1c03be9ca28403a183a41eb8bfd22d904c9716222`다.

## VM 그룹과 드라이버

| 그룹 | 포함 기능 | 기본 서비스 |
|---|---|---|
| `vm-common` | `kiki-vm-tools`, `kiki-vm-status` 읽기 전용 진단 | 추가 없음 |
| `vm-kvm` | QEMU guest agent 11.1.3, virtio 채널 연동 | `qemu-guest-agent.service` |
| `vm-hyperv` | Linux 6.1.187의 KVP·VSS·파일 복사 데몬 | KVP·VSS, 파일 복사는 기본 비활성 |

현재 커널에는 virtio 디스크·SCSI·네트워크·GPU·콘솔과 Hyper-V 저장소·네트워크·유틸리티 드라이버가 포함되어 있다. 사용자 공간 에이전트를 추가하며 기존 GNOME의 `graphical.target`을 바꾸지 않는다. 잘못된 하이퍼바이저에서는 서비스 조건에 의해 실행을 건너뛴다. KVP의 호스트 요청 네트워크 재설정은 지원하지 않으며 게스트 안에서 NetworkManager/systemd-networkd로 설정한다.

QEMU 에이전트에는 호스트의 `org.qemu.guest_agent.0` virtio 채널이 필요하다. OpenStack에서는 이미지/부팅 볼륨의 `hw_qemu_guest_agent=yes` 설정도 확인해야 한다. 파일·명령 실행·비밀번호 변경 RPC는 허용하지 않는다. GNOME의 SPICE 클립보드, 폴더 공유, 가속 GPU 등은 별도 기능이며 이 그룹만으로 제공된다고 표시하지 않는다.

## Local LLM 연결

현재 원본 API는 사용자 Windows PC의 `http://127.0.0.1:8080/v1`, 모델은 `kiki-ops`다. 모델 다운로드나 외부 AI 서비스로의 대체 전송은 하지 않는다.

Windows의 `tools/start_ki2llm_bridge.ps1`가 기존 SSH 키와 고정 known_hosts를 사용해 빌드 서버의 `127.0.0.1:18080`에서 PC의 `127.0.0.1:8080`으로 역방향 연결을 만든다. 서버의 `kiki-build-llm-relay`는 제한된 Unix 소켓으로 CI와 연결한다. CI 컨테이너의 네트워크 격리는 유지한다. 서버 소켓과 설정은 접근을 제한한다. PC와 모델 서버가 꺼지면 명확한 연결 오류를 표시하며 다른 모델로 보내지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\dev\KIKI-OS\tools\start_ki2llm_bridge.ps1
```

다른 환경에서는 `deploy/assistant/bridge.example.json`을 비공개 위치에 복사해 계정·키 경로·known_hosts를 설정한다. Python Paramiko가 필요하다. 서버 유닛 예시는 `deploy/systemd/kiki-build-llm-relay.user.service`다. 관리자만 연결 설정을 바꿀 수 있고 운영자는 분석·초안을 요청할 수 있다. 조회자는 쓰기 요청을 할 수 없다.

로그는 최근 128KiB를 읽고 자격증명과 개인키·쿠키를 제거한 다음 최대 6KiB를 모델에 전달한다. 응답은 HTML로 실행하지 않는다. 입력은 신뢰할 수 없는 로그로 취급하며 모델의 추론은 검토가 필요한 제안이다. 한 번에 한 추론 요청만 처리한다.

## 입력 고정과 재현성

작업의 `build-inputs.json`에는 빌드 버전, 도구 체인, Python·컴파일러, 실행 이미지 digest, Git 소스 커밋/아카이브, 빌드 엔진 SHA, 편집본과 레시피 digest를 기록한다. 작업 상세에서 다운로드할 수 있다. 재시도는 이전 편집본과 빌드 엔진을 재사용한다. 전체 소스 재현에는 Git 커밋 고정을 사용한다. 수정 가능한 보존 작업공간을 사용하는 경우에는 유지보수 전 소스 백업도 함께 보관해야 한다.

`SOURCE_DATE_EPOCH`를 고정하면 KI2 패키지의 생성 시각·tar 시각·gzip 헤더를 정규화한다. 서로 다른 빈 디렉터리와 파일 시각에서 문서 패키지를 두 번 생성해 아카이브 SHA가 같음을 검사했다. 모든 upstream 컴파일러, 전체 GNOME 또는 ISO가 바이트 단위로 재현된다고 보증하는 의미는 아니다.

작업자는 종료 신호를 처리한다. 대기 작업은 재시작 후 이어지고, 실행 도중 종료된 작업은 중단으로 남겨 명시적으로 재시도한다. 보관소에는 프로세스 간 쓰기 잠금과 목록 세대 검사를 적용해 오래된 프로세스가 새 스냅샷 참조를 덮어쓰지 못하게 한다. 유지보수 import는 실행 중인 작업자의 lease를 획득할 수 없으면 거부해야 한다.

## 백업과 새 서버 복원

작업이 없는 유지보수 시간에 별도 볼륨을 준비한다. 전체 release store에는 큰 패키지·ISO와 비공개 서명 키가 들어 있으므로 충분한 용량과 접근 제한이 필요하다.

```sh
python3 tools/ki2buildops.py doctor --root STATE_ROOT
python3 tools/ki2buildops.py backup \
  --component catalog=CATALOG_DIR --component jobs=JOBS_DIR \
  --component release=RELEASE_STORE --component auth=AUTH_STATE \
  --component config=PRIVATE_CONFIG_COPY --component source=PINNED_SOURCE \
  --output BACKUP_VOLUME/kiki-build.tar.gz
python3 tools/ki2buildops.py restore \
  --archive BACKUP_VOLUME/kiki-build.tar.gz --destination NEW_EMPTY_STATE
```

백업은 SHA 명세, SQLite 온라인 백업, 변경 감지, 여유 공간 검사를 사용한다. 빌드 임시 작업 트리와 일부 캐시는 제외한다. 복원은 새 경로에만 수행하며 경로 이탈·특수 파일·SHA 불일치를 거부한다. 계정과 서명 키는 유지하고 복원된 로그인 세션은 종료한다. 원본 서버의 전체 데이터 백업을 이번 시험에서 수행했다고 주장하지 않는다. 새 경로로 실제 인증 DB·Ed25519 키를 복원해 로그인·키 일치·세션 종료를 시험했다.

## 필수 검증 기록

검사 결과와 실제 ISO·VM 식별자는 같은 디렉터리의 후속 검증 기록에서 관리한다. 안정 채널 승격은 자동으로 하지 않는다. 분산 작업자, 전체 OS의 원자적 롤백, Secure Boot 서명과 물리 하드웨어 인증은 이번 지원 계약에 포함하지 않는다. Hyper-V는 새 UEFI VM의 실제 ISO 설치·두 차례 부팅·KVP 호스트 조회·VSS ProductionOnly 체크포인트를 검사했다. 게스트 파일 복사는 기본 비활성으로 유지하며 지원 범위에서 제외한다. QEMU 에이전트의 RPC는 상태 조회와 종료로 제한하며, 파일시스템 quiesce 백업은 이번 범위에 포함하지 않는다.

프로필 검사는 선택한 의존성 범위를 검사한다. 프로필 없는 `ki2build validate`는 일반·native 명세 264개를 함께 검사한다. `ki2sources.py`는 릴리즈 231개 패키지 각각의 원본 소스, 실제 레시피 digest, 패키지 SHA와 의존성 커버리지를 검사한다. 원본 압축파일까지 확인하려면 `--objects`로 보관 객체 디렉터리를 지정한다. `/source-manifest`와 `/api/source-manifest`에서 같은 명세를 조회한다.

별도 SDK에서 조립한 50개 native·분리 패키지는 `recorded-native`로 표시한다. 빌드 중간의 `/tmp/.../dest`를 원본 소스로 취급하거나 일반 copy 빌드로 성공시키지 않는다. 원본 레시피는 `distro/manifests/kiki-build-1.0.0/recipes`에 보존하고 실제 빌드 순서는 `tools/gnome_native/README.ko.md`와 해당 파이프라인을 따른다. 빈 Linux 배포판에서 전체 GNOME을 한 번에 재빌드하거나 모든 보존 SDK를 자동 재생성한다는 지원 계약은 아니다. 기초 world 프로필은 실행 패키지 81개이며 CI의 크기 한도는 96개다.

원본 URL 소스 참조 215개는 서로 다른 보관 파일 205개의 SHA를 실제 대조했다. 자체 소스·설정 14개는 저장소 경로와 보존 아카이브에 연결한다. 폰트와 설치기의 보존 그래픽 런타임 2개는 bootstrap 범위와 출처 한계를 명세에 표시한다. 전체 최상위 패키지 명세의 완전성이 모든 묶음 라이브러리를 독립적으로 소스 재빌드했다는 의미는 아니다.

OpenStack의 게스트 에이전트 채널 설정은 [Nova 공식 설명](https://docs.openstack.org/nova/yoga/admin/libvirt-misc.html)을 참고한다.
