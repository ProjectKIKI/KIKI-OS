# KIKI OS 에이전트 연결 준비 상태

기준: 2026-09-29. 이 문서는 준비 판정과 연결 전에 필요한 정보를 기록한다.
비밀 토큰·비밀번호·개인키는 이 문서나 Git에 기록하지 않는다.

## 현재 판정: 준비 중

- 새 `KIKI · 키키` 로고 설치 ISO는 `dist/iso/kiki-stage3-v3-installer-x86_64-20260929-r21-kiki-wordmark.iso`다. SHA-256은 `309dab02a07bab81f7d94c624d36bc0ec668e637ee16d1726c9f09bdc2f64c9b`이다. BIOS/UEFI 부팅 카탈로그, 로고·테마 원본 해시, r21 저장소 메타데이터와 패키지 목록 119개를 확인했다. 실제 VM 설치 완료를 확인한 것은 아니다.
- ISO는 기존 r21 KI2를 재사용한다. `kiki-installer-gtk-0.1.0-16`이 포함되므로 최신 로고가 GUI 패키지에 반영되었다고 주장하지 않는다. 로컬 `0.1.0-17`은 이 서명 저장소에 없다.
- `libmicrohttpd`, `systemd-journal-gatewayd`, `systemd-journal-transport`는 별도 후보 저장소 `dist/ki2/systemd-journal-candidate-01/`에 있다. r21 저장소와 ISO에는 넣지 않았다. 현재 문서화된 ABI·루프백 HTTP 시험은 KIKI VM의 실제 systemd 소켓·TLS 전송 검증이 아니다.
- 기존 `kiki-iso-lab-01`~`10`은 현재 Paused 상태이며 r20 ISO 시험용이다. 사용자 `kiki-os-test`와 `crc`를 포함해 기존 VM·디스크를 변경하지 않는다. 기존 시험 기록은 [Hyper-V 10대 스모크](kiki-hyperv-10vm-smoke-20260928.ko.md)에 있다.

## 준비 완료 판정에 필요한 순서

1. 최신 GUI 인스톨러와 필요한 KI2를 재빌드하고, 패키지 파일·저장소 인덱스·Ed25519 서명을 함께 검증한다. journal 후보는 격리 VM의 실제 동작 검증 전 운영 채널로 승격하지 않는다.
2. 기존 ISO를 덮어쓰지 않고 별도 이름으로 설치 ISO를 생성한다. ISO에서 다시 꺼낸 공개 메타데이터·패키지·로고의 해시와 BIOS/UEFI 부팅 항목을 확인한다.
3. 기존 사용자 VM과 구분되는 격리 Hyper-V Generation 2 VM에서 설치, 디스크 부팅, 로그인, DHCP·DNS, 기본 systemd 서비스와 `journalctl`을 확인한다.
4. journal 확장은 기본 자동 활성화하지 않는다. 격리 VM에서 루프백 게이트웨이 소켓·HTTP 응답, remote·upload 서비스, 재부팅 후 유닛 상태, TLS 설정과 접근 제어를 확인한다. 실패 시 운영 저장소 반영을 중단한다.
5. 실제 에이전트 연결 방법과 노드별 확인 결과를 기록한 뒤 준비 완료를 선언한다.

## 연결 전 운영자가 준비할 정보

- 접속할 관리 서버의 HTTPS 주소·포트, 신뢰할 CA 인증서 또는 공개키, 접근 가능한 DNS/네트워크 경로.
- 각 노드의 고유 이름과 연결 대상 VM 식별자, 예상 IP/SSH 접근 경로. IP는 설치 후 실제 DHCP 결과로 수집하고 추정하지 않는다.
- `kiki-bootstrapd` 관리자가 발급하는 **노드별 만료 일회성 등록 토큰**. 토큰은 비밀 파일 또는 비밀 관리자로 전달하며 채팅·Git·설치 로그에 원문을 남기지 않는다.
- 등록 후 받은 노드 Bearer 토큰은 해당 노드만 보관한다. 관리자 토큰, 공장 토큰, 노드 토큰을 재사용하지 않는다.
- 연결 실패 시 확인할 설치 로그, `systemctl status kiki-agent`, `journalctl -u kiki-agent` 및 관리 서버 이벤트 경로.

등록 API와 토큰 교환 계약은 [kiki-bootstrapd](../cmd/kiki-bootstrapd/README.md)와 [kiki-agent](../cmd/kiki-agent/README.md)를 따른다. 실제 URL·토큰·노드 이름이 정해지기 전에는 예시 값을 사용해 연결 성공으로 표시하지 않는다.
