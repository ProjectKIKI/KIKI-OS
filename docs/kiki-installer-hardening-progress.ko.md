# 설치기 안정화 진행 기록

## 2026-09-09 TUI 한국어 암호 백스페이스 수정 (release 11)

TUI 암호 입력이 백스페이스마다 1바이트만 지워 UTF-8 한국어 문자를
손상시키는 문제를 수정했다. 마지막 UTF-8 코드 포인트를 제거하고
삭제한 바이트는 버퍼에서 즉시 지운다. 설치 요청의 문자열 필드도
유효한 UTF-8인지 검사하여 손상된 암호가 백엔드로 전달되지 않게 했다.
이는 모든 조합 문자/이모지 grapheme 편집을 제공한다는 뜻은 아니다.

한국어 암호의 DEL/BS 두 키 처리, 비노출, 유효한 요청과 잘못된 UTF-8
거부 단위 테스트를 추가했다. 현재 TUI 전체 Go 테스트가 캐시 없이
통과했다(0.021초). 암호 문자열의 모든 Go 메모리 복제본을 완전 삭제
보장하는 변경은 아니다.

패키지 kiki-installer-tui 0.1.0-11을
/tmp/kiki-tui11-gqHRExHG에서 빌드했다(종료 코드 0,
빌드 키 2729577cdddd). 새 패키지 PTY 시험에 한국어 암호를 입력하고
백스페이스로 한 글자를 바꾼 뒤 동일한 암호로 확인하는 흐름을 넣었다.
요청의 0600 권한, 암호 바이트 일치, YAML/터미널 비노출과 모의
설치 성공·실패 흐름을 검사했다. 1개 시험이 1.220초에 통과했다.

```sh
GOPROXY=off GOSUMDB=off go test -count=1 ./cmd/kiki-installer-tui
KIKI_TEST_TUI_PTY=1 PYTHONPATH=tools python3 -B -m unittest test_tui_pty -v
```

PTY 시험은 Linux root의 임시 chroot와 모의 백엔드를 사용한다.
실제 디스크 설치·재부팅·물리 키보드 한글 입력기 검증은 하지 않았다.
기존 rootfs/ISO는 release 10 TUI 상태로 남아 있으며 release 11을
포함한 새 rootfs/ISO 통합과 실제 VM 시험은 아직 필요하다.

## 2026-09-09 설치 안전성 회귀 검사 보강

현재 소스에서 디스크·미디어·로그·진행 상태·입력 오류·서비스 유닛·
GSettings 검사를 재실행했다. 첫 실행은 19개 중 18개 통과,
조립 rootfs 경로 미지정으로 1개 생략이었다.

test_ki2disk에 다음 두 시험을 추가했다.

- 임시 sysfs/procfs 모형에서 미사용 디스크 허용, 파티션 대상 거부,
  디스크/파티션의 활성 holder 및 mount 거부, 블록 스왑과 파일 스왑
  사용 거부를 검사한다. 실제 블록 장치를 만들거나 접근하지 않는다.
- sysfs 식별 정보가 없으면 FileNotFoundError로 중단하는지 검사한다.

디스크 시험 5개가 0.632초에 통과했다. 기존 희소 이미지 기반
8 GiB/3 TiB GPT 시험도 실행됐다. 4Kn은 파티션 계산 검증 범위이며
실제 4Kn 장치 설치를 검증한 것은 아니다.

기존 /tmp/kiki-server-info-rootfs-YfYG7pT7/rootfs의 존재를 확인하고
유닛 파일을 시험용 임시 경로로 복사해 서비스 연결 검사도 수행했다.
13개 요청 유닛 및 관련 alias/Also 연결이 검증됐다. 원본 rootfs를
수정하거나 서비스를 기동하지 않았다. 최근 데스크톱 패키지가 이
rootfs에 포함됐다는 의미도 아니다.

최종 결합 실행: 21개 모두 통과, 1.994초, 생략 없음.

```sh
KIKI_ENABLE_TEST_ROOTFS=/tmp/kiki-server-info-rootfs-YfYG7pT7/rootfs PYTHONPATH=tools python3 -B -m unittest test_ki2disk test_ki2media test_install_logging test_gtk_progress test_gtk_stale_progress test_chroot_input test_systemd_enable test_graphics_schemas -v
```

서명된 시험 미디어 변조 거부, 실패 로그 처리, 잘못된 GUI 완료 상태
거부, 입력 실패 처리 등이 포함된다. 전체 ISO 부팅/설치나 동시 장치
상태 변경에 대한 안전성을 증명하는 시험은 아니다. 실제 GUI/TUI/CLI
VM 시험과 이후 변경을 포함한 ISO 재빌드는 계속 미완료로 유지한다.

## 2026-09-09 서버 rootfs에 패키지 후처리 통합

새 /tmp/kiki-server-info-rootfs-YfYG7pT7/rootfs 에 server-core를 조립했다.
종료 코드 0이며 ki2ctl 0.1.0-11과 install-info 7.2-2가 포함됐다.
GTK 설치기는 release 11, TUI는 release 10을 유지한다.
서비스 연결과 GSettings/Info 인덱스 생성이 완료됐고,
/system/ 스키마 경로 사용 중단 예정 경고는 계속 발생했다.

```sh
KIKI_SERVER_TEST_ROOTFS=/tmp/kiki-server-info-rootfs-YfYG7pT7/rootfs PYTHONPATH=tools python3 -B -m unittest test_server_rootfs -v
```

통합 읽기 전용 테스트 1개 통과(0.392초).
rootfs의 CLI가 현재 소스와 일치하며, 대상 Python으로 실행한 ki2ctl 목록에
새 패키지 두 개가 나타남을 확인했다. GMP Info 항목과 GSettings 캐시도
존재한다. 서비스 실제 기동, GTK/TUI 표시, 디스크 설치 시험은 수행하지 않았다.
조립 결과는 WSL 임시 영역에 있고 기존 ISO는 덮어쓰지 않았다.
이 결과로 새 ISO 생성이나 동일 ISO의 VM 설치 검증이 완료된 것은 아니다.

## 2026-09-09 GTK11 패키지 및 rootfs 통합 검증 완료

