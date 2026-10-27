# 설치 82% 시간대 오류 수정

증상: 패키지 설치 후 `Selected timezone could not be applied.`로 중단됨.
검사한 TUI11 이미지의 rootfs에는 `/usr/share/zoneinfo`가 없었으며,
기본 패키지 그룹과 레시피에도 tzdata가 없었다.

## 변경

- IANA tzdata 2025b를 SHA-256으로 고정한 독립 패키지로 추가했다.
- 최소 그룹(서버/Kubernetes 그룹의 기반) 및 TUI 기본 선택에 포함했다.
- Stage-1은 모든 프로필에서 tzdata를 필수 선택하고 미디어에 없으면
  GPT 기록 및 포맷 전에 중단한다.
- 시간대 적용 실패 로그에 예상 파일 경로를 남긴다.
- 기존 오류 중단 정책은 유지하며 UTC로 조용히 대체하지 않는다.

## 검증

실제 tzdata 패키지를 빌드하고, 그 payload의 서울/UTC/뉴욕 시간대 오프셋과
설치기에서 사용하는 localtime 링크 설정 스크립트를 검사했다.
잘못된 시간대는 실패하며 기존 localtime 링크는 유지된다.
`test_tzdata_runtime.py` 실행 시 `KIKI_TZDATA_ROOT`에 패키지 payload 경로를 지정한다.

## 통합 검증 완료 (2026-09-09)

추가로 발견한 GLib 스키마 도구 누락은 설치 시 런타임 의존성을 생략했던
문제였다. 서명 검증된 인덱스에서 런타임 의존성을 재귀적으로 해석하고,
누락/순환/선택 용량 초과는 디스크 변경 전에 차단하도록 수정했다.
자동 설치 후 PID 1 종료로 발생하던 커널 패닉도 CLI 복귀로 수정했다.

- GTK12/TUI12/ki2ctl12와 tzdata 패키지를 새로 빌드했다.
- 최종 ISO 재추출 검사: 서명과 패키지 74개, initramfs 선택 파일 45개,
  rootfs 선택 파일 45개 검증 통과.
- 최종 ISO 기반, 네트워크 없는 KVM(호스트 CPU, RAM 2GB)의 새 20GB
  가상 디스크에 server-core + 로컬 AI 설치가 43.3초에 완료됐다.
- 실제 설치 65개 패키지, 시간대/GLib/계정/UEFI 파일 설치, 디스크 마무리
  및 CLI 복귀까지 확인했다.
- GUI 클릭 설치 및 설치된 디스크의 UEFI 재부팅 검증은 포함하지 않는다.

배포 파일: `dist/iso/kiki-stage3-v3-installer-x86_64-20260909-r12.iso`

크기: 4,159,428,608 bytes

SHA-256: `9f1b7ba155cec1ba536e26197f8c83db377d252d488a8f22269d1b8ad3ef9ac1`

빌드와 테스트 로그는 Rocky-9의 `/tmp/kiki-tzfix-iso-PpmI1U`에 보존했다.
최종 시험 결과는 `vm-final-test/result.json`, 직렬 로그는 `vm-final-test/serial.log`다.
