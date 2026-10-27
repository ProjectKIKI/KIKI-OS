# 부팅 서비스 수정 진행 기록 (2026-09-09)

## Hyper-V 접근 확인 (2026-09-10)

사용자가 관리자 접근을 허용하여 `kiki-os-test`를 조회하고 기존 디스크로 시작했다.
2세대, Default Switch, 메모리 4GiB, vCPU 8개이며 Secure Boot는 Off이다.
기존 펌웨어 템플릿 이름은 MicrosoftWindows이지만 Secure Boot가 꺼져 있으므로
현재 서명 검증에 사용되는 상태는 아니다. DVD에는 ISO가 연결되어 있지 않았다.
디스크, 가상 스위치, Secure Boot 설정은 변경하지 않았다.

시작 후 VM Running 및 하트비트 상태 확인. KVP 교환은 연결 안 됨이며 호스트에
보고된 IP 목록은 비어 있었다. 이것만으로 DHCP 실패라고 판단할 수 없다.
Windows 화면 제어 스킬이 요구하는 node_repl 실행 도구가 이 세션에 없어
게스트 화면을 직접 확인하지 못했다. 사용자 화면 확인을 위해 VM은 실행 상태로 두었다.
아래의 '모든 시험 VM은 종료' 기록은 9월 9일 QEMU 시험 종료 당시 상태다.

## 상태

작업 중. 새 배포 ISO 및 Secure Boot는 아직 완료하지 않았다.
기존 r12 ISO는 보존했다. 아래 VM 검증은 r12 설치 시험 디스크의 별도
차등 디스크에 수정 파일을 적용한 결과이며, 새 ISO의 설치 검증은 아니다.
모든 시험 VM은 종료했다. 실제 사용자 디스크나 UEFI 키는 변경하지 않았다.

## 확인된 원인과 수정

- **swap**: BusyBox 패키지가 util-linux의 `/sbin/swapon`을 덮어썼다.
  systemd가 전달하는 `--fixpgsz`를 BusyBox가 지원하지 않아 실패했다.
  BusyBox 패키지에서 swapon/swapoff/mkswap 링크를 제외했다.
  VM에서 systemd를 통한 활성화 및 UEFI 재부팅 시 swap 활성화를 확인했다.
- **온라인 대기**: 기본 IPv4 DHCP 구성에 맞춰 `--any --ipv4 --timeout=30`,
  서비스 상한 35초를 적용했다. 로컬 AI 콘솔의 network-online 의존성을 제거했다.
  NAT VM에서 DHCP 10.0.2.15, routable/online, wait-online 종료 코드 0을 확인했다.
  사용자는 NAT라고 답했으나 가상머신 프로그램은 아직 확인되지 않았다.
  대기 제한은 DHCP 연결 실패 자체를 해결하는 설정은 아니다.
- **D-Bus 정책 손상**: firewalld 소스의 `FirewallD.conf`와 `firewalld.conf`가
  Windows 파일시스템에서 충돌했다. Linux `/tmp`에서 재빌드하여 XML을 복원했다.
  빌더는 대소문자를 구분하지 않는 경로에서 이런 충돌이 있으면 중단한다.
- **D-Bus 초기 권한**: dbus-daemon이 system.conf에 따라 직접 messagebus로
  권한을 낮추도록 서비스의 선행 User/Group 설정을 제거했다.
- **networkctl D-Bus 경고**: systemd 정책/서비스 파일이 빌드 sysroot의 절대 경로
  아래에 패키징되어 있었다. 세 D-Bus 설치 경로를 `/usr/share/dbus-1` 아래로
  명시했다. VM에서 파일을 정상 위치로 복원하고 서비스를 재시작하자 경고가 사라졌다.

## 한글 콘솔: 구현했으나 화면 검증 미완료

