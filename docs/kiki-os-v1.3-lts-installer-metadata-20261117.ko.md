# KIKI OS v1.3 LTS 설치기 추적 메타데이터 보완 — 2026-11-17

## 범위와 보존 방침

작업 후보: `artifacts/kiki-v1.3-lts/20261117-stage3-metadata/source`.
기존 Stage 1 후보를 복제하여 보완했다. 루트 제품 소스, 기존 설치기·원본 패키지와 GNOME 환경을 덮어쓰지 않는다. incident-ai 자동 연동은 보류한다. 왼쪽 화면을 제어하지 않고 SSH 및 대상 VM을 지정하는 Hyper-V API만 사용한다.

사용자가 승인한 ISO 보존 기준은 **최신 검증 후보 + 직전 정상 복구용**이다. 공개 릴리즈·버전 보관함·백업·다른 프로젝트와 VM 연결 이미지는 제외한다. 새 후보 실제 설치 검증이 통과한 뒤 구형 이미지의 SHA와 VM DVD 참조를 다시 확인하여 파일 단위로 제거한다. 과거 보존 목록은 수정하지 않고 이번 승인에 따른 예외 기록을 별도로 남긴다.

## 수정 내용

| 대상 | 변경 |
|---|---|
| ISO 소스 식별 | 짧은 커밋과 부모 Git 저장소 추정을 제거하고 40자리 기준 커밋, 후보 상태, 소스 아카이브·파일 트리 SHA를 기록 |
| 빌드 입력 | 소스 1,279개 파일의 SHA, 아카이브, 저장소 인덱스·서명 메타데이터, GTK 설치기·TUI·커널·카탈로그·루트 파일시스템·빌드 이미지·드라이버를 입력 잠금 파일로 기록 |
| 실제 미디어 결합 | ISO `/kiki/build-inputs.json`과 initramfs `/etc/kiki/installer-origin.json`을 만들고 실제 저장소 채널·인덱스 SHA와 결합 |
| Go 미리보기 계획 | 고정 채널명 `stage2-v2`를 제거하고 실제 미디어의 채널과 소스 입력 SHA 사용. `frontend=gtk/tui/cli/unattended`, `planner=kiki-installer-tui`, `executor=pending` 기록 |
| C 실행·저장 계획 | 서명·패키지 검증 후 추적 값을 로드. `generated_by=kiki-stage1`, 실제 frontend, planner와 `executor=kiki-stage1` 및 동일한 채널·입력 SHA 저장 |
| 부팅 준비 순서 | GUI·TUI 계획 생성 전에 로컬 ISO를 읽기 전용 마운트. 미디어를 준비할 수 없으면 다음 폴백으로 이동 |
| 오류 처리 | 잘못된 아카이브·누락 파일·SHA 불일치·중복/초과 길이/누락 추적 값을 거부. 잘못된 문맥으로 기존 미리보기 계획을 먼저 잘라내지 않도록 수정 |
| 후보 패키지 | 변경된 Go 계획 생성 도구만 `kiki-installer-tui-0.1.0-27`로 후보 재패키징. 기존 C/GTK4 설치기 29와 커널 6.1.187-4는 SHA 고정 |

기준 커밋은 `b97b2ca0dcdaf4aee8a18411e4a16421dba1974e`다. 이번 소스는 아직 커밋하지 않은 별도 후보이므로 `source_state=modified-candidate`, `commit_role=base-with-input-lock`으로 기록한다. 이 커밋만으로 이번 ISO가 재현된다고 표시하지 않는다. 소스 아카이브·트리·입력 잠금 SHA를 함께 대조해야 한다.

후보 변경 내역: `artifacts/kiki-v1.3-lts/20261117-stage3-metadata/metadata-changes.patch`와 `metadata-changes.json`. 원래 Stage 1 후보 대비 9개 파일이다.

## 검증과 산출물

최종 판정: **이번 추적 메타데이터 보완과 보존 기준 정리 범위 통과**. v1.3 LTS 전체 GA 판정은 아니다.

