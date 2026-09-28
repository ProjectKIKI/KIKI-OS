# Stage 3 Podman r21 배포 후보 (2026-09-29)

## 산출물

- 시험용 설치 ISO: `dist/iso/kiki-stage3-v3-installer-x86_64-20260929-r21-podman.iso`
- 크기: 4,199,766,016 bytes
- SHA-256: `324c319caf14dcedbde5cb01e1ef1536f08ba174303bf42955bb2d9a51914560`
- 별도 서명 KI2 저장소: `dist/ki2/signed-podman-r21/`
- Git 공개 메타데이터: `releases/ki2/stage3-v3-20260929-podman/repo/`

기존 r20의 116개 패키지에 `conmon`, `crun`,
`kiki-podman-bootstrap-5.8.2-5`를 더해 총 119개다. Git에는 ISO, KI2
바이너리, 서명 개인키를 넣지 않는다. 저장소를 실제 배포할 때는
`dist/ki2/signed-podman-r21/` 아래의 공개 메타데이터와
`packages/x86_64/` 전체를 함께 제공해야 한다.

## 확인한 범위

- Rocky-9 WSL에서 Podman KI2 레시피 검증·빌드 및 KIKI glibc 2.39 로더의
  `podman --version` 시험 통과.
- 공개키로 후보 저장소와 Git 복사본의 Ed25519 서명 검증 통과.
- 격리 루트의 `ki2ctl update` 서명 검증과 Podman 설치 의존성 계획 통과.
- WSL 내부의 빈 시험 루트에 서명 저장소에서 Podman과 런타임 의존 패키지
  27개, 총 28개 KI2를 실제 설치했다. 별도 마운트 네임스페이스에서 KIKI KI2 루트의
  `kiki-podman-check`가 `podman version 5.8.2`, `cgroup=v2`,
  `network=netavark`, `storage=overlay`를 보고했다. 이는 WSL 커널 시험이며
  KIKI VM 부팅 시험으로 간주하지 않는다.
- 완성 ISO의 BIOS·UEFI 부팅 카탈로그 확인.
- ISO에서 독립 재추출한 저장소 서명과 119개 KI2 파일의 SHA-256 전수 검증 통과.

이 패키지는 rootful 전용 Rocky 9 ABI 부트스트랩이며 네이티브 KIKI 빌드가
아니다. 이미지 정책은 기본 거부이므로 승인된 이미지 서명·출처 정책을
설정하기 전에는 pull이 차단된다. **KIKI OS VM에서 실제 설치·부팅,
컨테이너 실행, 네트워크 및 Quadlet 재시작은 아직 검증되지 않았다.**
따라서 기본 설치 그룹이나 운영 채널로의 자동 승격은 하지 않았다.
사용 중인 Rocky 시험 VM과 기존 r20 ISO는 변경하지 않았다.