- 그래픽 빌드 `/tmp/kiki-gtk11-8IjctBiS/graphics`, 종료 코드 0.
  753개 파일(292,432,074바이트)을 준비했다. 기존 GTK10 입력은
  `build/ki2/host-graphics/rootfs-before-gtk11`에 보존했다.
- GTK11 패키지 빌드 키 `8cb17dd914f0`, 종료 코드 0.
  `dist/ki2/packages/x86_64/kiki-installer-gtk-0.1.0-11.x86_64.ki2`,
  142,479,553바이트, SHA-256
  `d54c4155ad4e6e829372fa8fce6e8e44802271722a4f5538f9f190c9ed35edce`.
- 패키지 내부 스키마 파일 43개(XML 38개 포함)를 빌드 원본과 바이트 비교했다.
  스키마·브랜딩·진행 상태 회귀 테스트 27개 통과(6.100초).
- `/tmp/kiki-gtk11-rootfs-licl9wCV`에 GTK10 최종 후보의 패키지를 복사하고
  GTK만 release 11로 교체했다. server-core rootfs 조립과 유닛 연결이
  정상 종료했다. 원본 없는 캐시 삭제 메시지는 더 이상 발생하지 않았다.
- 조립된 rootfs의 대상 로더/GLib에서 GTK4 FileChooser 스키마를 조회했다.
  `gschemas.compiled`는 42,876바이트이며 SHA-256은
  `c95a2655edda62782d77d8ea0fda6d011787793bcd4e6f808140ac9a0ccf218a`.
  `/system/` 스키마 경로 사용 중단 예정 경고는 남아 있다.
- GTK11 ISO 생성·서명 저장소 재생성 및 실제 VM GUI/TUI/CLI 설치 검증은
  아직 수행하지 않았다. 기존 GTK10 ISO는 그대로 보존했다.

## 2026-09-09 GSettings 원본 누락 수정 (GTK release 11 소스)

GTK10 rootfs에서 스키마 캐시가 제거되는 원인을 확인했다. 그래픽 런타임은
호스트 `gschemas.compiled`만 복사했고 XML은 제외했다. 대상 GLib으로 캐시를
재생성할 때 입력 스키마가 없어 기존 출력이 삭제됐다.

- 그래픽 런타임이 스키마 디렉터리의 XML, enum, override 및 bootstrap 캐시를
  함께 복사하도록 수정했다. 필수 XML 또는 캐시 누락은 빌드 오류로 처리한다.
- rootfs 빌더는 XML 없이 캐시만 있는 경우 캐시를 삭제하지 않고 실패한다.
- `test_graphics_schemas`/`test_ki2build` 23개 통과(4.929초).
  모의 스키마와 override 복사, 실제 GLib 재컴파일·값 조회 및 캐시 보존을 검사했다.
- 실제 호스트 스키마 38개를 임시 경로에 복사하고 GTK10 rootfs의 대상 로더와
  GLib으로 재컴파일했다. GTK4 FileChooser 스키마 조회에 성공했다.
  기존 `/system/` 경로 사용 중단 예정 경고는 발생했으며 오류는 아니었다.
  호스트 설정/기존 rootfs는 변경하지 않았다.
- 현재는 호스트 bootstrap 스키마 집합을 보존하는 단계다. 네이티브 GNOME
  스키마 패키지와의 소유권·버전 충돌 정리는 전체 GNOME 통합 시 필요하다.
- GTK 패키지는 다음 release 11로 구분했으며 아직 새 패키지/ISO는 만들지 않았다.
  GTK10 ISO에는 이 수정이 없다. 실제 GUI 화면과 VM 설치 시험은 여전히 미완료다.

## 2026-09-09 GTK release 10 패키지 빌드 완료

- `ki2graphics.py prepare`로 `/tmp/kiki-gtk10-W685P7v6/graphics`에서 런타임을
  빌드했다. 708개 파일, 292,233,381바이트, 종료 코드 0.
- 기존 `build/ki2/host-graphics/rootfs`는 `rootfs-before-gtk10`으로 보존했고
  새 런타임을 표준 rootfs 위치에 배치했다. 기존 패키지·ISO는 변경하지 않았다.
- 재현 가능한 패키징용 `distro/profiles/installer-gui.toml`을 추가했다.
  설치 대상의 GNOME 데스크톱 프로필이 아니라 설치기 런타임 빌드용이다.
- 빌드 키 `5e8c37de3dde`, 패키징 종료 코드 0.
  `dist/ki2/packages/x86_64/kiki-installer-gtk-0.1.0-10.x86_64.ki2`,
  142,459,030바이트, SHA-256
  `449fd599beea774c61e27753a662a3663c4ef50d5ac8bd4fccfc2ead8fd45d00`.
- 패키지를 다시 읽어 GTK 실행 파일이 빌드 원본과 동일하고 정체 안내 문자열을
  포함함을 확인했다. GTK SHA-256은
  `617439d26d577722d9446a382942762fa11a9ebde23a6b3f75bf3c50672557fc`.
  패키지 로고도 선택한 dark-blue 원본 바이트와 일치했다.
- 진행 검증/정체 회복/브랜딩 회귀 테스트 4개 통과(0.646초).
  실제 GUI 화면 시험 및 ISO 설치 검증은 미실행이며 GTK10 ISO는 아직 없다.

패키징 재현 명령(그래픽 런타임 준비 후):

```sh
python3 tools/ki2build.py --jobs 8 build \
  --profile distro/profiles/installer-gui.toml --only kiki-installer-gtk \
  --build-dir /tmp/kiki-gtk10-W685P7v6/packages
```

## 2026-09-09 GUI 진행 정체 안내 (GTK release 10 소스)

- 정상 형식의 진행 레코드가 120초 동안 동일하면 GUI에 복구 콘솔과
  `/run/kiki/gui-install-backend.log` 확인 안내를 표시한다.
- monotonic 시간을 사용하며 레코드 내용이 바뀌면 기준 시간을 갱신한다.
  경고 이후 갱신되면 일반 진행 메시지로 돌아온다. 진행률뿐 아니라 단계,
  패키지 및 메시지 변화를 포함한 전체 레코드를 비교한다.
