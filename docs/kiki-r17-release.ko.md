# r17 AI 콘솔 응답 처리 수정 (2026-09-27)

## 변경 내용

- kiki-ai-console 0.1.0-5. 나머지 73개 패키지는 서명 검증된 r16 미디어를 유지합니다.
- 인사/설명은 kiki-ai-message-v1의 reply로 표시하고 실행 단계에 진입하지 않습니다.
- 관리 작업은 kiki-ai-command-plan-v1로 표시하고 명시적 execute 승인을 기다립니다.
- JSON 객체만 요구하던 요청에 실제 응답 스키마 제약을 추가했습니다.
  응답 종류(kind)를 먼저 생성하도록 속성 순서를 보존합니다.
- 스키마 없는 응답, 잘린 응답, 대화에 실행 명령이 섞인 응답을 거부합니다.
  모델 내용 검증 실패는 한 번만 재시도하며, 실패 시 실행하지 않습니다.
- 명령 계획을 대화로 분류하거나 질문을 요약만 하던 소형 모델 동작도
  실제 모델 시험으로 확인하고 프롬프트/대화 필드를 조정했습니다.
- 부팅 검사에 --ai 옵션을 추가했습니다. 설치된 모델에 실제 질의하지만
  --once로 계획만 확인하며 생성된 명령은 실행하지 않습니다.

스키마 제약 API는 [llama.cpp 서버 문서](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)를 참고했습니다.
제약된 생성과 별도로 Go의 수신 검증을 유지합니다.

## 검증

- Go 단위 테스트, race 검사, go vet 통과.
- 격리 부팅 도구 안전성 3개, 부팅 서비스 회귀 10개 통과.
- 동봉된 실제 GGUF와 llama-server의 로컬 포트에서 Hello, 기능 안내,
  DHCP 설명, uname -r 계획을 검증했습니다. 생성된 명령은 실행하지 않았습니다.
- 최종 ISO 독립 재추출: 서명 및 74개 패키지, initramfs/rootfs 선택 파일 각 44개 통과.
- ISO rootfs의 AI 콘솔 해시가 패키지 빌드 바이너리와 일치합니다:
  e52c33153d511d2b9a2cd13e8e68ca0d986dd1edc7d75d663a7065bd634f8041
- 새 20GB 디스크에 Go/GTK4 GUI로 66개 패키지 설치 완료.
  ISO 분리 후 설치 디스크의 UEFI/GRUB 부팅과 tty1 Hello 정상 응답을 직접 확인했습니다.
- 설치 디스크의 격리 오버레이에서 14개 자동 검사 모두 통과:
  kernel 6.1, networkd, D-Bus, IPv4, 기본 경로, DNS, 실패 서비스 없음,
  swap, AI 콘솔, sudo, sudo 로그인 셸, Hello, DHCP 설명, uname -r 계획.
  실제 모델 질의 포함 174.9초. 서비스 override나 DNSSEC 시험 변경은 없었습니다.
- GUI/UEFI 시험은 실제 화면 수동 검토이며, 14개 자동 검사는 별도 직접 커널
  부팅 오버레이에서 실행했습니다. 둘을 같은 시험으로 간주하지 않습니다.
- 생성된 uname -r 계획은 --once로 검사했으며 실제 실행하지 않았습니다.
  CPU 2개/RAM 2GB 시험에서 모델 질의는 수십 초가 걸릴 수 있습니다.
- AI 계획 검사는 스키마와 요청한 주 명령의 표시를 확인한 것이며, 모든 명령의
  의미적 정확성을 보장하지 않습니다. 실제 시험에서 읽기 전용 uname -r 계획에
  불필요하고 잘못된 rollback argv (uname -r old_version)가 덧붙은 사례가 있었습니다.
  해당 명령은 실행하지 않았습니다. 모델 계획 품질 개선은 남은 제한 사항입니다.

## 전달 파일

- E:\dev\KIKI-OS\dist\iso\kiki-stage3-v3-installer-x86_64-20260927-r17.iso
- 크기: 4,083,105,792 bytes.
- SHA-256: de62af8e1eabff6da17fd79d05c42c6293308bf71a3e7480d5ac871101de1b82
- WSL 원본, Windows 배포 복사본을 WSL 및 Windows 양쪽에서 대조했습니다.
- 증거: build/validation/20260927-r17/ (실제 VM 화면, 설치 결과, 테스트 로그).

## 배포 주의사항

- 커널 6.1.187-kiki-vm, Go/GTK4 설치 UI와 DNSSEC=no 정책을 유지합니다.
- 모델 가중치는 변경하지 않았습니다. 답변/명령의 의미적 정확성을 보장하지 않으므로
  변경 명령은 실행 전에 반드시 검토하세요. 대화 내용은 매 요청 단위로 처리합니다.
- 이 공개 ISO는 Secure Boot OFF로 시험하세요.
- 사용자 Hyper-V VM을 변경하지 않고 격리된 QEMU에서 검증합니다.
- 기존 ISO는 보존하며 새 r17 파일을 별도로 제공합니다.
