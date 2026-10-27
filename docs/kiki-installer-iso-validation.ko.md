# 동일 ISO 설치 검증 기록

현재 상태: **미실행**. 단위 테스트, PTY 모의 진행 상태, chroot 도움말 실행은
아래 VM 설치 시험을 대체하지 않는다. Stage 3 Kubernetes 검증과도 별도다.

## 검증 대상 산출물

### TUI11 ISO 생성·재추출 검증 완료

파일명: kiki-stage3-v3-installer-x86_64-20260909-tui11.iso.
원본 산출물은 /tmp/kiki-tui11-iso-99j7horb/output에 있으며,
크기 4,159,023,104바이트, SHA-256은 다음과 같다.

```text
8258e52f9ee8a7515ce316dea078799c2c1a123f5fa8bbe1afbeb2cb7c3bafbe
```

후보 repo에 73개 패키지 인덱스를 생성하고 기존 stage3-v3 Ed25519
키로 서명했다. 외부 공개키 검증을 통과한 뒤 installer 모드,
--no-install-image --no-hyperv-vhdx로 ISO를 생성했다(종료 코드 0).
이전 ISO나 원본 rootfs는 덮어쓰지 않았다.

완성 ISO를 /tmp/kiki-tui11-iso-99j7horb/readback에 재추출했다.
ki2readback으로 서명·인덱스·패키지 73개를 검증하고 initramfs와
rootfs의 선택 파일을 각각 45개 비교했다. 기존 GTK/스키마 44개에
TUI 실행 파일 비교를 추가했다. 두 gzip 스트림의 EOF/CRC 검사도
포함한다. TUI 참조는 /tmp/kiki-tui11-gqHRExHG의 빌드 산출물이다.

```sh
python3 -B tools/ki2readback.py --media-root /tmp/kiki-tui11-iso-99j7horb/readback --public-key build/ki2/keys/stage3-v3-repo.ed25519.pub --graphics-reference build/ki2/host-graphics/rootfs --rootfs-reference /tmp/kiki-tui11-iso-99j7horb/rootfs --tui-reference /tmp/kiki-tui11-gqHRExHG/x86_64/work/kiki-installer-tui/dest/usr/bin/kiki-installer-tui
```

재추출 도구의 TUI 참조 검사를 추가했고 회귀 시험 4개가 통과했다.
전체 rootfs 파일의 원본 비교, GUI 렌더링, 실제 디스크 설치·부팅은
이 검증에 포함되지 않는다. 동일 ISO GUI/TUI/CLI VM 시험과 GNOME
전체 데스크톱 통합은 여전히 미완료다.

### TUI11 후보 입력 조립 완료 — ISO는 아직 미생성

작업 경로: /tmp/kiki-tui11-iso-99j7horb.
ki2candidate.py로 기존 ki2ctl11 후보의 패키지 이름 집합과 현재
server-core 런타임 의존성을 합쳐 현재 레시피 산출물을 복사했다.
snapshot/packages/x86_64에 73개이며 크기·SHA-256 복사 대조를
통과했다. snapshot/snapshot.json에 선택 내역을 저장했다.
이 스냅샷은 서명된 저장소 인덱스나 신뢰 인증을 대체하지 않는다.
도구의 복사 대조·기존 대상 보존·누락 패키지 중단 시험도 통과했다.
첫 준비는 없는 해시 도우미를 호출해 실패했으며 스트리밍 해시를
구현한 뒤 별도 snapshot 경로에서 성공했다. 실패한 candidate
경로는 빈 패키지 디렉터리로 남아 있으며 사용하지 않는다.

새 rootfs: /tmp/kiki-tui11-iso-99j7horb/rootfs.
현재 server-core로 조립해 종료 코드 0이다. TUI release 11,
GTK release 11, GLib 2.84.4-2, gobject-introspection 1.84.0-7이
포함된다. GNOME 전체 데스크톱이나 최근 개발용 graphics-foundation
전체를 설치하는 프로필은 아니다. 기존 /system/ 스키마 경고는 남아 있다.

