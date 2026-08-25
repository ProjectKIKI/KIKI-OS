# KIKI OS 설치 프런트엔드

KIKI OS 설치기는 하나의 `kiki-install-plan-v1` 계약을 CLI, TUI, GTK GUI와
무인 설치가 함께 사용한다. 프로필별 패키지와 서비스 계산은
`kiki-installer-tui`가 담당하고 GTK 앱은 이 실행 파일을 호출해 같은 YAML을
생성한다.

## 메뉴 구성

| 순서 | 메뉴 | 주요 설정 |
| --- | --- | --- |
| 1 | 언어 및 지역 | 로케일, 콘솔 키맵, 시간대 |
| 2 | 디스크 | 전체 디스크, 자동 파티셔닝, swap 정책 |
| 3 | 네트워크 | DHCP, 고정 주소, 네트워크 끄기 |
| 4 | 계정 | 관리자 이름과 호스트명 |
| 5 | 패키지 소스 | 로컬 미디어, 원격 저장소, 미러와 검증 키 |
| 6 | 프로필 | 일반 서버 또는 Kubernetes 노드 역할 |
| 7 | 런타임 | 프로필 기본값, CRI-O, containerd |
| 8 | AI | 로컬 llama.cpp, 원격 호환 API, 끄기 |
| 9 | 검토 | 차단 항목과 파괴적 디스크 작업 확인 |
| 10 | 저장/설치 | InstallPlan 저장 후 Stage-1 실행기로 전달 |

디스크 암호화와 Secure Boot는 실제 포맷·키 등록 백엔드가 준비되기 전까지
메뉴에 표시하지 않는다. 선택지만 존재하고 실제로 적용되지 않는 상태를 피하기
위한 결정이다.

## CLI 및 무인 계획 생성

```sh
go build -o build/kiki-installer-tui ./cmd/kiki-installer-tui

build/kiki-installer-tui --write \
  --mode unattended \
  --plan ./install-plan.yaml \
  --profile server-core \
  --disk /dev/sda \
  --locale ko_KR.UTF-8 --keymap kr --timezone Asia/Seoul \
  --network dhcp \
  --source local --source-location /run/install-media \
  --ai local
```

원격 저장소는 HTTP(S) URL과 검증 키가 모두 있어야 계획 검사를 통과한다.

```sh
build/kiki-installer-tui --write \
  --source remote \
  --source-location https://repo.example/kiki \
  --verify-key /etc/ki2/trust/repository.pub
```

ISO의 Stage-1 무인 설치는 기존 커널 인자
`kiki.autoinstall=erase|quick-vm`과 `kiki.profile`, `kiki.runtime`,
`kiki.target`, `kiki.hostname`, `kiki.locale`, `kiki.keymap`,
`kiki.timezone`, `kiki.ai`, `kiki.ai-endpoint`를 사용한다. 이 경로는 명시된
경우에만 콘솔의
파괴적 확인을 생략한다.

## GTK 4 실행

```sh
make -C cmd/kiki-installer-gtk
KIKI_INSTALLER_TUI="$(pwd)/build/kiki-installer-tui" \
KIKI_INSTALLER_CSS="$(pwd)/cmd/kiki-installer-gtk/style.css" \
  ./cmd/kiki-installer-gtk/kiki-installer-gtk
```

GTK는 웹 CSS를 직접 실행하는 것이 아니라 GTK CSS의 색상, 여백, 테두리,
상태 클래스 등을 사용한다. 현재 GTK 앱은 계획 작성·검토·저장을 담당한다.
실제 파티션 포맷과 패키지 추출은 ISO Stage-1 실행기가 수행한다.

KIKI 자체 GTK 패키지는 GTK 4와 그래픽 세션 의존성 레시피가 갖춰진 별도
`desktop-*` 프로필에서 제공한다. 서버 코어와 설치 initramfs에는 GTK를 넣지
않아 복구 TUI와 무인 설치 경로를 작게 유지한다.

## AI 콘솔 배치

- `local`: tty1에서 한국어 AI 콘솔과 CPU 기반 llama.cpp 서버를 실행한다.
- `remote`: tty1 콘솔은 원격 OpenAI 호환 엔드포인트를 사용한다.
- `off`: tty1을 일반 로그인 셸로 되돌린다.
- 모든 모드에서 tty2는 독립 복구 셸이다.
- AI가 만든 명령은 실행 전에 명령 내용을 표시하고 운영자의 명시적 승인을 받는다.
