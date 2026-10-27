# KIKI 데스크톱 도구 — 미완성 소스

**상태: 개발 중(WIP). KIKI 네이티브 패키지 빌드·배포 및 실제 운영 환경 검증은 완료하지 않았다.**
이 디렉터리는 구현 검토와 후속 개발을 위해 소스에 포함한다. 소스 등록을
기존 설치기·패키지·ISO의 교체나 운영용 도구의 완성으로 취급하지 않는다.

## 현재 포함된 기능

- `main.c`: GTK4 파일 탐색·텍스트 미리보기와 사용자별 데스크톱 설정 초안.
- `Makefile`: GTK4 개발 환경에서의 독립 빌드·설치 진입점.
- `org.kiki.Files.desktop`, `org.kiki.Settings.desktop`: 두 화면의 실행 항목.
- `org.kiki.Terminal.desktop`: 외부 GTK4 VTE 실행 파일을 여는 실행 항목.
  자체 터미널 구현이나 VTE 바이너리를 포함하지 않는다.
- `ui_test.c`, `../../tools/test_desktop_tools_ui.py`: 설정 저장·폴더 탐색·정렬·
  텍스트 미리보기 검증을 위한 테스트 소스. 테스트 소스의 존재는 실행 통과를 뜻하지 않는다.

## 남은 의존성과 패키징

이 커밋에는 이 도구의 KI2 패키지 명세를 등록하지 않는다.
GTK4·VTE 공급 패키지와 의존성을 확정한 뒤 별도 명세로
등록해야 한다. 현재 Git 명세만으로 이 도구의 네이티브 패키지 빌드가 가능하다고
표시하지 않는다.

- 빌드: C 컴파일러, Make, pkg-config, `gtk4` 개발 헤더·라이브러리.
  사용할 GTK4 최소 버전과 KIKI sysroot 연동은 추가 검증이 필요하다.
- 설정: 사용자 D-Bus·GSettings 백엔드와 `gsettings-desktop-schemas`의
  `org.gnome.desktop.interface`, `org.gnome.desktop.input-sources` 스키마.
- 터미널: `/usr/bin/vte-2.91-gtk4`, `/bin/bash` 실행 파일과 세션 환경.
- 한국어 입력: IBus·한글 입력 엔진과 GNOME 세션 연동 검증.
- 네트워크 설정: VTE에서 `sudo /usr/bin/kiki-netconfig`를 실행하는 초안이다.
  인증·권한 정책과 실패 시 사용자 안내는 실제 대상 환경에서 검증해야 한다.
  이 소스 등록으로 sudo·Polkit 권한이나 시스템 설정을 변경하지 않는다.
- UI 테스트: Linux, GTK4 개발 패키지, Xvfb와 해당 GSettings 스키마가 필요하다.
  테스트가 건너뛰어지면 통과로 간주하지 않는다. Wayland·GDM·실제 사용자 세션,
  터미널·네트워크 인증의 종단 간 검증은 별도로 수행해야 한다.

기존 GNOME 애플리케이션은 계속 사용할 수 있어야 한다. 이 초안을 Nautilus,
GNOME 설정, 터미널의 운영용 대체품으로 자동 지정하거나 기존 앱을 제거하지 않는다.