test_server_rootfs와 test_systemd_enable 결합 8개가 0.871초에
통과했다. 대상 Python/ki2ctl 목록 실행, Info/GSettings 인덱스,
새 TUI 패키지와 rootfs 실행 파일 바이트 일치, 13개 요청 서비스
유닛의 임시 복사본 연결 검사를 포함한다. 실제 서비스 기동은 아니다.

남은 단계: 후보 저장소 인덱스 생성·서명·검증, 새 ISO 생성과
재추출 검사, 동일 ISO 기반 GUI/TUI/CLI VM 설치 시험.
기존 ISO는 변경하지 않았다.

### ki2ctl 11 통합 ISO 후보 준비

후속 생성 및 재추출 검증 완료: ISO 빌드 종료 코드 0.
파일 크기 4,158,976,000바이트, SHA-256
`ce0143f7b51156f9494a761930e4329079f8965a8b1b9ef8ff7f4f23dcc48f59`.
xorriso로 완성 ISO를 후보의 readback 디렉터리에 재추출했다.
ki2readback에서 외부 공개키로 서명 및 73개 패키지 검증,
initramfs와 rootfs의 GTK/스키마 각각 44개 비교가 통과했다.
이는 파일 수준 검사이며 실제 VM 부팅/설치를 의미하지 않는다.

프로젝트 배포 경로:
dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-gtk11-ki2ctl11.iso.
기존 GTK11 ISO는 별도 파일로 보존한다.

후보 작업 디렉터리: /tmp/kiki-iso-info-AIpJhzX7.
기존 GTK11 저장소의 패키지 집합을 기준으로 현재 레시피의 산출물을
선택하고 install-info를 추가했다. 73개 복사본의 크기와 SHA-256이
원본과 일치하며 server-core 런타임 의존성 66개를 모두 포함한다.
후보 repo/index.x86_64.json 및 metadata.x86_64.json을 생성하고
기존 stage3-v3 Ed25519 키로 서명, 외부 공개키로 검증했다.

rootfs 입력은 /tmp/kiki-server-info-rootfs-YfYG7pT7/rootfs 이다.
ki2ctl 0.1.0-11과 install-info 7.2-2가 포함되며 GTK는 release 11이다.
installer 모드, install-image/VHDX 제외 옵션으로 ISO 빌드를 시작했다.
출력 예정 경로:
/tmp/kiki-iso-info-AIpJhzX7/output/kiki-stage3-v3-installer-x86_64-20260909-gtk11-ki2ctl11.iso.

현재 이 항목은 입력 준비 기록이다. ISO 빌드 종료·재추출 검증·VM 설치
완료를 뜻하지 않는다. 이전 GTK11 ISO와 재추출 자료는 보존한다.

### 반복 실행 가능한 재추출 검증

`tools/ki2readback.py`는 이미 추출된 ISO 디렉터리를 읽기 전용으로 검사한다.
ISO 마운트/추출 또는 디스크 설치는 하지 않는다. 서명·패키지 검사는 기존
`ki2media`를 사용하고, initramfs newc와 rootfs tar의 GTK/스키마 파일을
각각 명시한 외부 빌드 참조와 비교한다. rootfs 캐시 재생성을 고려해 그래픽
입력과 조립된 rootfs 참조를 별도로 지정한다.

```sh
python3 -B tools/ki2readback.py \
  --media-root dist/iso/hardening-validation/readback-gtk11-20260909 \
  --public-key build/ki2/keys/stage3-v3-repo.ed25519.pub \
  --graphics-reference build/ki2/host-graphics/rootfs \
  --rootfs-reference /tmp/kiki-gtk11-rootfs-licl9wCV/rootfs
```

GTK11 재추출본에서 종료 코드 0: 패키지 72개, initramfs 44개 및 rootfs 44개의
GTK/스키마 파일 검증을 통과했다. 두 gzip 스트림을 EOF까지 읽어 CRC를 확인한다.
`test_ki2readback` 3개 통과: 정상 입력, 중복/누락/잘림/불일치, trailer 뒤
비정상 데이터와 gzip CRC 오류를 검사했다.

