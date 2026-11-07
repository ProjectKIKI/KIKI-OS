# Paper Pixel UI/UX 보완 후보 r6

2026-11-05. 배경 잘림·관리자 창 복귀와 GNOME Shell 내부 스타일을 별도 후보에서 보완한 기록이다.
현재 후보는 `paper-pixel-20261105-r6`, 세션 패키지는 `kiki-session-gnome-ops 0.1.0-6`이다.
이전 r3 검증 기록은 [1단계 기록](kiki-paper-pixel-stage1.ko.md)에 보존한다.

## 구현 내용

| 항목 | 수정과 경계 |
| --- | --- |
| 배경 잘림 | KIKI 기본 SVG의 기본 크기 정책을 `scaled`로 지정하고, 남는 영역은 같은 배경색으로 채운다. 1024×768에서 네 모서리 장식 전체를 확인했다. 사용자 지정 배경·명시적인 크기 정책은 유지한다. |
| 관리자 창 복귀 | 실제 운영 메뉴 이벤트의 시각으로 `Shell.App.activate_full()`을 호출하고 시작 알림 문맥을 전달한다. 최소화된 기존 창의 복귀와 새 창 실행을 검증했다. Wayland 포커스 정책은 완화하지 않았다. |
| 셸 공통 스타일 | 전용 세션의 `uiGroup` 아래로 스타일을 한정했다. 상단 패널, 운영 메뉴, 빠른 설정 내부, 달력·일정 카드, 검색, 도크, 앱 목록, 알림, 인증 대화상자에 Paper 색·테두리·작은 모서리·단색 그림자를 적용한다. OSD·앱 전환기에도 같은 규칙을 정의했다. |
| 라이트·다크 | `tokens.json`에서 GTK 관리자 CSS·Shell CSS·배경 채움 색을 생성한다. `ki2pixeltheme.py --check`로 생성물의 일치를 검사한다. 빠른 설정의 실제 어두운 스타일 전환과 최종 양쪽 달력 화면을 확인했다. |
| 접근성 | 고대비에서는 전용 색상 재정의를 해제하고 GNOME 고대비 색을 존중한다. 글자 125%와 고대비를 확인한 후 저장된 값으로 복구했다. |
| 기존 환경 | 일반 GNOME, GDM·잠금 화면, 기존 GNOME 앱 내부 디자인은 유지한다. 기본 글꼴·아이콘·커서를 일괄 교체하지 않는다. |

수정 소스는 `desktop/gnome/kiki-ops/`, `assets/desktop/paper-pixel/`,
`tools/ki2pixeltheme.py`, 별도 운영 프로필과 세션 레시피다.
기존 네이티브 관리자 `0.1.0-7`은 SHA가 같은 산출물을 재사용했다.
최종 설치에서는 221개 중 세션 패키지 하나만 바뀌며 나머지 220개는 유지된다.

## 후보와 보존

- 새 독립 Hyper-V VM: **`kiki-paper-pixel-candidate-r4-20261105`**. VM 이름의 r4는 생성 시점이며, 설치된 최종 패키지는 r6이다.
- 이전 r3 VM과 원본 GA VM은 정지한 채 보존한다. 새 VM 디스크는 부모가 없는 독립 VHDX다.
- 기존 설치기·패키지·ISO 4,039개 보호 파일의 SHA를 검사한다. 원본 GA 디스크 체인 3개와 이전 r3 후보 디스크도 SHA가 같다.
- 새 ISO 생성·새 설치 검증은 이번 작업 범위에 포함하지 않았다. 일반 GNOME 프로필의 고정 후보도 변경하지 않았다.
- 호스트 화면·마우스·키보드를 조작하지 않았다. SSH와 게스트 접근성, VMMS의 가상 키 입력·프레임 읽기만 사용했다.

이전 오른쪽 VMConnect 창은 보존한 r3 VM을 가리킬 수 있다. 새 VM을 볼 때는 위 이름을 선택해야 한다.
호스트 창을 자동으로 열거나 전환하지 않았다.

## 실제 검증

