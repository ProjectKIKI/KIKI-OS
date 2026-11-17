# KIKI OS Gitea stage3 설치기·ISO 빌드 및 Hyper-V 검증 — 2026-11-17

## 결과

요청한 **Git 커밋·입력 SHA 대조, 새 설치기 패키지·후보 ISO 생성, Hyper-V 오프라인 설치·재부팅·GDM/Wayland 로그인**을 완료했다. 기존 설치기·원본 패키지·보존 ISO·GNOME VM을 유지했다. 이번 작업에서 기존 ISO를 삭제하지 않았다. incident-ai 자동 연동은 계속 보류한다.

소스 커밋: `2839388582aaa54002e843dc485d80bd94271958`. Gitea stage3 원격과 로컬 HEAD가 같은 커밋임을 확인했다. ISO에는 `source_state=clean`, `commit_role=source-commit`으로 기록했다. 로컬 Git 객체와 서버 Git 아카이브의 소스 1,284개가 실제 빌드 입력 파일 SHA와 일치한다. Windows Git 아카이브의 줄바꿈 변환 영향을 피하기 위해 로컬 검사는 `git cat-file --batch`의 원본 객체 바이트로 대조했다.

## 빌드와 검증 범위

| 항목 | 결과 |
|---|---|
| C/GTK4 설치기 | Git 소스로 새 컴파일, x86-64-v2 옵션, 원본 28번 패키지의 라이브러리·라이선스 묶음 재사용 후 후보 29번 패키지 조립 |
| 런타임 출처 | C 바이너리·스타일·카탈로그·입력 SHA와 UI 버전 명세를 Git 입력에 맞춤. 원본 카탈로그와 Git 카탈로그는 JSON 내용이 같고 줄바꿈에 따른 SHA 차이를 확인 |
| Go 계획 생성기 | Git 소스로 정적 빌드, GOAMD64=v2, 후보 27번 패키지 생성, Go 검사 통과 |
| 기본 계약 검사 | 9개 통과 |
| 출처·미디어·설치 백엔드 Linux 검사 | 50개 통과, skip 0 |
| 서버 GTK/Xvfb 검사 | 3개 중 2개가 화면을 열지 못해 실패. 성공으로 처리하지 않았고 원인 확정·수정은 후속 항목 |
| ISO | 236개 패키지 SHA 및 저장소 Ed25519 서명 검증, 실제 initramfs 출처·BIOS/UEFI 부팅 카탈로그 확인 |
| Hyper-V 실제 GUI | 새 VM의 기본 한국어 GTK 부팅, 디스크·계정·GNOME·Hyper-V 구성 선택 및 설치 완료 화면 확인 |
| 오프라인 설치 | 후보 NIC를 분리한 상태에서 전용 새 32GiB 디스크에 216개 패키지 설치 완료 |
| 재부팅 | ISO를 분리하고 설치 디스크로 부팅 |
| GDM/Wayland | kiki 암호 로그인, gdm-password 서비스의 활성 Wayland 세션 확인. 자동 로그인 없음·root 잠금 |
| 설치 후 출처 | 저장된 InstallPlan의 커밋·clean 상태·아카이브·트리·입력·인덱스 SHA와 채널이 실제 ISO와 일치. frontend=gtk, planner=kiki-installer-tui, executor=kiki-stage1 |
| GNOME 앱 | Console·파일 앱 실제 실행, GDM·GNOME Shell·GTK·Libadwaita·VTE 등 주요 파일 7개 SHA 유지 |
| 서비스 | GDM·D-Bus·logind·SSH·NetworkManager·Hyper-V 데몬 활성, 실패 서비스 없음 |

실제 Hyper-V GUI 설치·로그인은 통과했다. 서버 Xvfb 실패는 별도 검사 환경 문제로 남겨 두며, 모든 자동 GUI 검사가 통과했다고 표시하지 않는다. 이번 결과는 Secure Boot·물리 서버·전체 x86-64-v2 CPU 인증이나 v1.3 LTS 전체 GA 판정이 아니다. 커널은 보존 기준선인 6.1.187-4를 유지했다.

GTK 설치기는 라이브 미디어 전용으로 갱신했다. 설치 대상 rootfs에 GUI 설치기가 없는 기존 구성을 유지하며, 대상의 Go 계획 생성기만 새 패키지로 갱신했다. 패키지 릴리스 번호 29·27은 후보 저장소에서만 재빌드한 값이며 기존 저장소의 같은 이름 파일을 덮어쓰거나 공개 업데이트 채널로 승격하지 않았다.

## 최종 산출물과 SHA