주의: 참조 경로는 호출자가 선택한 비교 기준이지 독립적인 신뢰 인증서가 아니다.
현재 도구는 전체 rootfs 원본 비교, GRUB 브랜딩 비교, VM 부팅/설치를 검사하지 않는다.
새 그래픽 빌드 후에는 해당 ISO를 만들 때 사용한 보존 참조 경로를 지정해야 한다.

### GTK11 최신 후보 — 스키마 수정 포함, 정적 재추출 검증 완료

파일: `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-gtk11.iso`.
입력/빌드 트리: `/tmp/kiki-gtk11-rootfs-licl9wCV`.
GTK11 스키마 원본 보존 수정을 포함하며 rootfs의 스키마 캐시가 재생성된다.
저장소는 72개 패키지로 생성했고 Ed25519 서명 및 파일명·크기·해시 집합 대조를 통과했다.
빌드 종료 코드 0, 크기 4,158,820,352바이트. SHA-256:
`03d591db6691c9a6831974497180b9788e404a6fe9d50456e5c9ad25c63e8c27`.
동일 이름의 `.iso.sha256`를 저장했다. 기존 ISO는 모두 보존했다.

실제 ISO 전체를 `readback-gtk11-20260909`에 재추출했다(754개 파일).

- 외부 신뢰 공개키로 Ed25519 서명·인덱스·72개 패키지 크기/SHA-256 검증 통과.
- initramfs gzip 해제와 newc 구조/trailer를 확인하고 GTK 실행 파일 및 스키마
  43개(총 44개)를 빌드 원본과 바이트 대조했다.
- 설치용 rootfs tar 내부의 동일 44개 파일 대조 및 gzip 끝까지 읽기/CRC 검증 통과.
- ISO 루트 `manifest.json`을 읽어 GRUB 로고/테마의 선언된 SHA-256을 대조했다.

이 결과는 rootfs 전체 파일의 원본 비교나 실제 부팅·설치 성공을 뜻하지 않는다.
GUI/TUI/CLI 동일 ISO VM 설치 시험과 GNOME 전체 데스크톱 통합은 미완료다.

### GTK10 의존성 일치 후보 — ISO 빌드·저장소 재추출 검증 완료

새 작업 디렉터리 `/tmp/kiki-gtk10-final-0dnroffE`에서 GMP/libffi를 각각
6.3.0-2/3.4.8-2로 교체했다. 기존 후보와 패키지는 그대로 보존했다.
rootfs 조립 및 엄격한 systemd 유닛 연결이 정상 종료했고, 저장소 인덱스는
72개로 복구됐다. Ed25519 메타데이터 검증과 실제 72개 패키지의 파일명 집합,
크기, SHA-256 전수 대조가 통과했다.

이 입력으로 `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-gtk10.iso`를 빌드했다.
`--no-install-image --no-hyperv-vhdx`, 기존 공개키를 initramfs에 포함한다.
빌드 종료 코드 0, 크기 4,158,720,000바이트. SHA-256은
`b635ba07160d4a8377d2dcf8b852697eaa7a228beeac9c8eb5a4927ebdc57ae3`이며
별도 `.iso.sha256`도 저장했다. 아래 이전 후보의 70개 인덱스를 사용하지 않는다.

실제 ISO에서 `readback-gtk10-20260909`로 저장소·패키지 등 76개 파일을
재추출했다. `ki2media.py`로 외부 공개키를 사용한 Ed25519 서명, 인덱스,
72개 패키지 크기·SHA-256 검증을 통과했다. 이번 검사는 initramfs/rootfs 내부
파일 전수 비교, 실제 부팅, GUI/TUI/CLI 설치 성공을 입증하지 않는다.
스키마 캐시 문제 및 VM 검증은 남아 있다. 기존 ISO는 보존했다.
정정: GTK10 재추출 명령은 manifest 경로를 잘못 지정했으므로 해당 검사에
ISO 루트 manifest 확인은 포함되지 않았다. 위 GTK11 검사에서 올바른 경로를 확인했다.

### GTK10 후보 준비 중 — ISO 미완성

작업 디렉터리 `/tmp/kiki-gtk10-iso-nj1nfFiH`에 기존 GTK9 패키지 스냅샷을
복사하고 GTK10으로 교체했다. rootfs 조립과 엄격한 systemd 유닛 연결은
종료 코드 0이다. 스키마 XML 부재로 캐시가 제거되는 메시지는 별도 점검 대상이다.
입력·로그·GTK 진행 회귀검사 41개도 통과했다.