- 정체는 백엔드 사망 판정이 아니다. 오래 걸리는 설치 작업일 수 있으므로
  설치 취소, 프로세스 종료, 자동 실패 처리, 재부팅 허용은 하지 않는다.
  기존 completed/failed 처리와 손상·누락된 상태 파일 안내가 우선한다.
- `test_gtk_progress`, `test_gtk_stale_progress` 2개 통과(0.555초).
  실제 C 헬퍼의 120초 직전/경계/이후, 갱신 회복, 시간 역행 방어를 검사했다.
  GTK 전체 소스 `-fsyntax-only -Wall -Wextra -Werror` 검사도 통과했다.
- 패키지 release를 10으로 올려 기존 release 9 산출물과 구분했다.
  release 10 패키지와 ISO는 아직 빌드하지 않았다. 실제 화면·VM 설치 시험이나
  백엔드 강제 종료 시험을 통과한 것으로 간주하지 않는다.

## 2026-09-09 GUI/TUI 로그 연결 공통화

- TUI의 직접 dup2 호출도 공통 start_install_log/restore_install_console로 교체했다.
  기존에는 dup2 오류가 무시됐고 stdout을 복사한 FD로 stderr까지 복원했다.
  이제 각 스트림을 별도로 복원하고 로그 연결 실패 시 요청을 제거해 설치를 차단한다.
- TUI 로그 경로 `/run/kiki/tui-install.log`와 ASCII UI는 유지한다.
  TUI 연결 분기 검사와 기존 실제 로그/오류 주입/init 검사를 포함해 39개 통과.
- 누적된 입력 전달 실패 처리, GUI 암호 버퍼 정리, GUI/TUI 로그 공통화를 반영할
  `kiki-stage3-v3-installer-x86_64-20260909-gtk9-logging.iso` 빌드를 요청했다.
  입력은 기존 GTK9 후보의 `/tmp/kiki-gtk9-iso-93JtCIV3` 아래 rootfs/repo/packages이며
  새 트리는 `/tmp/kiki-logging-iso-1vZMnZSS/iso-tree`에 보존한다.
  시작 시 ki2bootiso.py SHA-256은
  `edb0475d378d82cc5e8e81599a11a29788846031fefa6f29249b95fe18088956`.
  후속 빌드 종료 코드 0 및 재추출 서명/72개 패키지/initramfs/동일 rootfs 검증을
  확인했다. 완성 파일 SHA-256은
  `25df37aeac79e77f1066ca2f803aa7280b12b4f10dda2ecada0e8769a1950920`.
  아래 초기 기록의 ISO 미반영 항목 중 입력 전달/GUI 암호 정리/GUI·TUI 로그 연결은
  이 logging 후보에 반영됐다. 상세 범위는 ISO 검증 문서를 참고한다. 실기 시험은 아직이다.

## 2026-09-09 GUI 설치 백엔드 로그 — 소스 반영, ISO 미반영

- GUI의 상세 설치 stdout/stderr를 `/run/kiki/gui-install-backend.log`에 연결한다.
  새 로그 파일 생성 권한은 0600이다. 기존 `/run/kiki/gui-installer.log`는
  Cage/GTK 실행기 로그로 유지한다. 요청 파일을 로그로 복사하지 않는다.
- stdout/stderr 원본을 각각 저장하고 로그 연결 실패 시 복원한다.
  dup/open/dup2/로그 FD close 오류가 발생하면 요청 파일을 제거하고 디스크 설치를
  시작하지 않는다. 설치 후 콘솔 복원 오류는 경고로 알리며 이미 끝난 디스크 설치를
  다시 실행하거나 자동으로 재부팅하지 않는다.
- 실제 C 함수의 오류 주입 검사(정상/dup/open/부분 dup2/close/복원 실패)와
  실제 임시 파일 수집 검사를 추가했다. 후자는 0600 권한 및 stdout/stderr 내용이
  같은 파일에 기록되는 것을 확인한다. 기존 init/입력 검사 포함 38개 통과.
- 이 로그는 /run의 임시 파일이므로 영구 보존/외부 반출 기능은 아니다.
  설치 도중 저장 공간 부족에 의한 후속 로그 쓰기 실패, 모든 하위 프로그램의
  비밀정보 출력 여부, 실제 GUI 부팅·설치 시험은 아직 별도 검증이 필요하다.
- 기존 GTK9 ISO는 보존했다. 새 로그 경로는 다음 ISO 빌드부터 반영된다.

## 2026-09-09 GUI 완료 대기 중 요청 암호 버퍼 정리

- GUI 설치 요청 구조체는 설치 실행 후에도 완료/재부팅 대기 루프의 스택에
  남아 있었다. 요청 처리 분기 이후 전체 구조체를 volatile 쓰기로 지우도록 했다.
  파싱 실패 및 설치 실패에도 적용하며, 이미 있던 TUI 정리와 같은 방식이다.
- 새 검사는 정리 코드가 성공/실패 분기 밖이며 재부팅 대기 루프 이전인지 확인한다.
  기존 init 컴파일 및 입력 오류 검사를 포함해 36개가 통과했다.
  이는 메모리 덤프 전체에서 모든 암호 사본의 부재를 검증한 결과는 아니다.
- 상세 실패 로그 보존은 아직 미완료다. GUI의 설치 백엔드 출력은 콘솔로 향하며
  `/run/kiki/gui-installer.log`는 그래픽 실행기 로그다. TUI 상세 로그는
  `/run/kiki/tui-install.log`에 있으나 재부팅 후 보존되는 저장소가 아니다.
  암호를 담는 요청 파일을 진단 자료로 그대로 수집하지 않아야 한다.
- 이 변경은 기존 GTK9 ISO에 미반영이다. 실제 ISO 설치에 사용할 VM 이름,
  접속 방법과 삭제 가능한 가상 디스크 확인을 요청했다. 승인된 대상 확보 전까지
  GUI/TUI/CLI 디스크 설치 시험은 수행하지 않는다.

## 2026-09-09 설치 자식 프로세스의 입력 전달 실패 처리 — 소스 반영, ISO 미반영

