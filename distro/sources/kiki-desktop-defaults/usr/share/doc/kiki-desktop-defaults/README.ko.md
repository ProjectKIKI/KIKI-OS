GNOME 기본 구성

- 즐겨찾기: GNOME Console, 파일(Nautilus), GNOME 설정(Control Center).
- 폴더의 기본 실행 앱은 Nautilus이며 Console은 Bash 로그인 셸을 사용합니다.
- Super+Space로 영어/한국어 입력기를 선택합니다.
- 한국어 입력기에서 한/영 키 또는 Shift+Space로 한글 조합을 전환합니다.
- GNOME 설정에서 테마·배경·입력 언어·키보드·마우스·전원·네트워크 등을 관리합니다.
- Nautilus에서 폴더 탐색, 검색, 복사, 이동, 이름 변경과 휴지통을 사용합니다.
- GNOME 프로파일의 네트워크는 NetworkManager와 systemd-resolved를 사용합니다.
  서버 프로파일은 기존 systemd-networkd 구성을 유지합니다.
- 배경은 현재 이미지 디코더에서 지원하는 GNOME SVG·PNG 배경을 제공합니다.

KIKI 설정·파일 초안은 이 프로파일의 기본 앱으로 설치하지 않습니다.
오디오, 화면 공유, Xwayland와 실제 하드웨어 GPU 지원은 별도 검증 대상입니다.