저장소 생성 시 다음 입력 오류를 발견해 ISO 작업을 중단했다.

- `ki2repo --packages-dir`은 `.ki2`가 직접 들어 있는 `packages/x86_64`를
  요구한다. 부모 디렉터리 지정으로 0개 인덱스가 생성됐으며 이를 사용한
  ISO 빌드는 중단했다. 도구가 빈 결과를 메타데이터 기록 전에 거부하도록
  수정했고 저장소 회귀검사 4개가 통과했다.
- `--iso-dir`도 후보 전용 `/tmp/kiki-gtk10-iso-nj1nfFiH/output`으로 명시해
  과거 ISO 목록이 새 메타데이터에 포함되지 않게 했다.
- 올바른 경로로 생성한 인덱스는 70개이고 Ed25519 검증은 통과했다.
  기존 스냅샷의 `gmp-6.3.0-1`, `libffi-3.4.8-1`은 현재 레시피 release 2와
  달라 제외됐다. 패키지 디렉터리는 72개이므로 아직 ISO 입력으로 사용하면 안 된다.
  두 의존성을 이미 검증한 release 2로 교체하고 rootfs/서명 저장소를 재조립해야 한다.

GTK10 ISO 완료 또는 실제 VM 설치 성공으로 간주하지 않는다.
기존 GTK9 logging ISO와 서명키는 변경하지 않았다.

### 보존한 GTK9 logging 후보 — 빌드/재추출 검사 완료, VM 미실행

파일: `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-gtk9-logging.iso`.
입력은 아래 GTK9 후보의 rootfs/repo/packages 스냅샷을 그대로 사용했다.
입력 전달 write/close/dup2 실패 처리, GUI 요청 암호 버퍼 정리,
GUI 상세 백엔드 로그 및 GUI/TUI 로그 연결 공통화를 반영했다.
빌드 트리: `/tmp/kiki-logging-iso-1vZMnZSS/iso-tree`. 종료 코드 0.
크기 4,158,572,544바이트, ISO SHA-256:
`25df37aeac79e77f1066ca2f803aa7280b12b4f10dda2ecada0e8769a1950920`.
별도 `.iso.sha256`를 저장했다. ki2bootiso.py 입력 해시:
`edb0475d378d82cc5e8e81599a11a29788846031fefa6f29249b95fe18088956`.

`readback-gtk9-logging-20260909`로 재추출해 Ed25519 서명/인덱스/72개 패키지
크기·해시 검증을 통과했다. initramfs 내 검증 도구 4개·GTK·로고·공개키는
현재 원본과 일치한다. init에 GUI 로그 경로와 입력 연결/콘솔 복원 오류 문자열이
존재하고 init SHA-256은
`9926f9a85febb953797516e4b9df2c297f94df0df71c83ade848db423e2950df`이다.
initramfs gzip CRC 및 GRUB 테마/로고의 manifest 해시도 확인했다.
rootfs.tar.gz를 끝까지 압축 해제한 tar SHA-256은 이전 GTK9 후보와 동일하다:
`3bf33d74759eb03acd7775aedc71423485c977e0ef8c2c900f9471fb5cfd6e73`.
따라서 이전 GTK9 rootfs의 GTK/curl/GGUF 검증 결과와 같은 내용이다.
정적 재추출 검사는 실제 코드 경로 실행, GUI/TUI/CLI 설치 성공, 로그의 재부팅 후
보존을 입증하지 않는다. VM 실기 시험과 GNOME 전체 데스크톱 구성은 여전히 미완료다.
기존 ISO/서명키는 모두 보존했다.

### 보존한 GTK9 후보 — 빌드 및 재추출 정적 검사 완료, VM 미실행

