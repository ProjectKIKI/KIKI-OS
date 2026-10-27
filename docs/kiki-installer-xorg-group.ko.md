# GUI 인스톨러 Xorg 런타임 선택

기본 설치 프로파일은 그대로 유지하고, 고급 프로파일 옵션에
`Xorg runtime (optional; no LightDM or desktop)` 선택 메뉴를 추가했다.
선택하면 `xorg-runtime` 그룹이 설치 계획에 들어가며,
`kiki-x11-runtime` 패키지를 선택한다. LightDM, 데스크톱, 기본
그래픽 부팅 타깃은 자동으로 활성화하지 않는다.

패키지 그룹 카탈로그는 `ki2ctl`의 `package-groups.json`이며,
TUI 계획 생성기의 허용 그룹과 패키지 선택 로직도 같은 ID를 사용한다.
GUI가 생성한 계획의 패키지 목록은 설치 백엔드가 읽어 실제 설치에 사용한다.
선택한 패키지가 설치 미디어에 없으면 설치 전 확인에서 실패해야 한다.

Go TUI/GUI 단위 테스트, GTK 태그 실제 빌드, ki2ctl 테스트를 통과했다.
기존 r20 ISO에는 이 변경이 들어 있지 않다. 다음 릴리스에서는
`ki2ctl` 0.1.0-13, `kiki-installer-tui` 0.1.0-14,
`kiki-installer-gtk` 0.1.0-17을 함께 패키징하고 ISO에서 설치 검증한다.