| 검증 | 결과 |
|---|---|
| Linux 검사 | 50개 통과, skip 0. 생성된 C의 GCC 구문·실제 직렬화·잘못된 출처 필드 거부 포함 |
| Go 설치기 검사 | 전체 패키지 검사 통과. 최종 후보와 동일한 Go 소스 트리임을 빌드 시 대조 |
| 실제 ISO 미리보기 | 실제 ISO의 메타데이터·인덱스·입력 잠금 파일과 TUI 27 바이너리로 GTK 계획 생성 통과. 입력 변조 거부·기존 계획 보존 확인 |
| 입력 추적 | 실제 후보 1,279개 파일·소스 아카이브·트리·입력 잠금 SHA가 ISO manifest 및 실제 initramfs와 일치 |
| Hyper-V 실제 설치 | 새 전용 32GiB 디스크, NIC 분리 상태에서 GNOME + vm-hyperv 216개 설치 완료 |
| 재부팅·로그인 | ISO 분리 후 설치 디스크 부팅, GDM 암호 로그인, 활성 Wayland 세션. 자동 로그인 없음·root 잠금 |
| 저장된 InstallPlan | 실제 채널·인덱스 SHA와 소스 커밋·상태·아카이브·트리·입력 SHA 전부 일치. frontend=gtk, planner=kiki-installer-tui, executor/generated_by=kiki-stage1 |
| 패키지·앱 | 미디어 236개 패키지 SHA·저장소 서명 검증. 설치 DB 216개의 패키지 집합·SHA 일치. 주요 GNOME 실행 파일·라이브러리 7개의 실제 SHA 일치 |
| 기본 GNOME 앱 | Console·파일 앱의 실제 실행 파일 경로와 프로세스의 kiki 사용자 ID 확인 |
| 서비스 | GDM·SSH·NetworkManager·D-Bus·logind·Hyper-V KVP/VSS 활성, 실패 서비스 없음. VSS 백업 호환성을 인증한 것은 아님 |
| 원본 보존 | 승인한 구형 ISO 제외 원본 5,529개 SHA 일치, 제품 소스 16개 SHA 일치. 기존 GNOME VM 5개와 직전 검증 VM의 ID·디스크·상태 보존 |
| 빌드 서버 보존 | 기존 보호 목록 15,208개 경로의 크기·mtime 대조. 승인 ISO 삭제 외 변경 없음. 원본 설치기와 보존 ISO SHA 재검증. 서비스 4개 및 공개 로그인 응답 정상 |

최종 ISO: `artifacts/kiki-v1.3-lts/20261117-stage3-metadata/kiki-v13-metadata-r4-20261117.iso`.
VM: `kiki-v13-metadata-r4-20261117`, ID `b501fa7e-5c5f-4a9f-b41a-08a5601a9ae4`.

| 항목 | SHA-256 |
|---|---|
| 최종 ISO | `a409c261d44b7ec6e070b1bbbfbe8c645f15d4d4352ba5b6ec8a95d750ca740b` |
| 최종 입력 잠금 | `5c3538f0c88b4e10f9670af9bb586392bffac3ad5b6faa3e93789595a72b46fa` |
| 후보 소스 아카이브 | `d97afc14afc44c082aeb4de69a5a7a31378263e1541f6feee9d9a9c9b26f21ad` |
| 후보 소스 트리 | `8688b3cd20ed313aec8154a362c30844ac72914296b3224b96595e2ddef36f59` |

## ISO 정리 결과

| 위치 | 제거 수 | 제거한 파일의 논리 용량 | 정리 직후 사용 가능 공간 |
|---|---:|---:|---:|
| 로컬 E: KIKI 작업 경로 | 8개 | 16.02GiB | 31.43GiB |
| 빌드 서버 비공개 작업 경로 | 8개 | 8.89GiB | 93.03GiB |