작업 루트: `/tmp/kiki-gtk9-iso-93JtCIV3`.
이전 current 후보의 패키지 스냅샷에서 curl 8.8.0-1과 GTK 0.1.0-8을
각각 curl 8.8.0-4와 GTK 0.1.0-9로 교체한 별도 스냅샷을 생성했다.
다른 GNOME 개발용 신규 패키지는 추가하지 않았고 기존 스냅샷은 보존했다.
server-core rootfs 조립과 72개 패키지 저장소 생성은 종료 코드 0이다.
기존 stage3-v3 Ed25519 키로 새 메타데이터를 서명하고 공개키 검증을 통과했다.

완성 파일:
`dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-gtk9.iso`.
위 작업 루트의 rootfs/repo/packages/x86_64를 입력으로 사용하며 iso-tree를 보존한다.
`--no-install-image --no-hyperv-vhdx`이고 기존 ISO는 변경하지 않는다.
빌드 시작 시 ki2bootiso.py SHA-256:
`3a3b03a71e18a0aaf934cb91810f8067da260d4345829e1e800747f29d81b2e6`.
빌드 종료 코드 0, 4,158,570,496바이트. ISO SHA-256:
`07124f67f6902a3304b4b8771cb9076213f6d435ba9387cb14c86c7993d69bd4`.
별도 `.iso.sha256` 파일을 저장했고 빌드 전후 ki2bootiso.py 해시도 일치했다.
Windows 7-Zip으로 boot/kiki/manifest.json을
`dist/iso/hardening-validation/readback-gtk9-20260909`에 재추출했다.
재추출본의 Ed25519 서명·인덱스·전체 72개 패키지 크기/해시 검증을 통과했다.
initramfs를 gzip/newc로 끝까지 읽어 CRC를 확인했고 GTK9 실행 파일, 원본 로고,
외부 신뢰 공개키의 바이트 해시가 일치했다. GRUB 테마/로고도 manifest 해시와 일치했다.
rootfs tar의 14,089개 항목을 순회하며 gzip CRC를 확인하고 GTK9/curl4 실행 파일과
GGUF 모델 해시를 대조했다. 이는 전체 rootfs 파일별 원본 비교를 의미하지 않는다.
GUI/TUI/CLI 실제 부팅·설치 검증 및 GNOME 전체 데스크톱 구성은 아직 미완료다.
병행한 별도 WSL 확인 명령은 `Wsl/Service/0x8007274c`로 시작에 실패했다.
이는 기존 ISO 빌드 프로세스의 종료 증거가 아니므로 빌드를 중복 실행하지 않았다.

### 보존한 installed-brand 후보 — 빌드/정적 검사 완료, VM 미실행

완성 산출물: `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260909-installed-brand.iso`.
설치 후 ESP 로고/테마 전달과 GRUB 설정, gfxmenu/png UEFI 모듈을 반영한 후보를
빌드했다. 설치기 회귀 테스트 34개와 실제 생성 설정의 GRUB 구문 검사 통과.
빌드 입력 `tools/ki2bootiso.py` SHA-256:
`3a3b03a71e18a0aaf934cb91810f8067da260d4345829e1e800747f29d81b2e6`.

입력은 `/tmp/kiki-current-iso-qB019rhA/rootfs`, 같은 경로의 `repo`,
보존한 `iso-tree/kiki/packages/x86_64` 스냅샷이다. 진행 중인 libgcc/GNOME 빌드의
패키지는 포함하지 않는다. `--no-install-image --no-hyperv-vhdx`이며,
새 트리는 `/tmp/kiki-installed-brand-nM9ohzYY/iso-tree`에 보존한다.
빌드 종료 코드 0, 크기 4,158,550,016바이트. SHA-256:
`ae3df00994a9ad82f1a5c4f3b4b2abec0c5b8ec651c287d3ec850f94bce1758c`.
빌드 전후 설치기 소스 해시가 일치했고 별도 `.iso.sha256` 파일을 저장했다.
`readback-installed-brand-20260909` 재추출본에서 Ed25519 서명·인덱스 및
전체 72개 패키지 검증을 통과했다. initramfs 내 검증 도구 4개·공개키·로고는
원본 바이트 해시와 일치하고 init 바이너리에 새 브랜딩 실패 메시지가 존재한다.
GRUB 테마/로고의 manifest 해시 및 initramfs gzip CRC도 확인했다.
rootfs tar의 전체 SHA-256과 gzip CRC가 기존 검증본과 같았다:
`a4e8de4fa027ed5c6df594985c803d46887f86d2fe6f86d419c548bb4640bd1a`.
실제 GUI/TUI/CLI VM 검증도 미실행이다. 기존 ISO는 덮어쓰지 않았다.

