# 6.1 인스톨러 안정화 기록 (2026-09-10)

## 범위

현재 독립 ki2 배포판의 설치 ISO와 설치 대상 커널을 6.1.187로 통일한다.
별도 legacy Alpine/Debian 설치 경로는 이번 변경 대상이 아니다.
버전과 SHA-256은 kernel.org의 공식 배포 자료로 확인했다.

- https://www.kernel.org/releases.json
- https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc

## 변경

- linux/linux-headers 소스는 6.1.187로 고정. 지정 커널 패키지가 없으면 예전 캐시로 대체하지 않고 실패한다.
- Hyper-V 스토리지 옵션명을 CONFIG_HYPERV_STORAGE로 명시하고 QEMU UEFI용 DRM_BOCHS를 포함한다.
- 설치된 OS의 기본 부팅 인자에서 진단용 keep_bootcon을 제거한다.
- GUI 최종 검토에 주소/게이트웨이/DNS 표시. GUI가 호출하는 공통 계획 생성기는 IP/CIDR, DNS, 장치, 게이트웨이 주소 계열과 서브넷을 검사한다.
- 잘못된 입력은 디스크 변경 전에 차단한다. 현재 연결 확인 버튼은 설정을 적용하지 않는 읽기 전용 기능이다.
- 기본 콘솔 영문 출력과 NIC 선택 구현은 installer-network-console-20260910.ko.md 참고.

## 실제 시험에서 발견한 추가 문제

첫 r13 후보는 서명 및 패키지 74개, initramfs/rootfs 각 45개 선택 파일 검증에 통과했다.
새 20GB 폐기형 가상 디스크에 42.4초 만에 설치 완료했다.
직접 커널 부팅에서 6.1.187, swap, DHCP 주소/기본 경로, sudo 및 sudo 로그인 셸을 확인했다.
하지만 일반 사용자의 systemctl 조회는 실패했으므로 배포 완료로 판정하지 않았다.

원인은 dbus.socket 누락과 systemd 지원 없이 빌드된 dbus-daemon이었다.
systemd 255 소스의 manager_dbus_is_running은 소켓과 서비스 상태를 모두 검사한다.
이 조건이 충족되지 않아 PID 1이 시스템 버스에 등록되지 않았다.

수정은 dbus.socket + --address=systemd: + --systemd-activation 구성과
--enable-systemd 명시 빌드다. helper의 setuid 권한을 임의로 늘리지 않는다.
D-Bus는 systemd/libsystemd에 의존하고 systemd 자체에서는 dbus 의존을 제거하여 순환을 피한다.
최소/서버 프로필은 계속 두 패키지를 모두 선택한다.
D-Bus 빌드는 기존 phase-0 호스트 SDK 경계를 유지한다.

systemd 재빌드에서는 c_args가 CFLAGS의 sysroot를 덮어써 호스트 키보드 헤더가 섞이는 문제도 발견했다.
Meson c_args에도 대상 sysroot를 명시하여 생성기와 컴파일러가 동일한 6.1 헤더를 사용하도록 수정했다.

## 시험 도구와 보존 경로

- tools/ki2installsmoke.py: 새 디스크에만 설치하며 기존 디스크를 재사용하지 않는다.
- tools/ki2bootsmoke.py: 성공한 설치 시험 디스크를 기반으로 별도 qcow2 오버레이에서 부팅한다.
- direct 모드는 서비스 검증이며 펌웨어/GRUB 검증이 아니다.
- uefi 모드는 실제 펌웨어/GRUB 부팅과 기본/tty2 화면을 수집하며 이미지의 수동 검토가 필요하다.
- --dbus-unit-override는 진단 전용이며 결과에 명시된다. 이 결과를 수정 없는 ISO 시험으로 간주하지 않는다.
- 초기 후보/시험: WSL Rocky-9 /tmp/kiki-61-iso-candidate.
- 커널 추가 그래픽 빌드: /tmp/kiki-61-bochs-build.
- D-Bus/systemd 수정 빌드: /tmp/kiki-dbus-socket-build2.

현재 사용자 Hyper-V VM의 디스크와 펌웨어 키는 변경하지 않았다.
최종 ISO 재검증 완료 전 기존 ISO를 제거하지 않는다.
Secure Boot는 기본 부팅 안정화 이후 별도 서명/신뢰 체인 검증 단계다.

## r14 재검증 결과와 배포 보류 사유

- 후보 ISO: Rocky-9 `/tmp/kiki-61-iso-final/kiki-stage3-v3-installer-x86_64-20260910-r14.iso`.
- linux 6.1.187-2, headers 6.1.187-1, base-files 21, systemd 255.7-5, dbus 1.14.10-8.
- rootfs 계약 검사 3개, ISO 재추출 패키지 74개 및 initramfs/rootfs 각 45개 선택 파일 검증 통과.
- 새 디스크 설치 42.4초 완료. 직접 부팅에서 커널, networkd, D-Bus, DHCP 주소, 기본 경로,
  swap, AI 콘솔, sudo, sudo 로그인 셸 및 실패 서비스 없음 확인.
- 실제 OVMF/설치된 GRUB 부팅 화면을 검토했다. 영문 AI 콘솔과 Ctrl+Alt+F2 로그인 화면 정상.
  6.1.187 표시 확인. 이는 QEMU 결과이며 실제 Hyper-V VM 재설치 결과가 아니다.
- **DNS 기본 경로 검사는 실패했으므로 전체 runtime 결과는 success=false로 유지한다.**
  busybox nslookup으로 10.0.2.3 및 1.1.1.1 직접 조회는 모두 응답했다.
  같은 폐기형 overlay에서 per-link DNSSEC만 끄면 getent/resolvectl 조회가 즉시 성공했다.
  resolved 로그에는 DNSSEC `failed-auxiliary`가 기록됐다. NAT 환경의 DNSSEC 검증 경로 문제로
  범위를 좁혔지만 하위 실패의 모든 원인을 확정한 것은 아니다.
- DNSSEC 기본값 변경은 서명 검증을 하지 않게 되는 보안 차이가 있으므로 사용자에게 선택을 요청했다.
  답변 전 원본 ISO 및 base-files의 DNSSEC 설정은 변경하지 않았다.
- 기존 공개 r12 ISO는 보존했다. DNS 정책 확정 → 수정본 빌드 → 무수정 새 설치/부팅 검사 통과 후
  최종 ISO 게시 및 기존 ISO 제거를 수행해야 한다.

검증 증거: `build/validation/20260910-r14/`의 JSON, 로그 및 UEFI PNG 화면.
Secure Boot의 별도 시험 결과는 `secureboot-isolated-lab-20260910.ko.md` 참고.

## 2026-09-13 후속 처리

사용자가 DNSSEC 기본값 해제를 승인했다. r15에서 base-files 22와 설치 대상 DNS 설정을
`DNSSEC=no`로 변경했고, 새 설치 후 설정을 임시 변경하지 않은 검사에서 DNS 포함 11개 항목이
모두 통과했다. 위 r14 배포 보류 기록은 당시의 결과이며, 최신 결과는 `kiki-r15-release.ko.md`를 따른다.
