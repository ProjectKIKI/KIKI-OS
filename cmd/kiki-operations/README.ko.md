# KIKI 운영

GNOME과 기존 앱을 유지하면서 자체 화면·설정을 제공하는 GTK4 운영 앱이다.
UI는 Libadwaita 위젯·GNOME Shell 확장·전용 GNOME 세션 없이 동작한다.
기존 관리자 재사용을 위한 `kiki-admin` 의존성 때문에 Libadwaita 런타임은 함께 유지한다.

현재 1~4단계 범위는 다음과 같다.

- 픽셀 아이콘·각진 카드·탐색·라이트/다크와 GTK 고대비를 존중하는 앱 전용 스타일.
- CPU·메모리·루트 파일시스템·실패 서비스·systemd 서비스 목록의 실제 읽기 전용 조회.
- 서비스 검색·실패 필터·상태 선택. 3초 갱신, 중복 조회 방지, 시간 제한과 닫기 시 취소.
- 기존 `kiki-adminctl snapshot`의 요약 재사용. 패키지 조회와 실시간 폴링 분리.
- 기존 관리자 진단 화면 열기. 기본 관리자·KI2·Polkit 정책을 변경하지 않는다.
- 선택한 서비스의 이번 부팅 최근 200줄 사용자 로그 조회와 접근 제한 안내.
- 기존 관리자의 조회 계획·토큰과 `pkexec kiki-admin-helper system-logs`를 그대로 사용하는 시스템 로그 인증 조회.
- 서비스 상태 또는 사용자 로그의 고정 명령 미리보기와 GNOME Console 실행. 일반 사용자 권한이며 임의 명령·셸 입력 API는 제공하지 않는다.
- 서비스 변경 시 이전 로그·승인 창·Console 계획을 초기화하고 이전 서비스의 늦은 응답을 버린다.
- incident-ai 문맥 미리보기·편집, 선택적 로그 포함, 패턴 마스킹, 1,000 UTF-16 단위 제한.
- 검토한 문맥을 복사하고 `https://incident-ai.lab.terminal-lab.kr/#ask`를 기본 HTTPS 브라우저로 연다.
  웹 질문란에는 사용자가 붙여넣고, 정상 로그인 후 전송한다. 자동 업로드나 AI 질의 실행은 하지 않는다.

`kiki-operationsctl runtime`은 `kiki-operations-v1` JSON을 반환한다. 조회 불가 항목은
null과 warnings로 표시하며 정상 0으로 간주하지 않는다. `summary`는 기존 관리자 요약을
낮은 빈도로 호출한다. `logs UNIT`, `log-plan UNIT`, `terminal-plan UNIT status|logs`도
같은 스키마를 사용한다. 시스템 로그의 실제 권한 작업은 기존 관리자 helper에만 남긴다.
Console은 고정 래퍼 `/usr/libexec/kiki-operations-console`을 통해 셸 없이 argv로 실행하며,
조회 결과와 종료 코드를 표시하고 Enter까지 유지한다. 이후 남은 Console 창은 닫기 버튼으로 닫는다.

설정은 `$XDG_CONFIG_HOME/kiki-operations/settings.ini`(기본 `~/.config/kiki-operations/settings.ini`)에
저장하며 GNOME dconf DB를 변경하지 않는다. 키파일의 `preferences` 그룹과 독립 GSettings
스키마 `org.kiki.Operations`를 사용한다. 테마와 실패 필터를 저장한다.

incident-ai 로그 포함은 처음에 꺼져 있다. 호스트·서비스·조회 범위·시각을 확인하고 필요한 로그만 포함한다.
마스킹은 완전하지 않으므로 전송 전 직접 검토한다. URL에는 로그를 넣지 않는다.
서비스 변경·제거 시 앱 초안과 앱이 소유한 클립보드는 지운다. 웹에 이미 붙여넣은 내용은 별도 스냅샷이다.
서비스 변경 승인과 로그인 자동 실행은 후속 범위다. 사용자 로그가 비어 있어도 시스템 전체 로그가 없다고 표시하지 않는다.
별도 데스크톱 세션·compositor·패널 구현이나 성능 경량화 완료를 뜻하지 않는다.

네이티브 빌드는 기존 KIKI SDK와 실제 설치된 GA를 고정한
`distro/manifests/kiki-operations-20261107-baseline.json`을 명시적으로 사용한다.
기존 11월 6일 잠금 파일과 빌더의 기본 경로는 보존한다.
`tools/build_kiki_operations.py`는 새 경로에만 후보를 만들며, 기존 221개 패키지를 교체하지 않는
시험용 얇은 오버레이를 생성한다. 이 오버레이는 새 ISO 공급 저장소가 아니다.

검증은 `tools/test_kiki_operations.py`의 데이터 오류·경계 시험과 `ui_test.c`의 실제 GTK 화면 시험으로
분리한다. GTK 시험 설정은 지정한 출력 디렉터리 아래에 저장해 실제 사용자 설정과 구분한다.
검증 기록은 `docs/kiki-operations-stage12-20261106.ko.md`와
`docs/kiki-operations-stage3-20261107.ko.md`, `docs/kiki-operations-stage4-20261107.ko.md`를 참고한다.

4단계 후보의 Firefox ESR은 Mozilla 공식 바이너리다. 브라우저용 X11 클라이언트 라이브러리와
별도 GTK3·Cairo·Epoxy는 소스로 빌드한다. 기존 공용 GTK를 교체하지 않고 브라우저 프로세스에만
`/usr/libexec/kiki-incident-browser/153.6.0esr/compat`를 적용한다. 브라우저가 없던 후보 VM에
전용 프로필과 HTTPS 기본 연결을 추가했다. GNOME 기본 세션은 유지한다.