- `run_chroot_program_input`이 암호 등의 입력을 전달할 때 파이프 쓰기/닫기
  결과를 무시하던 부분을 수정했다. 입력 전달이 실패하면 자식의 종료 상태가
  0이어도 실패를 반환한다. 파이프를 정리하고 자식 종료를 기다리는 동작은 유지한다.
- 자식의 표준입력 `dup2`가 실패하면 오류 코드 126으로 종료하고 설치 명령을
  실행하지 않는다. 로그에는 입력 내용이나 암호를 출력하지 않는다.
- `tools/test_chroot_input.py`는 실제 C 함수를 추출해 syscall 모의값으로
  정상 입력, pipe/fork/write/close/wait 오류, EINTR 재시도, 비정상/시그널 종료,
  입력 없는 호출, 자식 dup2 실패를 검사한다. 실제 계정/디스크를 변경하지 않는다.
- 새 검사 1개와 기존 ISO/init 회귀 검사 34개, 총 35개가 통과했다.
  실제 OS 설치에서 오류를 주입한 결과나 모든 SIGPIPE/프로세스 중단 상황의
  검증을 의미하지 않는다. 기존 GTK9 ISO에는 이 소스 변경이 아직 반영되지 않았다.

## 2026-09-09 rootfs 조립의 필수 서비스 실패 처리

- `tools/ki2build.py`의 서비스 활성화에서 유닛 누락을 경고 후 무시하던 경로를
  오류로 변경했다. 빈 파일/디렉터리/대상 루트 외부로 해석되는 유닛도 거부한다.
- 기존 링크는 같은 유닛을 가리키는 심볼릭 링크인 경우에만 재사용한다.
  일반 파일, 끊어진 링크, 다른 대상으로 연결된 링크는 보존하고 조립을 중단한다.
- 심볼릭 링크 생성 실패를 유닛 파일 복사로 대체하지 않는다. 권한/파일시스템 오류를
  호출자에게 전달하므로 조립 성공으로 숨겨지지 않는다. Alias/Also에도 적용한다.
- 새 파일시스템 회귀 검사 5개와 기존 빌더 검사 21개가 통과했다.
  `KIKI_ENABLE_TEST_ROOTFS=/tmp/kiki-gtk9-iso-93JtCIV3/rootfs`를 지정한 추가 검사에서는
  실제 GTK9 ISO 입력의 systemd 파일만 임시 복사해 server-core 요청 유닛 13개와
  Also/별칭의 활성화를 확인했다. 이 선택형 검사를 포함한 6개 검사 모두 통과했다.
- ISO 입력 rootfs 및 완성 GTK9 ISO는 수정하지 않았다. 위 조립 도구 변경은
  기존 ISO에 소급 반영되지 않으며 실제 서비스 시작/OS 부팅 시험도 아니다.
- 완전한 systemd enable 구현이나 모든 유닛 문법/경로에 대한 보안 검증은 아니다.

## 2026-09-09 GUI 진행 상태 검증 보완 — GTK 패키지/검증용 ISO 반영, 실기 미완료

- GTK는 이전에 `state=completed`만으로 완료 및 재부팅 버튼을 표시했다.
  숫자 변환 오류를 무시하고 진행률을 0~100으로 보정해 모순된 완료 기록도 수용했다.
- 진행 파일을 표시하기 전에 버전/상태/필수 숫자/중복 키/UTF-8/NUL/크기 제한을
  확인한다. 숫자에 부호·공백·문자 접미사 또는 오버플로가 있으면 거부한다.
- 완료 및 재부팅 상태는 진행률 100%와 설치 완료/전체 패키지 수의 일치를 요구한다.
  읽기 오류나 잘못된 상태에서는 완료 처리를 하지 않고 재부팅 금지 및 로그 확인을
  안내하며 정상 상태 파일을 계속 기다린다. 잘못된 파일을 설치 실패의 증거로 삼지 않는다.
- `tools/test_gtk_progress.py`: 실제 C 검증 함수를 추출해 컴파일/실행하는 검사 1개
  통과(정상 4개, 잘못된 문자열 20개, 내장 NUL/과대 입력 2개).
  GTK 전체 소스의 `-fsyntax-only -Wall -Wextra -Werror` 검사도 통과했다.
- GTK 런타임을 새 출력 경로에 재생성했다. seatd 0.9.3, wlroots 0.16.2,
  Cage 0.1.5, GTK 4.12.3 기반 708개 파일이며 생성 명령은 종료 코드 0이다.
  작업 경로는 `/tmp/kiki-gtk9-riMEyScz/work`이다. 기존 런타임은
  `build/ki2/host-graphics/rootfs-before-gtk9`에 보존하고 새 런타임을
  기존 레시피 입력 경로 `build/ki2/host-graphics/rootfs`로 옮겼다.
- GTK 릴리스 9 패키지 빌드 종료 코드 0, 키 `6fb4fc1c6b44`.
  `kiki-installer-gtk-0.1.0-9.x86_64.ki2`: 142,458,625바이트, SHA-256
  `1ce1437319929ade092379abc705a03871faab1b8666e8772966e8eab02140e8`.
  패키지를 다시 읽어 릴리스 9 및 실행 파일/CSS/dark-blue 로고의 원본 바이트
  일치를 확인했다. 실행 파일 SHA-256은
  `1277705eac64cab473627e81b594a6953d37e632f8e0c299ad0e5c8444f5c103`.
  진행 상태 C 검사 1개 및 브랜드 복사 검사 2개를 재실행해 통과했다.
- 기존 ISO는 변경하지 않았다. 새 GTK9 후보 ISO에 저장소 서명/루트 파일시스템을
  반영했고 재추출한 72개 패키지 및 initramfs/rootfs의 GTK9 바이너리를 검증했다.
  정확한 파일명·해시·검사 범위는 `docs/kiki-installer-iso-validation.ko.md`를 참고한다.
  화면 렌더링이나 GUI/TUI/CLI 실제 ISO 설치를 수행한 결과가 아니다.