### 보존한 request-guard 후보 — VM 설치 미실행

파일: `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260908-request-guard.iso`.
크기 4,158,404,608바이트, SHA-256:
`4a29228f6a4ad917b8336e182f7b58380de60837279f868c6103391e4e054a70`.
설치 요청의 파일 길이/NUL/부분 읽기 검사와 실패 시 암호 버퍼 정리를 추가한
현재 소스로 initramfs를 다시 생성했다. 설치기 테스트 32개와 빌드 종료 코드 0 확인.
빌드 입력 ki2bootiso.py SHA-256:
`79f351c4142056f801c45d05845b6fe363ca7cac3e9deb454d0c9e00dde933b4`.

검증 완료 rootfs와 서명 저장소 스냅샷을 재사용했으며 72개 패키지를 유지한다.
libusb 및 GNOME 기반 패키지 캐시 수정 이후의 재빌드 결과는 포함하지 않는다.
별도 설치 완료 이미지와 VHDX는 생성하지 않았다.

완성 ISO를 `readback-request-guard-20260908`에 재추출한 뒤 Ed25519 서명,
인덱스 및 전체 72개 패키지의 크기·해시를 검증했다. initramfs 8개 파일
(검증 도구 4개·공개키·GUI/TUI 실행 파일·로고), GRUB 로고/테마가 입력과 일치한다.
ki2bootiso.py의 빌드 전후 해시도 일치했다.
gzip CRC 및 전체 압축 해제 rootfs tar 해시는 이전 current 후보와 동일하다:
`a4e8de4fa027ed5c6df594985c803d46887f86d2fe6f86d419c548bb4640bd1a`.
따라서 아래 14,090개 항목의 원본 일치 검사 결과와 같은 rootfs 내용이다.
이 결과를 실제 VM 부팅/설치 또는 GNOME 데스크톱 제공 완료로 간주하지 않는다.
빌드 트리는 `/tmp/kiki-request-guard-GX0tSAQZ/iso-tree`에 보존했다.

### 보존한 current 후보 — 빌드 및 정적 검증 완료, VM 설치 미실행

2026-09-08 새 `server-core` rootfs 조립이 정상 종료됐다.
임시 빌드 경로는 `/tmp/kiki-current-iso-qB019rhA`이며 실제 설치 기록은 65개다.
TUI 0.1.0-10, GTK 0.1.0-8, ki2ctl 0.1.0-9, llama-cpp b10516-2와
GGUF 1개를 확인했다. 새 저장소는 72개 패키지, 2,518,578,005바이트이며
Ed25519 서명 및 공개키 검증이 통과했다. GNOME 기반 패키지 4개가 저장소에
추가됐으나 기본 rootfs에 GNOME 데스크톱을 설치하거나 선택지를 노출하지 않았다.

완성 ISO 경로:
`dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260908-current.iso`.
크기: 4,158,404,608바이트. SHA-256:
`9a2714426b853b2a870eb4ded122fe32b2c9b0a42a758b8d95caba506935e8d6`.
빌드 종료 코드 0 및 완성 파일 해시 확인 완료. 기존 ISO는 모두 보존했다.
이번 후보는 `--no-install-image --no-hyperv-vhdx`로 생성한 패키지 기반 설치 ISO다.
별도 설치 완료 이미지/VHDX는 미생성이다. GUI/TUI/CLI의 guided 설치 시험에 사용할
후보이며, 별도 이미지 복사 방식 검증용 산출물과 동일하다고 간주하지 않는다.

