# ISO 자동 배포와 OpenStack 무인 설치

KIKI ISO 작업이 성공하면 별도 outbox가 Terminal Lab의 서명된 기계 API로 작업을 전달한다. 운영 앱은 ISO를 검증하고 전용 프로젝트에서 설치 VM과 빈 Cinder 볼륨을 생성한다. 설치 성공 후 설치 볼륨의 스냅샷에서 디스크 전용 VM을 만들고 첫 부팅 및 재부팅 검사를 수행한다.

## 운영 구성

- API: `POST /api/kiki-builds`, `GET /api/kiki-builds/:jobId`
- 인증: Ed25519, 원문 본문 SHA-256, 메서드·경로·시각·nonce 서명. 두 복제본이 공유하는 nonce 저장소에서 재사용 차단.
- 빌드 클라이언트: `KIKI-Build-Deploy/1.0`. Cloudflare 차단 후 운영자의 명시적 허용으로 적용했다.
- ISO 배포: 256MiB 이하의 읽기 전용 조각을 HTTP로 전달하고 조각별·전체 SHA를 검증한다. 외부 임의 URL은 받지 않는다.
- 프로젝트: `custom-lab-user-7`, 소유자 7. 네트워크·Flavor·볼륨 크기는 서버 설정으로 고정한다. 활성 작업은 하나로 제한한다.
- 설치 VM: UEFI, q35, VirtIO 그래픽, VirtIO SCSI, ISO CD-ROM과 32GiB 대상 볼륨.
- 실행 VM: 설치 디스크의 스냅샷과 복제 볼륨으로 부팅한다. 원본 설치 볼륨과 실패 증거는 보존한다.
- 안정 채널 승격은 수행하지 않는다.

## 설치 허가와 완료 판정

앱이 서명한 config drive를 ISO의 고정 공개키로 검증한다. 작업·ISO·카탈로그·볼륨 UUID·크기·만료 시각과 계정을 검사한다. SCSI VPD 또는 VirtIO serial이 대상 볼륨과 일치하고, 파티션과 파일시스템 서명이 없는 경우만 포맷한다. 설치 seed가 없으면 일반 대화형 설치를 유지한다. seed가 있지만 서명이 잘못되면 설치를 중단한다.

공통 GUI/CLI 설치 백엔드를 사용하며, 설치된 전체 패키지 집합과 카탈로그 SHA를 재확인한다. 설치 완료 보고에는 작업·ISO·볼륨·카탈로그와 생성된 SSH 호스트 공개키를 결합해 HMAC을 붙인다. 앱은 인증된 Nova 콘솔에서 보고를 읽고 정상 종료까지 확인한다. SSH 검증에는 이 호스트키를 사용한다.

두 차례 디스크 부팅 검사는 실제 DMI VM UUID와 서로 다른 boot ID를 요구한다. 전체 패키지 해시, 주요 파일, 그룹·프로필, 기본 저장소 서명 검증, GNOME 서비스와 기본 앱, nmcli/readline, DHCP/DNS/HTTPS, SSH, 시간 동기화 및 기존 OpenSCAP 9개 규칙을 검사한다. 방화벽은 열린 시험 리스너까지 보낸 TCP 패킷이 실제로 차단되고 전용 카운터가 증가하는지도 검사한다.

웹 로그인 조작과 실제 사용자 GNOME 로그인은 자동화하지 않는다. 서비스 검사·로그인 화면 확인·사용자 GUI 로그인 결과를 구분한다.

## 실제 실행에서 수정한 문제

- 기존 i440fx의 UEFI 거부: q35를 ISO 이미지와 디스크 실행 VM에 모두 명시.
- Nova BUILD 중 콘솔 HTTP 409: 준비 대기로 처리.
- Linux SCSI serial 노출 방식: VPD page 0x80 지원.
- seed가 없는 일반 부팅: 종료 코드 정규화와 충돌하지 않도록 명시적 seed 표식 사용.
- initramfs의 `blkid` 누락: 서명된 util-linux 패키지에서 실행 파일을 포함. 기존 init와 라이브러리 ABI 보존.
- SSH 호스트 키 생성 실패: 같은 패키지를 사용한 격리 재현에서 `/dev/null` 누락을 확인. 생성 동안만 `/dev`를 대상 루트에 bind mount하고 실패해도 반드시 해제.
- 카탈로그 직렬화 차이: UTF-8/LF와 키 순서를 고정하고 ki2ctl 36을 새 불변 패키지로 발행.
- ISO 부팅 카탈로그 재생성의 GPT 중첩: `grub-mkrescue`로 BIOS/UEFI 구조를 재생성하고 내장 initrd와 저장소 해시 재확인.
- 앱 교체 중 이전 Node 리스너 잔존: 정확한 컨테이너·PID·시작 시각·프로그램 해시를 확인해 해당 프로세스만 정리. 새 리스너 PID와 새 컨테이너 PID가 일치해야 배포 성공으로 판정.

