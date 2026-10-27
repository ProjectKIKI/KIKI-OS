# Rocky 9.8 Hyper-V 10대 시험 설치 (2026-09-28)

- 범위: 기존 시험 VM `kiki-iso-lab-01` 및 새로 만든 빈 시험 VM `02..10`만 사용. `kiki-os-test`, `crc`는 변경하지 않음.
- 설치 매체: `F:\isos\Rocky-9.8-x86_64-minimal.iso`; SHA-256 `d338032cd1cdd41c67139f2f71b4c832c8e4a21943106519db9c7137df7a63d4`.
- 각 VM: Generation 2, 전용 16 GiB VHDX, Default Switch, Rocky Minimal, DHCP, Asia/Seoul, SELinux enforcing, 방화벽 활성화, SSH 비활성화.
- 시험용 계정: `rocky`; root와 해당 계정의 시험용 암호는 사용자 요청대로 `rocky`.
- 02번은 메모리를 1 GiB에서 2 GiB로 올려 설치. 09번은 Linux 인증서 Secure Boot 템플릿을 적용해 설치 및 부팅 확인.
- 검증: 01..10 모두 설치된 디스크에서 재부팅해 Rocky Linux 9.8 로그인 화면에 도달. 10대 모두 실행 중이고 펌웨어 첫 부팅 항목은 `Rocky Linux Minimal`.
- 설치 완료 후 각 VM의 가상 DVD에서 Rocky ISO와 Kickstart OEMDRV 매체를 분리함. 원본 ISO/OEMDRV 파일과 VHDX는 보존.
- 미검증: 게스트 콘솔 실제 로그인, 게스트 IP/DHCP·인터넷 연결, 패키지·서비스 동작. Hyper-V 키-값 쌍 교환 서비스가 `연결 안 됨`이어서 호스트의 `IPAddresses` 값은 비어 있음. 따라서 이를 네트워크 실패나 성공으로 단정하지 않음.
- KIKI OS로 전환하지 않음. 추가 Rocky 기능 시험 후 사용자 결정에 따라 진행.

## IP 확인 및 journald gateway 요청 후속

- Hyper-V Default Switch의 IPv4 이웃 테이블과 VM MAC 주소를 대조한 결과: 01 `172.25.78.216`, 02 `172.25.79.175`, 03 `172.25.66.23`, 04 `172.25.71.250`, 05 `172.25.79.83`, 07 `172.25.66.115`, 08 `172.25.72.238`, 09 `172.25.78.14`, 10 `172.25.73.208`.
- 06은 최초 설치 당시 가상 스위치가 연결되지 않았고, Default Switch 재연결·정상 재부팅 후에도 IPv4 주소가 관찰되지 않음. 게스트 콘솔 로그인 화면은 정상. 이웃 테이블 값은 DHCP 임대처럼 변경될 수 있음.
- 06~08 NIC를 Default Switch에 연결함. 01~05, 09~10은 이미 연결돼 있었음.
- Rocky 9 저장소의 정확한 패키지 이름은 `systemd-journal-remote`이며 그 안에 `/usr/lib/systemd/systemd-journal-gatewayd`, `.service`, `.socket`이 포함됨.
- 패키지 설치는 아직 하지 않음: 최초 설치 정책상 SSH가 비활성화돼 있고 Hyper-V 콘솔 입력 API가 Linux에서 잘못된 키코드를 전송함. 게스트 접근 방식에 대한 사용자 결정 필요.

## SSH 활성화 재설치 및 gatewayd 패키지 (최신 상태)

위의 SSH 비활성화·패키지 미설치·06 IP 미확인 기록은 재설치 이전 상태이며, 아래가 현재 상태이다.

- 사용자 요청에 따라 01..10을 모두 재설치. 이전 VHDX는 삭제하지 않고 `F:\hyper-v\kiki-iso-lab-20260928\pre-ssh-reinstall\`에 VM별로 백업.
- 모두 Rocky 9.8, Default Switch, SSH 활성화, `rocky` 계정 wheel 그룹 및 암호를 요구하는 sudo. 시험용 사용자·root 암호는 `rocky`. SSH 설정에서 root 로그인은 금지.
- 10대 모두 재부팅 후 SSH 22번 포트 열림. 01은 실제 암호 SSH 로그인, sudo 사용 및 설정 확인. 02..10은 실제 SSH 로그인과 sudo로 패키지 설치 완료.
- 10대 모두 `systemd-journal-remote-252-67.el9_8.6.rocky.0.1.x86_64` 설치 및 `/usr/lib/systemd/systemd-journal-gatewayd` 실행 파일 확인. gatewayd socket은 01에서 disabled 확인; HTTP 엔드포인트는 노출하지 않음.
- 09는 Secure Boot On + MicrosoftUEFICertificateAuthority 템플릿, Rocky 부팅 및 SSH 패키지 설치 성공. 나머지 9대는 Secure Boot Off.
- 설치 후 모든 가상 DVD 매체 분리. 첫 부팅 항목은 `Rocky Linux Minimal`.
- 현재 IPv4 주소 (DHCP이므로 변경 가능): 01 `172.25.78.216`, 02 `172.25.79.175`, 03 `172.25.66.23`, 04 `172.25.71.250`, 05 `172.25.79.83`, 06 `172.25.67.118`, 07 `172.25.66.115`, 08 `172.25.72.238`, 09 `172.25.78.14`, 10 `172.25.73.208`.
- `kiki-os-test`, `crc`는 변경하지 않았고 Off 상태. KIKI OS 전환은 하지 않음.
- 시험용 약한 암호이므로 격리된 실험망에만 사용하고, 장기 사용 전에는 계정 암호 교체 및 SSH 접근 제한 필요.