Windows 7-Zip으로 완성 ISO의 boot, 저장소, 패키지, UEFI payload 및 manifest를
`dist/iso/hardening-validation/readback-current-20260908`에 재추출했다.
Ed25519 서명/인덱스/72개 패키지의 크기·해시 검증 통과.
initramfs를 gzip/newc 스트림으로 읽어 GUI/TUI 실행 파일은 새 rootfs와,
검증 도구 4개·공개키·GTK 로고는 빌드 소스와 바이트 해시 일치를 확인했다.
GRUB 테마/로고 원본 일치, GUI 기본 설정 및 UEFI 부트로더 포함도 정적 확인했다.
후속 검사에서 ISO의 rootfs tar도 재추출해 전체 14,090개 항목을 원본 조립
rootfs와 비교했다. 파일 11,656개는 내용 해시, 심볼릭 링크 1,587개는 대상,
디렉터리 847개는 종류를 확인했으며 모든 항목의 권한 및 전체 경로 집합도 일치했다.
gzip 스트림을 끝까지 읽어 CRC/종료 검사를 통과했다. GGUF 경로는
`var/lib/kiki/models/kiki-ops.gguf`, SHA-256은
`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`이다.
이 검사는 압축 파일의 원본 일치를 입증하며 OS 부팅 가능성이나 설치 성공을
입증하지 않는다. 실제 VM 부팅/설치는 수행하지 않았다.

빌드 입력 `tools/ki2bootiso.py` SHA-256:
`726a94df3ff12d8911ab921230d6af40a53de5480ac14b1aa785e37cdd719a67`.
직전 검사: 설치기 Python 테스트 31개, 빌드 도구 20개, 미디어 검증 2개 및
TUI Go 테스트 통과. 실제 ISO 부팅이나 설치 결과는 아니다.

### 보존한 io-units 후보

- 파일: `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260908-io-units.iso`
- 크기: 8,124,499,968바이트
- SHA-256: `ef7ee269d5c3be1ed90ef7819de736ce22f0da676413c3d5f650d12352ad845d`
- 서비스 링크/단위 누락, 파일 I/O, 대상 커널/initramfs 복사, sudoers/시간대 오류 처리 반영.
- 재추출한 ISO의 Ed25519 서명/인덱스/68개 패키지 검증 통과.
  init 바이너리의 새 오류 메시지, 빌드 입력 소스 해시, 검증 도구/공개키 및 GTK/GRUB
  로고의 원본 일치 확인. GNOME 데스크톱은 미포함이며 실제 VM 검증은 미실행.

### 보존한 dark-blue 후보

- 파일: `dist/iso/brand-validation/kiki-stage3-v3-installer-x86_64-20260908-dark-blue.iso`
- 크기: 8,124,493,824바이트
- SHA-256: `d3140c419c90cc85ac009d9136630f660a16ed81a6dab31a979f7252279adc8c`
- GTK 0.1.0-8과 dark-blue GRUB/GTK 로고 포함, GNOME 데스크톱은 미포함.
- 재추출한 ISO의 Ed25519 서명/인덱스/68개 패키지 검증 통과.
  GRUB 테마/로고, initramfs GTK 로고·검증기 4개·신뢰 공개키의 원본 일치 확인.
- 로고의 실제 화면 표시와 아래 GUI/TUI/CLI 설치 매트릭스는 아직 미실행.

### 보존한 이전 후보

- 파일: `dist/iso/validation/kiki-stage3-v3-installer-x86_64-20260908-gpt-tui-validation.iso`
- 크기: 8,118,009,856바이트
- SHA-256: `9b8237fe801391d36ad45d8ea8a6a8e796d2f4279c51d093e4a0f71fb4fc304e`
- 완성 ISO에서 재추출한 저장소의 Ed25519 서명과 68개 패키지 해시 검증 통과.
- initramfs 검증기/공개키의 원본 일치 및 GUI 기본 부팅 설정 정적 확인 완료.
- 위 결과는 아래 실기 매트릭스의 통과 기록이 아니다.

## 실행 전 게이트

- 운영자가 폐기 가능한 테스트 VM과 가상 디스크를 지정하고 변경을 허용해야 한다.
- 호스트 디스크, 운영 데이터 디스크, 공유 저장소를 연결하지 않는다.
- ISO 생성이 정상 종료되고 SHA-256을 계산한 후 세 경로 모두 같은 파일을 사용한다.
- VM 세대/펌웨어, CPU/RAM, 디스크 크기/논리 섹터 크기, 네트워크를 기록한다.
- guided 설치는 UEFI VM에서 시험한다. Secure Boot 지원 완료로 간주하지 않는다.
- 각 경로는 깨끗한 폐기형 디스크에서 시작한다. 다른 경로의 설치 결과를 재사용하지 않는다.
- 암호·토큰·비밀 키는 스크린샷이나 첨부 로그에 기록하지 않는다.