## 산출물과 결과 위치

- ISO 작업: `aab943e03c014d5abf888fca9a80b697`
- ISO: `kiki-openstack-unattended-20261030-r3-gnome50-x86_64-aab943e0.iso`
- ISO SHA-256: `86f91427bb94364042b2572c4b440de8c53f02c0b5b98bf814bece74bbd5d32b`
- ISO 크기: 1,250,209,792 bytes
- 패키지 스냅샷: `update-openstack-unattended-20261030-r3`
- 운영 앱 이미지: `registry.vlab.dustbox.kr/prod-terminal-lab/terminal-lab-app@sha256:b52f079e8d6bc3cf7b674e84705d843751502a12dffcd911f073065972c6f423` (R7)
- [KIKI 작업 화면](https://cloud-7-3b778824-09936d.lab.terminal-lab.kr/iso-build/jobs/aab943e03c014d5abf888fca9a80b697)

KIKI 화면은 ISO 빌드 성공과 클라우드 설치·검증 상태를 별도로 표시한다. 성공한 검증 보고서는 같은 작업의 `cloud-report` 경로에 연결한다. 실패 시 `needs-review`로 중단하고 자원을 보존한다. 비공개 state·config·환경 파일에는 자격증명이 있으므로 공개하거나 다운로드하지 않는다.

## 회귀 검사

- 운영과 같은 R6 Node 런타임: 15개 통과. 두 HTTP 복제본의 nonce 공유, 불변 작업 ID, 서명 본문·경로 결합, ISO 스트리밍·SHA, 실패 자원 보존, 디스크 전환 중복 방지를 포함한다.
- Linux 설치 seed/호스트 키 검사: 7개 통과. 기존 볼륨·잘못된 seed 거부, SCSI VPD, seed 없는 일반 부팅, 키 생성 실패 시 장치 bind 해제를 포함한다.
- Linux initramfs 검사: 4개 통과. GNU cpio 추출, 연결된 아카이브, C init 보존, 도우미 교체, 잘못된 경로·잘린 데이터 거부를 포함한다.
- outbox 결과 검증: 5개 통과. 잘못된 작업·ISO·VM, 같은 boot ID, 불완전한 패키지·파일 검사와 OpenSCAP 미통과 보고를 성공으로 수용하지 않는다. 기존 스캐너와 세 파일 통합 해시가 일치하는지 독립 확인한다.

## 검증기 R7과 배포 인계

첫 검사에서 GDM의 `activating` 상태를 너무 일찍 읽었고, 세 XML의 통합 정책 해시를 XCCDF 단일 파일 해시와 비교했다. 설치 파일은 서명 패키지의 해시와 모두 일치했고 OpenSCAP 9개 규칙도 통과했다. R7은 서비스 준비를 최대 90초 기다리고, XCCDF·OVAL·CPE의 파일명과 원문을 기존 스캐너와 같은 방식으로 해시한다. outbox는 별도로 고정된 서명 패키지에서 같은 통합 해시를 재계산한다. 초기 v1의 단일 XCCDF 앵커는 원본 manifest를 변경하지 않고 세 파일의 해시 검증과 통합 해시 검증을 모두 요구한다.

R6의 실패 보고를 보존하고 `validationAttempts`에 이유와 보고서 SHA를 남겼다. 수정 검증은 실제 ISO 설치에서 나온 같은 디스크를 사용하며, ISO·패키지·카탈로그·설치 계획·기계 API manifest를 바꾸지 않았다.

최종 Terminal Lab 소스는 로컬 `E:/dev/terminal-lab.kr/.codex/worktrees/modern-preview-v2`와 운영 호스트 `/home/tang/terminal-lab-web`에 반영했다. 통합 배포 시 다음 파일과 연결점을 보존해야 한다.

- `server/kiki-iso-automation.js`
- `server/kiki-cloud-openstack.js`
- `server/iso-vm.js`, `server/iso-upload.js`
- `server/assets/kiki-cloud-guest-check.py`
- `tests/kiki-iso-automation.test.mjs`
- `server/heat.js`: `getKikiCloudContext`, `kikiOpenstackFetch` export 별칭
- `server/index.js`: primary/공유 quota lock을 사용한 factory 생성, 기본 JSON parser 앞의 `/api/kiki-builds` mount

로컬에서 빌드·검사한 원본 묶음은 `E:/dev/KIKI-OS/artifacts/cloud-automation-20261030/production`에 있다. 운영 소스·이미지·환경 설정 변경은 R7 교체와 digest 고정까지 완료했다. 이후 별도 v2 UI 배포와 충돌하지 않도록 앱/웹 교체·재시작·환경 파일 변경 및 v2 공통 소스 수정을 중단했다. 웹·프록시·DB 이미지는 이 작업에서 교체하지 않았다.

통합 담당에게 추가 전달할 회귀 검사 파일은 `E:/dev/KIKI-OS/artifacts/cloud-automation-20261030/production/tests/iso-vm.test.mjs`다. v2 작업 디렉터리의 `tests/iso-vm.test.mjs`에는 아직 복사하지 않았다. 기능 모듈과 나머지 검사 파일은 위 위치에 반영돼 있다.

## 실제 OpenStack 최종 결과

2026-10-30 19:41 KST에 두 번째 부팅 검사까지 통과했다. 빌드 서버 outbox도 서명 패키지에서 계산한 정책 통합 해시로 결과를 독립 확인하고 `passed`를 저장했다.

| 항목 | 결과 |
| --- | --- |
| 실행 VM | `kiki-iso-aab943e03c01-installed` |
| 실행 VM UUID | `6f5263b2-0b66-4a51-bcea-6daa5e4ec2fb` |
| 내부 IP | `10.250.254.121` |
| 설치 VM UUID | `68c34fdc-2abc-4649-8a16-c088fff5b2d0` |
| 설치 대상 볼륨 | `02d2d68e-b7d1-4c30-a5ad-a4339c3dbbc0` |
| 설치 디스크 스냅샷 | `4880661d-e0fb-4917-b48c-697b555e840c` |
| 실행 복제 볼륨 | `85a162b5-634a-414b-aa7f-6748f8929248` |
| 첫 boot ID | `9e008250-0ea3-46ab-86ae-4a11340d6cd5` |
| 재부팅 boot ID | `42954541-db59-4ffa-9bde-57bfdc1d7c0d` |
| 검사 | 각 부팅에서 34/34 통과 |
| 설치 패키지 | 218개, 전체 집합·SHA 일치 |
| 주요 파일 | 35개, SHA 일치 |
| OpenSCAP | 각 부팅에서 9/9 pass, fail/error 0 |
| 정책 통합 SHA | `d5a06f768b2fdd897e3354a7e6cb4d980559f0c4fcf33b45bffa8c075df33d8a` |
| 방화벽 | 두 부팅 모두 시험 패킷 3개 관측 후 차단, 새 SSH 연결 정상, 다른 테이블 보존 |
| GUI | 실제 GDM 로그인 화면 확인, 사용자 로그인 조작 미실시 |
| KIKI 결과 | `fresh_install_tested=true`, `fresh_install_status=passed` |
| 서버 저장 보고서 SHA | `2d0db948593ec79047c6d6615c699df940a35d7277f5992580c36c023ba6b2cb` |

[최종 VM 보고서](https://cloud-7-3b778824-09936d.lab.terminal-lab.kr/iso-build/jobs/aab943e03c014d5abf888fca9a80b697/cloud-report)

비밀값을 포함하지 않는 API 보고서 사본은 `artifacts/cloud-automation-20261030/openstack-final-public-report.json`, 로그인 화면은 `artifacts/cloud-automation-20261030/openstack-disk-gdm.png`에 보관했다. 안정 채널은 `update-55f351d06ff14a20a8746e49f5e2e7de`를 유지했다.