논리 용량은 제거한 파일 크기의 합이다. 서버의 하드링크·공유 블록·백업 때문에 실제 확보 공간과 다를 수 있으며, 정리 전후 free 값도 기록했다. 서버 공개 릴리즈·버전 보관함·백업과 다른 프로젝트·VM 연결 ISO는 제거하지 않았다.

로컬 KIKI 경로에는 최종 r4 후보와 직전 `kiki-v13-installer-r29-20261116.iso`만 남았다. 직전 복구 ISO SHA는 `1707c31eb18815f587dc52650346e4b9bbc8a448def09f9229f6ff94403f3b45`로 유지된다. 기존 보존 목록에 있던 구형 ISO 5개는 이번 사용자 승인에 따른 예외다. 부팅 시험 이미지 2개와 미디어 준비 순서 문제로 제외한 중간 r3 ISO도 제거했다. 원본 패키지는 제거하지 않았다.

## 재개할 때 사용할 파일

모든 경로는 `artifacts/kiki-v1.3-lts/20261117-stage3-metadata/` 아래다.

- `source/`: 실제 검증 후보 소스. 제품 루트에 반영·커밋·푸시하지 않았다.
- `final-inputs/build-inputs.json`, `final-inputs/source.tar`, `final-inputs/iso-driver.py`: 서로 SHA가 맞는 최종 입력·아카이브·빌드 드라이버. 이전 시도의 입력 파일 대신 이 묶음을 사용한다.
- `metadata-changes.patch`, `metadata-changes.json`: Stage 1 후보 대비 변경과 파일 SHA.
- `iso-result.json`, `iso-manifest.json`, `initramfs-origin.json`, `final-input-verification.json`: 실제 ISO 추적 증거.
- `guest-first-boot.json`, `guest-final.json`, `critical-files-result.json`: 실제 설치·로그인·출처·앱 검증. 검증기 진단용 파일과 최종 통과 기록을 구분한다.
- `retired-isos-local.json`, `retired-isos-server.json`: 제거 파일의 경로·SHA·용량·보존 예외 기록.
- `preservation-current-files.json`: 이번 승인 ISO 삭제를 반영한 현재 로컬 보존 기준선. 과거 기준선 파일은 그대로 남긴다.
- `preservation-local.json`, `preservation-server.json`, `preserved-vms-after.json`, `validation-summary.json`, `SHA256SUMS.txt`.
- `r4-install-review.png`, `r4-install-state.png`, `r4-gdm-login-result.png`, `r4-wayland-apps.png`.

빌드 서버 후보: `/build-kikios/kiki-build/candidates/installer-v13-metadata-20261117-r4`.


r3 실제 부팅 시험에서는 ISO가 아직 마운트되지 않은 시점에 Go 계획 생성기가 출처 파일을 읽어 계획 생성이 거부됐다. 디스크 쓰기는 시작되지 않았다. 이를 찾아 GUI·TUI 진입 전에 읽기 전용 미디어 준비를 추가했고, 보완 소스로 다시 Linux 검사 50개를 통과했다. r3는 실패 증거만 보관하고 최종 보존 ISO에서 제외한다.

최종 ISO 빌드 시도는 r4, 서명된 저장소 채널은 `v13-metadata-20261117-r3`이다. ISO manifest·initramfs 출처 정보·Go 미리보기·설치 후 C 실행 계획에서 이 실제 채널과 입력 SHA가 일치함을 확인했다.

## 후속 범위

이번 작업은 설치기 출처 추적과 ISO 보존 기준 정리다. v1.3 LTS 전체 릴리즈 완료를 뜻하지 않는다. 커널 6.12 LTS 평가, 전체 패키지의 x86-64-v2 최소 사양 인증, 업데이트·롤백·복구와 24개월 지원 범위 확정은 최종 계획서의 별도 단계로 남는다. incident-ai 자동 연동 및 운영 서버 배포·Git 커밋/푸시는 이번 작업에 포함하지 않는다.