- 설치 명령 대기 경로는 비정상 종료를 실패로 반환하는 것을 소스로 확인했다.
  백엔드 중단 감지, 진행 기록 쓰기 실패 처리, 실패 로그의 영구 보존은 별도 미완료다.

## 확정된 데스크톱 방향

- 운영자 선택: **GNOME**. GTK 설치기는 유지하며 GNOME은 선택형 데스크톱 프로필로 분리한다.
- 현재 GNOME Shell/Mutter/GDM 레시피와 데스크톱 패키지 그룹은 없다.
  GTK+Cage 설치기 런타임을 GNOME 데스크톱 제공 완료로 간주하지 않는다.
- 실제 패키지 및 로그인/세션 백엔드가 준비되기 전에는 설치기에서 동작하는
  GNOME 선택지인 것처럼 노출하지 않는다.
- 기존 tty1 AI / tty2 복구 셸 요구와 그래픽 로그인 VT 배치의 호환성을 검증해야 한다.

## 후속 dark-blue 변경 (위 검증용 ISO와 분리)

- GTK 헤더·창 아이콘에 v7 dark-blue 원본 PNG 연결, 버튼/패키지 강조색 조정.
- 그래픽 런타임 준비와 Makefile 설치에 원본 파일 복사 추가, 레시피 입력에
  브랜드 파일을 포함하고 GTK 릴리스 8로 변경.
- GTK `-Wall -Wextra -Werror` 컴파일과 브랜드 파일 복사/오류 처리 테스트 2개 통과.
- `kiki-installer-gtk-0.1.0-8.x86_64.ki2` 패키지 빌드 완료(142,455,810바이트).
  패키지 내부의 릴리스, GTK 실행 파일, dark-blue CSS, 원본 로고 바이트 일치 확인.
  로고 SHA-256: `c74eafa6d76d5591d205ed2a579415b4dfaeed27549b5cecfdd2b0c93dc12fa0`.
- 실제 화면, 새 저장소 서명/ISO 반영, 부팅 화면 브랜딩은 미완료.
- 후속 GRUB 변경: 원본 PNG를 런타임에 축소 표시하는 dark-blue 테마를 추가하고
  ISO 부팅 트리에 테마/로고를 복사하며 매니페스트에 해시를 기록한다.
  그래픽 모듈/테마가 없는 경우의 텍스트·직렬 콘솔 설정은 유지한다.
  Linux 미디어 빌드 테스트 25개와 `grub2-script-check` 문법 검증 통과.
  이는 테마 화면 렌더링 검증이 아니며 기존 검증용 ISO에는 아직 포함되지 않는다.
- 앞서 생성한 검증용 ISO 및 그 SHA-256은 변경하지 않았다.

## 2026-09-08

전체 목표는 설치 실패 처리, 디스크 삭제 전 미디어 검증, TUI 실행 연결,
GPT/디스크 처리 개선, ISO 실기 검증, dark-blue 브랜딩과 선택형 GUI 확장이다.
자동 테스트 통과를 ISO 설치 검증 완료로 간주하지 않는다.

### 구현 및 자동 검증

- 필수 fstab/identity, 네트워크, 로케일/AI, ld.so.conf 생성 실패 시
  설치를 중단하고 대상 파일시스템을 동기화한 뒤 마운트를 해제한다.
- GUI뿐 아니라 CLI/무인 설치 경로에서도 부트로더 설치 실패 이후
  성공 메시지를 출력하지 않는다.
- ISO 패키지 복사 시 파일명, 중복 항목, SHA-256, 크기 및 일반 파일 여부를
  검사한다. 원본과 복사본 모두 크기/해시가 일치해야 한다.
- 패키지 누락/손상을 기록만 하고 계속하던 동작을 오류 종료로 변경했다.
- Rocky-9 WSL에서 `python3 -B tools/test_ki2bootiso.py`: 19개 통과.
  실패 처리 테스트는 생성 C 코드의 제어 흐름 검사이며 VM 오류 주입 테스트가 아니다.

### 초기 점검 당시 남은 작업 (아래 후속 결과 참조)

- 부팅 후 파티션 변경 전 저장소 신뢰 검증 및 모든 설치 패키지 검사 연결.
  빌드 시 해시 일치만으로 저장소 서명이나 ISO 진위를 검증했다고 볼 수 없다.
- 설치 실패 로그 보존, 설치 계획 저장/서비스 활성화/동기화 실패 처리 보강.
- TUI 설치 실행 및 공통 진행 이벤트 연결.
- GPT와 대용량/섹터 크기 처리 개선.
- 변경된 코드로 새 ISO 빌드 및 ISO 파일명/SHA-256/커밋 고정.
- GUI/TUI/CLI 각각의 실제 설치, 폴백, 실패 및 설치 후 부팅 검증.
- dark-blue 로고 패키징 및 화면 적용, 선택형 데스크톱 GUI.

현재 변경에 대한 ISO 빌드와 실기 테스트는 아직 수행하지 않았다.

### 미디어 검증 연결 및 런타임 시험

- `--media-public-key`로 지정한 Ed25519 공개키와 Python/OpenSSL 기반 검증기를
  initramfs에 포함한다. Stage 3 빌드 파이프라인은 서명 키에 대응하는 공개키를 전달한다.
- guided 설치의 파티션/포맷 호출 전에 `ki2media.py`를 실행하며 실패하면 반환한다.
  guided 수동 설치의 파티션 명령/셸을 열기 전에도 검증하며 포맷 전에 재검사한다.
  독립 실행 파티션 편집기와 legacy 이미지 쓰기 경로는 추가 검토 대상이다.
- 실제 KIKI 패키지를 조립한 임시 chroot에서 정상 서명 미디어 통과,
  패키지 손상/누락, 인덱스 변경 및 메타데이터 변조의 오류 종료를 확인했다.
- 재현: Linux root로 `KIKI_TEST_MEDIA_RUNTIME=1 python3 -B tools/test_ki2media_runtime.py`.
  이 시험은 임시 파일만 사용하며 VM 디스크나 블록 장치를 연결하지 않는다.
- 기존 접두사 검색이 python 대신 python-setuptools를 선택하는 문제를 수정했고,
  릴리스 번호 숫자 비교 및 `/usr/lib` 런타임 라이브러리 연결을 추가했다.