## 정상 설치 매트릭스

| 항목 | GUI (`kiki.ui=gui`) | TUI (`kiki.ui=tui`) | CLI (`kiki.ui=cli`) |
| --- | --- | --- | --- |
| 부팅 후 해당 화면/입력 정상 | 미실행 | 미실행 | 미실행 |
| 프로필·패키지 그룹·AI·네트워크 선택 반영 | 미실행 | 미실행 | 미실행 |
| 암호 확인 및 정확한 디스크 삭제 확인 | 미실행 | 미실행 | 미실행 |
| 확인 취소 시 대상 디스크 무변경 | 미실행 | 미실행 | 미실행 |
| 미디어 검증 후 GPT/포맷 실행 | 미실행 | 미실행 | 미실행 |
| 진행률·완료/전체 패키지 개수 표시 | 미실행 | 미실행 | 미실행 |
| 마지막 구성/부트로더/마운트 해제 후 성공 | 미실행 | 미실행 | 미실행 |
| 완료 확인 후 재부팅 및 ISO 제거 부팅 | 미실행 | 미실행 | 미실행 |
| tty1 AI 및 tty2 복구 셸, 실행 전 명령 승인 | 미실행 | 미실행 | 미실행 |

GUI/TUI에서는 설치 중 해당 화면이 유지되는지, GUI에서는 한글과 버튼이
잘리는지, TUI에서는 ASCII 폴백과 키 조작이 실제로 동작하는지도 확인한다.
CLI는 화면형 진행바를 임의로 통과 처리하지 말고 실제 제공되는 표시를 기록한다.

## 실패 및 폴백 매트릭스

- GUI 시작 실패 → TUI 진입 → CLI 복귀. 원래 GUI 오류 로그도 보존한다.
- 서명·인덱스·패키지 변조/누락: 설치 거부 및 대상 디스크의 전후 해시 동일.
  변조 시험은 원본 ISO를 보존한 별도 복사본으로만 수행한다.
- 작은 디스크, 사용 중인 디스크/파티션, 활성 swap 대상: 파티션 작성 거부.
- 패키지 추출/필수 구성/계정/부트로더/마운트 해제 실패: 성공 100% 또는
  성공 전용 재부팅 확인이 표시되지 않아야 한다.
- 실패 후 재시도: 이전 요청/성공 상태를 새 설치 성공으로 오인하지 않아야 한다.
- GPT: ESP/선택 swap/root 타입, 정렬, 주·백업 헤더와 설치 후 UEFI 부팅 확인.
- 대용량 및 4Kn 시험은 해당 가상 장치가 준비된 경우 별도 실행하며,
  512바이트 섹터 시험만으로 통과 처리하지 않는다.

## 결과마다 남길 증거

- ISO 절대 경로, 크기, SHA-256, 빌드 커밋과 미커밋 변경 여부
- VM/가상 디스크 식별자, 부팅 인자, 선택한 프로필/그룹/AI/네트워크
- 시작/종료 시각, 실제 기대 결과와 관측 결과, 통과/실패/미실행
- 비밀정보를 제거한 화면과 로그:
  `/run/kiki/gui-installer.log`, `/run/kiki/tui-install.log`,
  `/run/kiki/install-progress.state`, 설치 대상 `/var/lib/ki2/install-plan.yaml`
- 설치 후 `systemctl --failed`, 네트워크 및 AI 서비스 상태

`/run` 로그는 재부팅하면 사라지므로 재부팅 전에 수집한다. 원시 설치 요청 파일에는
암호가 들어갈 수 있으므로 증거 첨부 대상으로 사용하지 않는다.

현재 Hyper-V 조회는 접근 거부 상태다. 권한/대상 VM이 준비될 때까지 이 문서의
실기 항목은 미실행으로 유지한다.
