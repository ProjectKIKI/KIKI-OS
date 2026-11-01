# KIKI Build 1.0.0 정식 릴리즈 검증

검증일: 2026-11-01(한국시간). 정식 태그는 `build-v1.0.0`이며 x86_64 단일 Linux 빌더를 지원한다. KIKI OS 전체의 범용 하드웨어 GA 선언이나 안정 업데이트 채널 승격과 구분한다.

## 필수 통과 항목

| 항목 | 결과 |
|---|---|
| 일반·native 카탈로그 전체 의존성 | 264개 레시피 통과 |
| 릴리즈 소스 명세 | 최상위 231/231 패키지, 실제 레시피 digest 231/231 일치 |
| 업스트림 압축파일 바이트 | URL 참조 215개, 서로 다른 보관 객체 205개 SHA-256 검증 |
| Linux 회귀 검사 | 496개 실행, 492개 통과, 환경 조건 4개 건너뜀 |
| 후속 소스 페이지 HTTP 회귀 | JSON·HTML 응답, 명세 훼손·누락·경로 이탈·잘못된 URL 거부 |
| 웹 브라우저 | 인증 프록시 포함, 1440×1000·390×844, 전체 목록·JSON·native 안내·링크·콘솔 오류·페이지 폭 검사 |
| 이전 OpenStack 실제 설치 | 220개 패키지·중요 파일·2회 부팅·OpenSCAP 9/9, 별도 QGA 실제 virtio RPC 통과 |
| 운영 반영 후 smoke | 20단계 통과, 작업 `20261101-052818-3056` |
| 새 Hyper-V 실제 설치 | 원본 ISO에서 빈 32GB 디스크에 GNOME·보안·vm-hyperv 220개 설치, 2회 부팅 각각 18개 검사 통과 |
| Hyper-V 호스트 연동 | KVP 실제 OS·IP 조회, ProductionOnly 체크포인트 2회, 게스트 FREEZE·THAW 성공 |

전체 Linux 회귀 검사 뒤 추가한 HTTP 테스트와 정식 버전 표시는 별도 후속 검사로 확인한다. 환경 의존 건너뜀을 성공한 실기 검사로 간주하지 않는다.

## Hyper-V 시험 환경

- VM: `kiki-build-v1-ga-hyperv-20261101`
- UUID: `b3089726-4b58-4c91-bdf8-4f8633984585`
- 새 독립 디스크: `artifacts/build-v1-ga-hyperv/fresh-install.vhdx`, 32GB 동적 VHDX
- Generation 2, UEFI, 4GiB 고정 메모리, vCPU 2개. 기존 VM이나 디스크는 변경하지 않았다.
- ISO: `kiki-build-v1-rc1-vm-20261031-gnome50-x86_64-01e17ae1.iso`
- ISO SHA-256: `a2a44d3f9c508ffda5a3a53ae29208a33b5878ce6227365a9e98634532e46067`
- 부팅 ID: `2dedbe58-63fd-4220-9bc1-b768f1fdc6b4`, `b43e9d4d-22ae-41e9-bbb8-d554d775e400`

두 부팅에서 설치 집합 220개와 각 패키지 SHA, Hyper-V 감지와 장치, KVP·VSS·GDM·NetworkManager·sshd·방화벽 서비스, root 잠금, 그래픽 기본 대상, nmcli/readline·HTTPS·OpenSCAP를 확인했다. GDM 한국어 로그인 화면을 캡처했다. 인증된 GNOME 데스크톱 사용자 세션 조작은 이번 자동 검증에 포함하지 않는다. SSH 호스트 키는 설치된 시스템의 `ssh-keygen -A`로 생성했으며, 기본 sshd 유닛도 최초 부팅 시 같은 명령을 실행한다. 공용 이미지에 호스트 개인키를 포함하지 않는다.

`CheckpointType=ProductionOnly`로 설정해 Standard 체크포인트 대체를 허용하지 않았다. `v1-ga-production-vss-20261101`, `v1-ga-production-vss-reboot-20261101`를 생성했고, 게스트 journal에서 두 번 모두 `FREEZE: succeeded`, `THAW: succeeded`를 확인했다. Get-VMSnapshot의 SnapshotType=Standard는 사용자 체크포인트의 API 분류이며, 이 값으로 Production 여부를 판정하지 않는다. 호스트 정책과 실제 게스트 동결 로그를 함께 증거로 사용한다.

KVP가 전달한 값은 `OSName=KIKI OS`, `OSVersion=6.1.187`, `IntegrationServicesVersion=3.1`, 호스트명 `kiki-v1-hyperv`와 해당 VM IPv4다. Windows는 KVP·VSS에 구형 프로토콜 보조 경고를 표시하지만 PrimaryStatus는 정상이고 실제 조회·freeze/thaw가 통과했다. 경고가 전혀 없다고 주장하지 않는다. 파일 복사 서비스는 기본 비활성이며 검증/지원 대상에 포함하지 않는다.

## 전체 소스 명세의 범위

`distro/manifests/kiki-build-1.0.0/sources.json`이 릴리즈 패키지 집합, 원본 주소·SHA, 의존성, 원래 레시피 digest와 저장소에 보존한 레시피 파일의 SHA를 묶는다. 일반 카탈로그 누락 114개를 실제 기록에서 가져왔다. 임의로 upstream 주소나 역사적 Git 커밋을 추정하지 않았다.

215개 URL 소스 참조는 실제 보관 객체 205개의 해시를 검사했다. 자체 소스·설정 14개는 저장소 경로·해당 보존 소스에 연결하며, 보존 아카이브 7개도 실제 객체 SHA와 대조했다. 폰트와 인스톨러 그래픽 런타임은 bootstrap 2개로 구분하고 포함 라이브러리 개별 소스 재빌드의 한계를 명시한다. 별도 SDK에서 분리·조립하는 50개 패키지를 일반 copy 컴파일로 성공시키지 않는다. 이는 231개 최상위 패키지 명세의 통합이며 모든 묶음 라이브러리 또는 빈 호스트에서의 전체 GNOME 무인 재빌드 인증은 아니다.

## 보존과 공개 범위

사용자가 보존을 선택한 OpenStack 시험 VM `kiki-v1-qga-isolated-20261031`과 32GB 복제 볼륨은 전원 종료 상태로 유지한다. 기존 설치 VM·원본 스냅샷과 기존 로컬 VM은 그대로 보존한다. 새 Hyper-V 시험 VM과 체크포인트도 증거를 남기고 보존한다.

GitHub와 Gitea는 비공개 저장소에서만 정식 릴리즈를 게시한다. Gitea 저장소가 공개 상태였으므로 사용자 요청에 맞춰 비공개로 전환했다. 릴리즈 파일에는 테스트 계정 비밀번호·개인키·서버 인증 DB·원시 콘솔 로그를 포함하지 않는다. 안정 업데이트 채널 `update-55f351d06ff14a20a8746e49f5e2e7de`는 변경하지 않는다.

실제 게시 커밋과 릴리즈 URL, 서버 반영 결과는 릴리즈 설명과 비공개 검증 묶음에서 확인한다.