- 점검 당시 dist 저장소의 서명 메타데이터와 실제 인덱스가 달랐다.
  이후 저장소를 재생성·재서명했으며 공개키 검증이 통과했다.

위 결과는 ISO 부팅 후 설치 시험이나 실제 디스크 무변경 증명이 아니다.

### TUI 실행 연결 (ISO 실기 미검증)

- 전체 화면 TUI의 설치 시작 및 `:install`/`:start`/`:10`은 암호(비표시),
  암호 확인과 `INSTALL <disk>` 입력 후 공통 요청 IPC를 전송한다.
- Stage-1은 TUI를 유지한 채 설치를 실행하고 원문 로그를
  `/run/kiki/tui-install.log`에 기록한다. 진행률과 패키지 완료 개수는
  GUI와 동일한 상태 파일에서 읽는다.
- 성공 후 r 키는 재부팅 확인, q 키는 CLI 복귀다. 실패 시 재부팅 확인을 제공하지 않는다.
- 요청 파일은 0600으로 원자적으로 전달하며 암호를 계획 YAML에 기록하지 않는다.
- `kiki-installer-tui` 레시피 릴리스를 9로 올리고 해당 패키지 빌드를 완료했다.
  이 변경을 포함하는 ISO 빌드와 실기 설치 검증은 별도다.
- Go 단위 테스트에서 요청 검증, 암호 비표시, 파일 권한 및 진행 상태 범위를 확인했다.
  추가 PTY 시험에서 실제 키 입력, 요청 권한과 암호 비노출, 성공 시 재부팅 요청,
  실패 시 CLI 복귀를 확인했다. 진행 상태는 모의 입력이므로 실제 백엔드 설치
  통합과 ISO 설치는 별도 검증이 필요하다.

### 2026-09-08 재확인

- Windows 실제 저장소 경로는 `E:\dev\KIKI-OS`다.
  현재 브랜치는 `feat/stage-3-kiki-platform`이며 수정 사항은 미커밋 상태다.
- 미디어 빌드 테스트 23개, 서명/손상 테스트 2개, GPT 테스트 3개 및 TUI Go 테스트 통과.
- KIKI 프로젝트 Go 검증도 통과했다:
  `GOCACHE=/tmp/kiki-go-cache go test -mod=vendor ./cmd/... ./internal/... ./deploy/... ./installer/...`.
  단순 `./...` 실행은 `build/ki2/.../gcc-11.5.0`에 풀린 외부 GCC 테스트까지
  탐색해 중복 main/CGO 의존성 등의 오류로 실패했다. 프로젝트 테스트 결과와
  이 외부 소스 빌드 캐시 오류를 구분한다. 외부 테스트 파일은 변경하지 않았다.
- 필수 설치 계획의 누락/저장 실패와 최종 ESP/Root 마운트 해제 실패 시
  설치 성공을 표시하지 않는다. 컴파일한 C 테스트에서 각 마운트 해제 실패 조합을
  주입해 반환값을 확인했으며 이는 실제 디스크 I/O 오류 시험은 아니다.
- initramfs에서 sfdisk와 호스트 GTK 런타임의 libblkid 버전 충돌을 수정했다.
  조립한 chroot의 sfdisk 실행과 임시 sparse 이미지 GPT 검증을 확인했다.
- GUI/TUI/CLI ISO 부팅·실제 설치 및 설치 후 부팅은 여전히 미완료다.
- 최신 C 백엔드로 설치용 initramfs 생성 완료. 해당 chroot에서 미디어 검증기,
  GPT 도구, Cage 및 GTK 도움말 로딩을 확인했다. Cage 도움말은 종료값 1을
  반환하며 GTK 도움말은 종료값 0이다. 화면 렌더링 시험은 수행하지 않았다.
- Windows Hyper-V 모듈은 있으나 `Get-VM` 조회가 접근 거부로 실패했다.
  실제 VM 테스트에는 접근 권한과 사용 가능한 폐기형 테스트 VM 지정이 필요하다.
- 새 rootfs는 기존 산출물 보존을 위해 `dist/rootfs/validation-20260908`에
  조립 완료했다. TUI 0.1.0-9와 GTK 0.1.0-7이 포함된다.
  initramfs의 컴파일 입력 C 소스와 현재 `INIT_C`의 일치도 확인했다.
- 검증용 ISO 출력 경로는
  `dist/iso/validation/kiki-stage3-v3-installer-x86_64-20260908-gpt-tui-validation.iso`다.
  생성 완료: 8,118,009,856바이트.
  SHA-256: `9b8237fe801391d36ad45d8ea8a6a8e796d2f4279c51d093e4a0f71fb4fc304e`.
  조립된 미디어 트리의 Ed25519 서명, 인덱스 및 68개 패키지 검증 통과.
  Windows 7-Zip으로 완성 ISO에서 재추출한 미디어의 Ed25519 서명, 인덱스,
  68개 패키지 크기/해시 검증도 통과했다. WSL 재읽기 명령은 연결 오류로
  실행되지 않아 Windows Python과 설치된 Git OpenSSL을 사용했다.
  ISO의 initramfs 내부 검증기 4개와 신뢰 공개키가 현재 원본과 바이트 단위로
  일치하고 TUI/GTK/Cage/sfdisk, 새 마운트 실패 메시지가 포함된 것을 확인했다.
  GRUB의 GUI 기본값 및 GUI/TUI/CLI 항목 순서를 확인했다.
  VM 부팅/설치는 여전히 미실행이다. 이 ISO는 실기 검증용이며 릴리스 승인본이 아니다.
  기존 ISO는 변경하지 않았고 별도 VHDX 생성 및 VM 변경은 수행하지 않았다.

### 2026-09-08 dark-blue ISO 빌드 및 재읽기 완료

- 산출물: `dist/iso/brand-validation/kiki-stage3-v3-installer-x86_64-20260908-dark-blue.iso`
- 크기 8,124,493,824바이트, SHA-256:
  `d3140c419c90cc85ac009d9136630f660a16ed81a6dab31a979f7252279adc8c`.