`kiki-kmscon` 패키지와 `tools/ki2kmscon.py`를 추가했다.
kmscon 10.0.3 / libtsm 4.7.1 소스는 SHA-256으로 고정한다.
FreeType와 Noto Sans Mono CJK KR 글꼴을 사용하며, 호스트 ABI 라이브러리는
`/usr/lib/kiki-kmscon/lib`에 격리한다. 빌드에 사용한 RPM 목록과 라이선스를 포함한다.
이것은 네이티브 패키지로 완전히 이행하기 전의 bootstrap 런타임이다.

AI 콘솔 서비스는 kmscon을 통해 실행하도록 연결했다. tty2 getty는 유지한다.
VM에서 글꼴 로딩, DRM 장치 인식, AI 프로세스의 PTY 연결은 확인했지만
화면은 검증에 실패했다. QEMU 기본 VGA에서는 펌웨어 framebuffer 1280x800과
화면 캡처 800x600의 불일치 및 기본 tty2까지 깨지는 현상이 있었고,
가상 VGA 최대 해상도를 800x600으로 제한하자 해상도는 맞았지만 한글 콘솔은
검은 화면이었다. **한글 표시 해결 완료로 간주하면 안 된다.**
호스트 libxkbcommon과 Compose 데이터 간 dead_hamza 경고도 추가 확인 대상이다.

## 생성 및 검증

- busybox 1.36.1-2
- base-files 0.1.0-20
- firewalld 2.5.1-11
- systemd 255.7-4
- kiki-ai-console 0.1.0-3
- kiki-kmscon 10.0.3-1

패키지 경로: `dist/ki2/packages/x86_64`.
실제 패키지에서 swap 링크 제외, FirewallD 정책 XML, Compose 자산,
systemd D-Bus 등록 경로와 불필요한 rootfs/mnt 빌드 경로 제거를 검사했다.
`test_boot_service_regressions.py` 8개, `test_ki2build.py` 22개 통과.

## 이어서 할 일

1. 사용자 VM 프로그램 확인 및 동일 그래픽 환경에서 한글 화면/입력/tty2 전환 검증.
   로컬 QEMU에는 virtio-vga 모듈이 없고 저장소 모듈 설치 시 QEMU 업그레이드가
   필요하므로 호스트 패키지는 아직 변경하지 않았다.
2. D-Bus 패키지 전체를 적용한 새 설치 검증 및 이전 시험에서 관찰한
   sudo 로그인 셸 segfault 재확인. 아직 해결됐다고 할 수 없다.
3. 새 저장소 스냅샷/ISO 생성, 서명 검증, 설치와 설치 디스크 재부팅 검증.
   검증된 대체 ISO가 준비되면 사용자 요청 범위의 이전 ISO를 정리한다.
4. 그 뒤 Secure Boot 개발용 서명 체인을 격리된 OVMF 환경에서 구성/검증.
   실제 장비 키 등록이나 Microsoft 신뢰 체인 적용은 별도 승인/외부 절차가 필요하다.

## 시험 경로 (WSL Rocky-9)

- 패키지 빌드: `/tmp/kiki-boot-service-fix-build`
- 콘솔 빌드: `/tmp/kiki-kmscon-package-build`
- 최신 콘솔 번들: `/tmp/kiki-kmscon-package-rootfs-v2`
- 시험 차등 디스크: `/tmp/kiki-bootfix-validation.qcow2`
- 차등 디스크 기반: `/tmp/kiki-tzfix-iso-PpmI1U/vm-final-test/install-test.qcow2`
- 시험 펌웨어 변수: `/tmp/kiki-bootfix-OVMF_VARS.fd`

시험 차등 디스크의 GRUB에는 진단용 직렬 root shell 옵션을 넣었다.
이 디스크나 해당 GRUB 설정을 배포 이미지에 포함해서는 안 된다.
화면 모드 실험 변경 역시 시험 디스크에만 적용했으며 제품 소스에는 반영하지 않았다.
