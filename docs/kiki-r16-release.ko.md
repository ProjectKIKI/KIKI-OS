# r16 Go/GTK4 설치 UI (2026-09-26)

## 산출물

- ISO: E:\dev\KIKI-OS\dist\iso\kiki-stage3-v3-installer-x86_64-20260926-r16.iso
- Windows 복사본 SHA-256: bbdaa3ff277fd8af928c51f3057211413d23626ef33af5d6129d302ae2c9e2a0
- 2026-09-27 WSL 통신 복구 후 원본과 Windows 복사본 해시 일치를 확인했습니다.
  이후 발견된 AI 응답 처리 오류 수정은 r17로 제공됩니다.
- 크기: 4,083,103,744 bytes.
- 기존 r15 ISO와 실제 Hyper-V kiki-os-test VM은 변경하지 않았습니다.

## 변경 범위

- kiki-installer-gtk 0.1.0-15: Go/gotk4 GUI. 디스크 및 NIC 선택,
  DHCP/정적 주소, 계정, 설치 계획 검토, 삭제 동의, 진행률 및 완료 후 재부팅.
- kiki-netconfig 0.1.0-2 관리 도구 포함.
- 다른 72개 패키지는 검증된 r15 미디어에서 가져왔습니다.
  커널은 6.1.187-2, 실행 버전 6.1.187-kiki-vm을 유지합니다.
- 실제 GUI 시험에서 발견한 설치 미디어 선행 마운트 검사 오류를 수정했습니다.
  설치 모드 부팅인지 확인한 다음 기존 Stage-1이 미디어를 마운트하고 검증합니다.
- 선택한 실제 NIC는 MACAddress로 매칭합니다. 설치 전후 NIC 이름 변경을 허용합니다.
  수동 패턴 입력과 네트워크 비활성화 정책은 유지합니다.
- 그래픽 런타임의 절대 심볼릭 링크는 패키지 내부 상대 링크로 정규화합니다.
- 이번 후보는 별도 패키지 스냅샷으로 생성했으며, 전체 작업 중인 레시피를
  무조건 재빌드하지 않았습니다. 기본 C 그래픽 빌드 경로는 유지됩니다.

## 실제 시험 결과

1. ISO를 독립적으로 재추출해 외부 공개키로 서명과 74개 패키지를 검증했습니다.
   initramfs와 rootfs의 선택 파일 각각 44개도 대조했습니다.
2. OVMF UEFI + QEMU/KVM, RAM 2GB, 새 20GB 디스크에서 기본 메뉴로
   Go/GTK4 GUI를 부팅했습니다. 자동 설치가 아닌 실제 입력/클릭으로 진행했습니다.
3. 선택한 /dev/vda에 66개 패키지 설치가 완료됐으며 완료 화면을 직접 검토했습니다.
   GUI의 한글 완료 메시지는 정상 렌더링됐습니다.
4. ISO를 분리한 다음 GUI 재부팅 버튼으로 설치 디스크의 UEFI/GRUB 부팅을 확인했습니다.
   영문 AI 콘솔, Ctrl+Alt+F2 로그인, 설치한 관리자 계정 로그인에 성공했습니다.
5. 설치 시 eth0였던 NIC가 enp0s2로 바뀌었지만 10.0.2.15/24 DHCP 주소를 받았습니다.
6. 해당 설치 디스크를 변경하지 않는 별도 오버레이/직접 커널 부팅에서 11개 검사가
   모두 통과했습니다: kernel 6.1, networkd, D-Bus, IPv4, 기본 경로, DNS,
   실패 서비스 없음, swap, AI 콘솔, sudo, sudo 로그인 셸. 실행 시간 8.1초.
   임시 서비스 override나 시험 중 DNSSEC 변경은 사용하지 않았습니다.

증거 원본은 WSL /tmp/kiki-r16/gui-final/ 및 /tmp/kiki-r16/runtime-final/에 있습니다.
WSL 통신 복구 후 주요 JSON, 로그, 설치 완료·부팅·로그인 화면을
build/validation/20260926-r16/에 보존했습니다.
gui-install.json은 완료 화면의 수동 검토 기록이며 자동 이미지 판정 결과가 아닙니다.
runtime.json은 서비스 자동 검사 결과입니다. PNG는 실제 VM 화면을 형식 변환한 것입니다.
시험 디스크와 시험용 계정은 ISO에 포함하지 않았습니다.

## 제한 및 사용자 시험

- 실제 Hyper-V 하드웨어 경로는 이번 시험에서 실행하지 않았습니다.
  사용자 환경은 2세대 / Default Switch에서 최종 시험하세요.
- 공개 ISO는 Secure Boot OFF로 시험해야 합니다.
  이전 자체 서명 격리 시험과 공개 ISO의 펌웨어 신뢰는 별개입니다.
- QEMU std/Bochs 그래픽에서는 PRIME import 실패로 TUI fallback이 나타났습니다.
  이번 GUI 합격 시험은 virtio VGA를 사용했습니다.
- WSL 시험 환경의 QEMU 및 virtio 디스플레이 모듈을 업데이트했습니다.
  Windows Hyper-V 설정과 키는 변경하지 않았습니다.
- 원격 패키지 저장소 선택, 수동 파티션 편집, 자동 오류 복구는 간단한 새 UI 범위 밖입니다.
