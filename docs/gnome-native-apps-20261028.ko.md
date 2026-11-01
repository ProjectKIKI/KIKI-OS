# GNOME 기본 앱 구성 개선

`desktop-gnome` 그룹은 GNOME Control Center 50.4, Nautilus 50.2.2,
GNOME Console 50.0을 기본 앱으로 선택합니다. 이전 실험용
`kiki-desktop-tools` 소스는 보존하지만 새 후보의 기본 앱으로 설치하지 않습니다.
GNOME 설정 실행 파일과 desktop ID를 가로채던 래퍼도 제거했습니다.

즐겨찾기, 폴더 MIME 기본 앱, Console 로그인 셸, GNOME 배경화면,
IBus 한글 엔진의 설정 실행 경로를 실제 GNOME 앱에 연결했습니다.
한글 입력 소스와 Super+Space, Shift+Space 설정을 유지합니다.

데스크톱은 NetworkManager 1.58.0을 사용합니다. 설치기가 지정한 DHCP·고정 IP·
비활성 상태, MAC 주소, DNS, IPv6 RA와 NTP를 대상 시스템에 기록합니다.
네트워크 장치 이름이 부팅 후 바뀌어도 MAC 주소로 연결을 찾습니다.
desktop 그룹은 networkd 서비스와 소켓을 비활성화하고 NetworkManager를
활성화합니다. 서버 프로파일의 networkd 동작은 유지합니다.

새 패키지는 기존 KIKI ABI의 별도 SDK에서 빌드했습니다. GNOME 공식 50.4
빌드 메타데이터와 freedesktop-sdk의 고정 커밋을 사용하며 소스 URL·SHA는
`tools/gnome_native/sources.json`에 보존합니다. 도구와 실제 빌드 옵션은
`tools/gnome_native/`에 있습니다. 보존된 SDK·vendor 입력이 필요한 후보
빌드이며 상세 재현 조건은 해당 디렉터리의 README에 명시합니다.

기존 ISO·서명된 패키지 후보·사용자가 확인하던 VM은 보존합니다.
후보 서명은 공식 릴리스 서명과 별개이며 개인키는 배포하지 않습니다.
UDisks는 클라이언트 라이브러리 구성입니다. 이동식 미디어 자동 마운트,
실물 GPU·무선·오디오·프린터·화면 공유는 별도 장치 검증이 필요합니다.

## 최종 후보와 실제 설치 검증

검증한 후보는 `gnome-native-apps-20261028-r3`입니다. ISO는
`artifacts/gnome-native-apps-20261028/kiki-gnome-native-apps-20261028-r3.iso`이며
SHA-256은 `646051b312d1162bf75e00e4dcf38991fd25e8318c03d75f50c2f75383ab7598`입니다.
미디어의 223개 KI2를 다시 읽어 Ed25519 서명과 SHA를 검사했고,
GNOME 설치 프로필의 의존성은 206개입니다. `desktop-gnome.toml`은 이 후보의
공개키와 저장소 인덱스 SHA에 고정했습니다.

Hyper-V 2세대 `kiki-gnome-apps-r3-20261028`의 새 32GB 가상 디스크에
한국어 GTK 설치기로 설치했습니다. ISO를 분리한 디스크 부팅, GDM/Wayland
로그인, 두 번째 재부팅과 재로그인에서 각각 28개 검사가 모두 통과했습니다.
시스템·사용자 실패 유닛은 없으며 UPower의 PrivateUsers·RestrictNamespaces
보호도 유지합니다. VM의 Secure Boot 서명은 제공하지 않습니다.

실제 화면에서 GNOME 설정의 네트워크 연결과 모양 변경, Nautilus의 폴더 생성·
이름 변경·복사·휴지통 이동, GNOME Console의 Bash 셸과 IBus 한글 조합을
확인했습니다. 직접 입력한 `한글` 파일, 폴더 작업 결과와 어두운 테마 설정이
재부팅 후에도 유지됐습니다. 문서 포털의 실제 FUSE 마운트도 검사했습니다.
증거는 같은 artifacts 디렉터리의 `guest-r3-first.json`,
`guest-r3-reboot.json`, `iso-readback-validation.json`,
`rootfs-payload-validation.json`, `vm-r3/` 화면에 있습니다.

시험에서 발견한 파일 포털 의존성 누락을 보완하고 Linux 6.1.187에 FUSE를
추가했습니다. systemd가 찾는 `/usr/bin/mount`와 `/usr/bin/umount`를 기존
util-linux 실행 파일에 연결했습니다. 암호 라이브러리는 ABI 1을 유지하면서
실제 SONAME 2를 별도로 빌드했고, 두 ABI의 올바른 암호·틀린 암호 처리가
일치하는지 확인했습니다. 설치 계획서도 실제 NetworkManager 구성을 기록합니다.

관련 Python 설치·미디어 테스트 55개, 릴리즈 관리 테스트 48개와 Go 설치기
테스트가 통과했습니다. 프로필 검증은 206개 레시피를 확인했습니다.
루트 파일시스템의 일반 파일 30,623개가 패키지 명세와 일치합니다.
프로필에 따라 생성하는 default.target과 ld.so.cache만 예외로 기록합니다.

## 빌드 서버 동기화 방식

소스 커밋과 후보는 별도 경로로 보관하고 기존 dirty checkout을 덮어쓰지
않습니다. 새 데스크톱 ISO는 현재 패키지 그룹을 사용하고, 이전 후보는
`--legacy-backend`로 보존한 빌드 도구를 사용합니다. 보존 설치기 래퍼도
명시한 저장소의 ISO 생성기를 불러옵니다.

서버에 보관하는 로컬 ISO는 검증한 바이트를 그대로 복사합니다.
서버에서 재컴파일한 결과로 표시하지 않습니다. 버전 라이브러리의 새 서명
스냅샷은 로컬 ISO에 내장된 서명 인덱스와 구분하고, 실제 설치 증거는
동일한 ISO SHA에 연결합니다. 개인 서명키는 전송하지 않습니다.

## 후속 관리자 앱 후보

위 ISO와 설치 검증 기록은 GNOME 기본 앱 후보의 이력이다. 이후 추가한
`KIKI 관리자`는 별도 서명 후보 `dist/ki2/kiki-admin-20261028-r4`에 포함하며,
현재 `desktop-gnome.toml`은 이 후보를 사용한다. 기존 GNOME ISO 파일은
변경하지 않았다. 관리자 앱의 기능·권한·검증 범위는
[`cmd/kiki-admin/README.ko.md`](../cmd/kiki-admin/README.ko.md)에 기록한다.