- GTK 0.1.0-8과 GRUB/GTK dark-blue 로고 포함. 이전 후보는 보존했다.
- Windows 7-Zip 재추출 후 Ed25519 서명/인덱스/68개 패키지 검증 통과.
- GRUB 테마/로고 및 initramfs GTK 로고, 검증기 4개와 공개키의 원본 일치 확인.
- GNOME 기반 dconf 런타임 테스트 2개 통과. GNOME 데스크톱은 ISO에 미포함.
- 실제 VM 부팅, 로고 렌더링, GUI/TUI/CLI 설치는 미검증. 릴리스 승인본이 아니다.

### 필수 서비스 링크 실패 판정 추가 (dark-blue ISO 생성 이후)

- 기본/선택된 Kubernetes 서비스의 링크 생성 실패를 필수 구성 실패 경로로 연결했다.
  권한 거부, 공간 부족, 충돌 파일/링크를 무시하고 설치 성공을 표시하지 않는다.
- 이미 같은 대상을 가리키는 절대/상대 링크는 인정한다. 기존 rootfs의
  `../../../../usr/lib/systemd/system/...` 및 `../sshd.service` 형식을 확인했다.
  다른 대상을 가리키는 링크는 임의 삭제/덮어쓰기 없이 실패로 남긴다.
- ISO 도구 테스트 26개 통과: 링크 오류 주입, 상대 경로 비교, 설치기 C 컴파일 포함.
- 이 변경은 위 SHA-256의 dark-blue ISO 생성 이후 수정이며 아직 해당 ISO에 없다.
- 후속 보완: 링크를 만들기 전에 설치 대상 chroot에서 단위 파일의 일반 파일 여부,
  크기 및 읽기 가능 여부를 검사한다. 절대 별칭이 라이브 설치기 루트로 해석되지 않는다.
  Kubernetes의 선택된 런타임, kubelet, chronyd 누락 시 건너뛰기를 제거했다.
- 회귀 테스트 27개 통과. AI off/local/remote 및 CRI-O/containerd 각각에서
  모든 필수 링크 실패를 하나씩 주입해 실패 전파를 확인했다.
- 기존 조립 rootfs의 기본 서비스 단위 14개를 실제 chroot 안에서 읽기 전용 검사:
  모두 통과. 의도적으로 존재하지 않는 단위 경로는 실패로 반환됐다.
- 단위 파일 내용의 의미적 유효성, 서비스 실제 시작 및 VM 설치는 아직 미검증이다.

### 공통 파일 I/O 실패 판정 (dark-blue ISO 생성 이후)

- 텍스트 쓰기/추가 및 파일 복사가 쓰기, fsync, close 실패를 반환하도록 수정했다.
  권한 지정 함수는 chmod 실패도 반환한다. 짧은 쓰기는 끝까지 처리하고
  read/write/fsync의 EINTR는 재시도한다. Linux close는 재시도하지 않는다.
- 대상 루트의 커널/initramfs 복사 결과를 무시하던 경로도 설치 실패로 연결했다.
- 회귀 테스트 28개 통과. C 오류 주입은 4개 파일 연산의 open/write/read/fsync/
  chmod/close 실패, 0바이트 쓰기, 짧은 쓰기, EINTR 조합을 검사한다.
- 이 테스트는 실제 디스크 고장 시험이 아니며, 모든 호출자의 반환값 확인이
  끝났다는 뜻도 아니다. 기존 dark-blue ISO에 이번 변경은 포함되지 않는다.

### sudoers 및 시간대 오류 처리

- 위 서비스/I/O/시간대 수정을 포함하는 후속 ISO 빌드 완료:
  `dist/iso/hardening-validation/kiki-stage3-v3-installer-x86_64-20260908-io-units.iso`.
  `tools/ki2bootiso.py` 입력 SHA-256:
  `239122250706f02560b97733cc7b1a245720fbcde0e63d46a1a83a4d0584d6d0`.
  기존 검증 rootfs를 사용하고 설치기 initramfs는 현재 소스로 다시 생성한다.
  산출물 크기 8,124,499,968바이트, SHA-256:
  `ef7ee269d5c3be1ed90ef7819de736ce22f0da676413c3d5f650d12352ad845d`.
  완성 ISO 재추출 후 Ed25519 서명/인덱스/68개 패키지 검증 통과.
  빌드 소스 해시 불변, init의 새 실패 메시지, 검증 도구 4개/공개키,
  GTK/GRUB 로고 및 테마의 원본 일치 확인. 기존 ISO는 보존했다.
  GNOME 데스크톱 미포함. GUI/TUI/CLI 실제 VM 설치는 계속 미실행이다.

- 후속 구성 검사: sudoers 쓰기와 0440 권한 설정 실패를 함께 반환하도록 변경했다.
  시간대는 설치 대상 chroot에서 파일 존재/크기/읽기 가능 여부를 확인한 뒤
  `ln -sfnT`로 기존 localtime을 교체한다. 실패하면 필수 구성 실패로 종료한다.
- 회귀 테스트 29개 통과. 시간대 테스트는 실제 스크립트의 목적지만 임시 경로로
  바꾸어 기존 링크 교체, 누락/빈 파일 시 기존 링크 보존, 디렉터리 충돌 거부를 확인한다.
  호스트 `/etc/localtime`은 변경하지 않았다. 실제 VM 시간대 적용 시험은 아니다.
  이 후속 변경도 이전 dark-blue ISO에는 포함되지 않는다.

### GUI/TUI 요청 필드 경계 검사

- 후속 파일 단위 검사: 요청 전용 읽기 함수는 EOF까지 읽고 16KiB 버퍼의
  최대 텍스트 길이(16,383바이트)를 넘거나 NUL이 포함되면 전체 요청을 거부한다.
  부분 읽기와 EINTR는 이어서 처리하며 읽기/close 실패도 거부한다.
  일반 패키지 인덱스 읽기 함수의 기존 동작은 이번 수정 범위에 포함하지 않았다.
- 요청 파일의 암호 제거용 truncate/open/close 실패 시 설치를 진행하지 않는다.
  읽기 실패 버퍼와 파싱 실패 시 요청 구조체·원문 버퍼는 volatile 쓰기로 지운다.
  디스크 상의 실패 요청 파일이 모든 경로에서 영구 삭제됨을 입증하는 검사는 아니다.
