# Go / gotk4 설치기

GTK 4용 gotk4 v0.2.2를 사용하는 별도 Go 모듈입니다. 현재 C 설치기를 삭제하지
않고, 같은 Go CLI 계획 생성기와 Stage-1 설치 백엔드에 연결합니다.
기본 화면은 영어이며 기존 ISO의 Noto CJK 글꼴로 백엔드 한글 메시지를 표시합니다.

## 화면

디스크 선택 → NIC와 DHCP/고정 IP/오프라인 → 계정 및 접힌 고급 설정 →
설치 계획 검토 → 삭제 동의 → 설치 진행/결과/명시적 재부팅 순서입니다.
INSTALL /dev/sda를 직접 입력할 필요는 없습니다. 뒤로 돌아가 수정하면
계획을 다시 생성하고 삭제 동의를 다시 받습니다.

## 개발 및 안전한 실행

Linux에 Go 1.21 이상, C 컴파일러, GTK 4 개발 헤더, pkg-config,
gobject-introspection-devel이 필요합니다. GTK 4.12.3 빌드 환경을 대상으로 합니다.

~~~sh
go build -o build/kiki-installer-tui ./cmd/kiki-installer-tui
cd cmd/kiki-installer-gotk
go mod download
make
KIKI_INSTALLER_TUI=../../build/kiki-installer-tui ./kiki-installer-gotk
# 디스플레이에서 창을 잠시 열고 자동 종료; 설치 요청은 보내지 않음
./kiki-installer-gotk --smoke
~~~

기본 실행은 PREVIEW입니다. 임시 폴더에 설치 계획만 생성하며 디스크 설치와
네트워크 적용을 수행하지 않습니다. 직접 실행할 때 실제 설치는 --live를
지정해야 하며 root, 설치 미디어, 삭제 동의와 암호 검증이 필요합니다.
일반 개발 PC에서는 --live를 사용하지 마세요.

암호는 CLI 인자·설치 계획에 넣지 않으며, 백엔드 요청 파일에만 0600 권한으로
전달합니다. 기존 요청을 덮어쓰지 않습니다. 실행 중인 설치는 창 닫기를 막습니다.
실패 시 Ctrl+Alt+F2 복구 콘솔과 /run/kiki/gui-install-backend.log 경로를 안내합니다.

## 테스트

~~~sh
KIKI_TEST_TUI=/absolute/path/to/kiki-installer-tui go test -v ./...
~~~

GTK 태그 없이도 입력 검증, 요청 형식, 암호 비노출, 원자적 요청 게시,
진행 상태 파싱 및 실제 CLI 계획 생성기 연동을 테스트할 수 있습니다.

## ISO 빌드에 선택적으로 연결

~~~sh
python3 tools/ki2graphics.py prepare --installer-ui gotk \
  --output build/ki2/host-graphics-gotk/rootfs \
  --work /tmp/kiki-graphics-gotk
~~~

이 선택은 기존 실행 경로 /usr/bin/kiki-installer-gtk에 Go 바이너리를
배치하고 ISO용 실제 설치 모드를 기본으로 빌드합니다. 기존 Stage-1 실행
경로는 바뀌지 않습니다. 기본 --installer-ui c는 기존 C 버전을 유지합니다.
별도 출력 rootfs를 사용하면 기존 그래픽 산출물을 보존할 수 있습니다.

위 명령은 그래픽 런타임만 생성합니다. 기존 ISO의 내용은 바뀌지 않습니다.
gotk4 실설치·재부팅 인수 테스트 전에는 배포 ISO 기본 구현을 교체하지 않습니다.
원격 패키지 소스, 수동 파티션 편집, 자동 오류 복구는 이번 간단한 UI 범위 밖입니다.

## 2026-09-26 검증 결과

- Rocky Linux 9 / Go 1.25.9 / GTK 4.12.3에서 실행 파일 빌드 성공.
- WSLg 디스플레이에서 --smoke 실행: GOTK_UI_SMOKE_OK, 정상 종료.
- Go 테스트 6개(입력 거부 하위 시나리오 10개 포함), 실제 CLI 계획 생성기 연동,
  race 검사와 go vet 통과.
- 그래픽 패키징 회귀 테스트 7개 및 Go 라이선스 수집·재실행 통과.
- ISO용 gotk 개발 의존성 doctor 통과.
- r16 후보를 새 20GB QEMU 디스크에 실제 GUI로 설치하고, ISO를 분리한 뒤
  UEFI/설치 GRUB 부팅 및 tty2 계정 로그인을 확인했습니다.
- 설치 중 eth0 → 설치 후 enp0s2 이름 변경에도 MAC 주소 매칭으로 DHCP가 유지됩니다.
- 설치 디스크의 격리 오버레이에서 커널, networkd, D-Bus, IPv4, 경로, DNS,
  실패 서비스 없음, swap, AI 콘솔, sudo, sudo 로그인 셸 11개 검사가 통과했습니다.
- r16 공개 ISO를 별도로 생성했습니다. 기존 r15 ISO 및 Hyper-V VM은 변경하지 않았습니다.
  자세한 범위와 화면 증거는 docs/kiki-r16-release.ko.md를 참고하세요.