| 항목 | 값 |
|---|---|
| ISO | `kiki-v13-git-r7-20261117.iso` |
| 크기 | 1,450,387,456 bytes |
| ISO SHA-256 | `80281c24045dbf77da7d37c54e7ef34f0a3ec015c05f7019d3ab7a547349c091` |
| 저장소 채널 | `v13-git-20261117-r7` |
| GTK 설치기 패키지 SHA-256 | `8e6fae4ab4b1ad0fb5c2732780d063b108c13aaf644a68990d5040e25096332b` |
| Go 계획 생성기 패키지 SHA-256 | `9a5906527862f62664cb344c9f39beacb907eb29a2b7ef8d57c8d1be1de166cb` |
| Git 원본 아카이브 SHA-256 | `04f5608c0ac158ebb74f1ce9230a3aff907a825b520c41b59c32566c470aecbd` |
| 실제 소스 아카이브 SHA-256 | `46d40aa2c087718b19b1b4741022992d5c2ea521a8b6a52467d9f01ec2516703` |
| 소스 트리 SHA-256 | `d7c129a8117bbf14938a0679ae66874beafede54a560514700da399e4d4963f1` |
| 입력 잠금 SHA-256 | `2a164b07a396b98752bcf7ff36de5d5d0794552cc2d43b9c799ad29bc3c1e89d` |

Git 원본 아카이브에는 디렉터리 항목이 있다. 현재 출처 검사기가 받는 정규 파일 전용 아카이브로 재포장하면서 파일 내용과 모드는 유지했다. 두 아카이브의 SHA가 다른 이유이며, 모든 파일 SHA를 Git 원본 객체까지 대조했다.

- 로컬 산출물: `E:/dev/KIKI-OS/artifacts/kiki-v1.3-lts/20261117-stage4-git-build/`.
- 서버 후보: `/build-kikios/kiki-build/candidates/installer-v13-git-20261117-r7/`.
- 패키지: 서버 후보의 `packages/kiki-installer-gtk-0.1.0-29.x86_64.ki2`, `packages/kiki-installer-tui-0.1.0-27.x86_64.ki2`.
- VM: `kiki-v13-git-r7-20261117`, ID `7f8d3cd0-df85-4715-ad99-e98a62fc04b5`.
- 설치 호스트명: `kiki-v13-git`. 실제 로그인 사용자: `kiki`.

## 보존 확인

로컬 기준선 5,531개를 대조했다. 5,526개는 과거 SHA 그대로다. 나머지 소스 5개는 직전 작업에서 승인·커밋한 설치기 변경이며 현재 Git 커밋과 정확히 일치한다. 이번 작업의 예기치 않은 변경·누락·삭제는 없다. 보존 ISO r29와 metadata-r4는 SHA를 재확인했고, 새 git-r7 ISO를 추가했다.

기존 GNOME VM 5개, r29 설치 검증 VM과 metadata-r4 후보 VM의 ID·디스크·상태를 보존했다. 서버의 기존 보호 목록 15,208개 경로는 과거 승인한 ISO 삭제 3개 예외를 적용하여 크기·mtime 변동이 없음을 확인했다. 원본 설치기 패키지·보존 ISO·새 ISO는 SHA도 재검증했다. 빌드 서비스 4개와 외부 로그인 화면은 정상이며 재시작하지 않았다.

## 재개·검토용 기록

로컬 산출물 디렉터리의 다음 파일을 사용한다.

- `final-inputs/build-inputs.json`, `final-inputs/source.tar`, `final-inputs/source/`, `final-inputs/iso-driver.py`: 서로 SHA가 맞는 실제 입력·소스·빌드 드라이버.
- `local-git-proof.json`, `git-source-proof.json`, `gtk-package-provenance.json`, `final-input-verification.json`.
- `iso-result.json`, `iso-manifest.json`, `initramfs-origin.json`, `SHA256SUMS.txt`.
- `go-tests.log`, `contracts.log`, `core-tests.json`, `core-tests.log`, `headless-gtk-tests.log`: 실패 로그도 포함.
- `install-start.json`, `install-completed.json`, `guest-first-boot.json`, `critical-files-result.json`.
- `preservation-local.json`, `preservation-server.json`, `preservation-current-files.json`, `preserved-vms-after.json`, `previous-candidate-vm-preserved.json`.
- `install-review.png`, `install-state.png`, `gdm-login-result.png`, `wayland-apps.png`.

중간 실패 후보를 최종 ISO로 사용하지 않았다. 최초 중단은 카탈로그 바이트 SHA 차이였으며, 이후 후보 준비 도구의 라이브 설치기/rootfs 구분과 Git 아카이브 항목 처리를 보완해 r7을 완성했다. 제품 Git 소스는 바꾸지 않았다. 후속 우선 항목은 서버 Xvfb 기반 GTK 검사 복구, 그 다음 후보를 정식 패키지 릴리스·업데이트 경로로 승격하기 위한 별도 검토다.


## 2026-11-17 Xvfb 검사 후속

검사 도구의 X11 준비 확인·진단·시간 제한을 보완했고 GTK 3건을 5회, 실행 도구 4건과 회귀 61건을 통과했다. 최초 실패의 정확한 촉발 조건은 미확정이다. 당시 실패 기록은 유지하며 [후속 검증 기록](kiki-os-v1.3-lts-xvfb-validation-20261117.ko.md)을 함께 읽는다. 기존 패키지·ISO는 교체하지 않았다.