| 검증 | 결과와 증거 |
| --- | --- |
| GDM 암호 로그인·재부팅 | 새 boot ID에서 Wayland, `--mode=kiki-ops`, 확장 v5 ACTIVE, 관리자 자동 실행 active. `r6-runtime-reboot.json` |
| 잠금과 해제 | 기존 GNOME 잠금 화면 유지, 정상 암호로 해제 후 확장 ACTIVE와 관리자 유지. `r6-unlock-validation.json`, `r6-runtime-final.json` |
| 관리자 최소화 → 실제 메뉴 → 복귀 | 최종 r6에서 보조 Alt+Tab 없이 전면 복귀. `r6-minimize.log`, `r6-restore-item.log`, `r6-admin-restored.png` |
| 배경·내부 스타일 | 전체 배경, 라이트·다크 달력, 빠른 설정, 검색·앱 목록·도크, 정상 알림 배너와 Polkit 화면 확인. PNG 증거 참조 |
| 실제 권한 작업 | 실패하도록 만든 무해한 후보 시험 서비스를 선택하고 복구 계획 → 정상 Polkit 암호 인증 → helper 실행 → active/success 확인. 감사 로그 확인 후 시험 파일과 서비스를 제거. `r6-recovery-validation.json` |
| 일반 GNOME 복귀 | `--mode=user`, 픽셀 확장 비활성, 전용 환경 변수 없음, 전용 자동 실행 inactive. 기존 Nautilus·Console·관리자 실행 확인. `r6-runtime-standard.json`, `r6-standard-apps-check.json` |
| GNOME 설정 보존 | 일반 세션 파일 3개와 사용자 `dconf/user` SHA가 최초 값과 일치. `normal-before.json`, `r6-normal-after.json` |
| 설치 파일 | 관리자 7개·세션 22개, 총 29개 일반 파일의 SHA와 권한 일치. `r6-installed-files.json` |
| 소스 검사 | 배경 사용자 설정 보존·인수 제한 Node 테스트 4개와 후보 경계 Python 테스트 4개 통과. 테마 생성물 검사 통과 |
| 패키지 | 전체 225개 SHA·Ed25519 서명·내용 명세 검증, 운영 런타임 의존성 208개 확인. `r6-final-archive-audit.json` |

증거 위치: `artifacts/server-shell/20261105-stage1/candidate-r4/`.
현재 상태와 통과 항목의 기계 판독 보고서는 `r6-final-validation.json`을 따른다.
현재 GNOME 50.4에서 CSS/GJS 확장 오류는 확인되지 않았다.

## 고정 SHA-256

| 대상 | SHA-256 |
| --- | --- |
| 후보 인덱스 | `c400e1d453c9561c7d7f4d39377b6b88109cd34fad93887362141b8fc66b4d2f` |
| Ed25519 공개키 | `22122bb259fb1d61c21bf0db35c439cedbf631cb2f1c5cc8af07ef23e3a24f2f` |
| 세션 0.1.0-6 | `e105186075fc443fc93971bc2f173532199d67996d8d8780a95e1cc404bd5cb7` |
| 재사용 관리자 0.1.0-7 | `fb29c2fb0779514515b454fb81aacdbac3b8aa592b5656baced848aaa4eb7a2f` |

후보 프로필만 r6 인덱스로 고정했다. 서명 개인키는 빌드 서버에만 보관한다.

## 실제 화면

![전체 이미지가 보이는 배경](../artifacts/server-shell/20261105-stage1/candidate-r4/r6-wallpaper.png)

![라이트 달력](../artifacts/server-shell/20261105-stage1/candidate-r4/r6-calendar-light.png)

![다크 달력](../artifacts/server-shell/20261105-stage1/candidate-r4/r6-calendar-dark.png)

![최종 앱 목록](../artifacts/server-shell/20261105-stage1/candidate-r4/r6-app-grid.png)

![정상 Polkit 인증](../artifacts/server-shell/20261105-stage1/candidate-r4/r6-polkit.png)

## 남은 범위

전체 Stage 3 최종 배포 판정은 아니다. 기존 관리자 보조 창의 중복 제목과 표준 출력이 없는 작업의 빈 완료 본문,
기본 HTTPS 브라우저 부재에 따른 incident-ai 열기 의존성, 기존 portal·선택 서비스·iso-codes SDK 경로 및
Hyper-V 소프트웨어 그래픽 경고가 남아 있다. 실제 한글 조합 입력은 별도 검증이 필요하다.
OSD와 앱 전환기는 스타일 규칙을 추가했으나 이번 최종 후보의 시각 검증 항목으로 계상하지 않았다.
이번 변경에서 GDM·잠금 화면을 새 픽셀 디자인으로 교체했다고 표현하지 않는다.