- 설치기 테스트 32개 통과. 새 C 오류 주입 검사는 허용 최대 길이, 최대 길이 초과,
  NUL, 빈 요청, 부분 읽기, EINTR, open/read/close 실패 및 버퍼 지우기를 확인했다.
  전체 설치기 C 컴파일도 통과했다. 실제 GUI/TUI 디스크 설치 테스트는 아니다.
- 이 후속 수정은 `20260908-current.iso` 생성 이후 변경으로 해당 ISO에는 미포함이다.

- 공통 요청 파서가 필드 길이 초과와 같은 키의 중복을 오류로 반환한다.
  값을 잘라 다른 디스크/설정으로 해석하지 않도록 상위 요청 검증에 연결했다.
- 패키지 이름 길이 또는 목록 최대 개수 초과도 요청 실패로 처리한다.
- ISO 도구 회귀 테스트 31개 통과. C 파서 경계값/중복/빈 값/누락 검사를 포함한다.
- TUI 시작 시 이전 진행 파일을 지우는 코드가 있음을 확인했다. 진행 통신 중단의
  실제 백엔드 종료 시나리오 검증까지 완료한 것은 아니다.
- 후속 TUI 보완: 진행 정보가 2분 이상 바뀌지 않거나 읽기/파싱에 실패하면
  설치가 계속 실행 중일 수 있음을 안내하고 복구 셸의 로그 확인을 요청한다.
  시간 초과만으로 실패를 확정하거나 설치 취소·자동 재부팅하지 않는다.
  새 정상 진행 정보가 오면 안내를 해제한다. 실패한 프로세스를 감지하는 기능은 아니다.
- 완료 상태는 진행률 100% 및 설치/전체 패키지 수 일치를 요구한다.
  TUI Go 테스트 통과. 경고/복구와 불일치 완료 거부의 로직 테스트이며 실제 화면·VM
  시험은 아니다. TUI 패키지 릴리스는 10으로 올렸다.
- 이번 요청 파서 변경은 io-units ISO 생성 이후이며 해당 ISO에는 포함되지 않는다.

### 설치 후 부팅 브랜딩 — 코드 반영, ISO/실기 미완료

수정 전 `write_installed_boot_config()`가 생성하는 ESP의 `kiki-installed.cfg`에는
gfxterm/콘솔 전환은 있지만 dark-blue 로고 테마 설정이 없다.
`install_uefi_boot_files()`도 폰트·커널·initramfs·EFI 실행 파일을 복사하며,
ISO의 `/boot/grub/kiki/` 테마와 로고는 설치 대상 ESP로 전달하지 않는다.
후속 수정으로 `install_target_boot_branding()`이 로고와 테마를 ESP에 복사하고,
설치 후 설정에서 파일 존재 및 gfxmenu/png 모듈 로딩 조건으로 테마를 적용한다.
UEFI fallback 빌드 모듈에도 gfxmenu/png를 추가했다. 기존 콘솔 fallback은 유지했다.
공통 테마 제목은 설치 후에도 사용할 수 있도록 `KIKI OS`로 통일했고 PNG 원본은
변경하지 않았다. 과거 비브랜딩 미디어는 두 파일 모두 없으면 계속 사용할 수 있다.
하나만 있거나 복사에 실패하면 설치 성공을 반환하지 않는다.

설치기 테스트 33개 통과: 새 C 오류 주입 검사에서 12가지 파일 존재/복사 실패
조합과 경로를 확인했고 전체 INIT_C 컴파일도 통과했다. 모의 파일 작업 검사이며
실제 ESP 설치 및 GRUB 렌더링 검사는 아니다. 이 변경은 기존 request-guard ISO에
미포함이다. 새 ISO 빌드와 실제 화면 검증이 남아 있다.

gfxmenu/png를 포함한 UEFI fallback 실행 파일은 실제 빌드에 성공했다.
`/tmp/kiki-branded-uefi-5q9tcu7k/BOOTX64.EFI`, 15,642,624바이트,
SHA-256 `a5778436b0a626707578b74fc04e1c54122957f11c0dc5dface7d9698378e6d4`.
임시 산출물이며 VM에서 실행하거나 기존 ISO/ESP에 덮어쓰지 않았다.

후속 검사에서는 실제 `write_installed_boot_config()`와 `append_string()` C 함수를
실행해 얻은 설정을 `grub2-script-check` 표준 입력으로 전달했다. 구문 검사를
통과했고 두 부팅 항목, 대상 루트 경로, 테마 및 콘솔 경로를 확인했다.
이 검사를 추가한 설치기 회귀 테스트는 34개 통과했다. 디렉터리/파일 쓰기는
모의 처리했으며 GRUB 그래픽 출력이나 펌웨어 부팅까지 검증한 결과는 아니다.

### GPT 전환 (실제 디스크 미검증)

- 자동 설치는 직접 MBR 엔트리를 쓰는 대신 `ki2disk.py`와 sfdisk로 GPT를 생성한다.
  TUI 및 Stage-1이 생성하는 계획서 기본값도 GPT다.
- 논리 섹터 크기와 바이트 용량을 ioctl로 읽고 1MiB 경계에 ESP/Swap/Root를 배치한다.
  끝부분에는 백업 GPT를 위한 공간을 남긴다. Swap off는 ESP/Root 두 파티션이다.
- 일반 파일·파티션 장치·마운트 중인 대상·활성 Swap·device-mapper/RAID holder가
  있는 장치는 실제 작성 경로에서 거부한다. sfdisk 기본 사용 중 검사도 유지한다.
- `python3 -B tools/test_ki2disk.py`: 3개 통과. 512/4096바이트 섹터 계산,
  일반 파일 거부, 임시 8GiB/3TiB sparse 이미지의 GPT 생성 및 sfdisk 검증 포함.
- 512바이트 섹터 이미지에서 주/백업 GPT 헤더와 파티션 타입을 확인했다.
  4Kn 실제 장치, Hyper-V 부팅 및 설치는 아직 미검증이다.
