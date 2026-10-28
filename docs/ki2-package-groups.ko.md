# KIKI 패키지 그룹

KIKI 패키지 그룹은 ISO 프로파일, GUI/TUI/CLI 설치기와 설치 후 `ki2ctl`이
같은 역할별 패키지 목록을 공유하기 위한 선언형 카탈로그입니다. 원본은
`/usr/share/ki2/package-groups.json`에 설치되며 스키마는
`ki2-package-groups-v1`입니다.

기본 그룹은 `minimal`, `server`, `ai-console`, `ai-console-remote`,
`container-containerd`, `container-crio`, `kubernetes-node`, `development`,
`desktop-gnome`, `xorg-runtime`입니다.
각 그룹은 필수·기본·선택 패키지, 선행 그룹과 활성화·비활성화 서비스 목록을
가집니다. 프로파일은 직접 패키지 목록을 반복하지 않고 `groups`를 선언하며,
빌드 도구가 선행 그룹과 기본 패키지를 확장합니다.

```sh
ki2ctl group list
ki2ctl group info ai-console
ki2ctl group install ai-console
ki2ctl group install development --with-optional
ki2ctl group upgrade ai-console
ki2ctl group remove ai-console --dry-run
ki2ctl group remove ai-console
```

`ki2ctl`은 설치 패키지마다 다음과 같은 사유를 기록합니다.

- `explicit`: 사용자가 패키지 이름을 직접 지정함
- `dependency:<패키지>`: 명시 패키지의 런타임 의존성
- `group:<그룹>`: 패키지 그룹이 소유함

그룹을 제거할 때는 해당 그룹 사유만 제거합니다. 명시 설치, 다른 그룹 또는
남아 있는 패키지의 의존성이 있으면 패키지와 파일을 보존합니다. 이전 버전의
설치 DB에 사유가 없으면 안전을 위해 `explicit`으로 간주합니다.

설치기 CLI와 무인 설치에서는 `--groups`에 쉼표 구분 추가 그룹을 지정합니다.

```sh
kiki-installer-tui --write \
  --profile minimal-systemd \
  --groups development,container-containerd
```

전체 화면 TUI에서는 `group add development`와 `group remove development`를
사용합니다. GTK 설치기의 **추가 구성** 체크박스도 같은 옵션을 전달합니다.
선택 결과는 InstallPlan의 `packages.groups`와 `packages.selected`에 함께 기록되어
구성 의도와 실제 설치 패키지를 모두 감사할 수 있습니다.

카탈로그의 `profiles`는 프로파일 표시 이름, 그룹 조합과 기본 AI 정책을 정의합니다.
`services.default_target`은 그룹에 필요한 부팅 대상을 선언합니다. GNOME 그룹은
`graphical.target`, GDM과 tty2 복구 콘솔을 사용하며 tty1 AI 콘솔을 비활성화합니다.
Go·GTK용 테이블을 수정할 때는 원본 카탈로그를 먼저 수정하고 다음 명령을 실행합니다.

```sh
python3 tools/ki2installcatalog.py
python3 tools/ki2installcatalog.py --check
```

ISO 백엔드는 같은 카탈로그를 직접 읽습니다. 새 미디어에는 프로파일·그룹의 전이
런타임 의존성, 포함 여부, 패키지 수와 압축 크기를 기록합니다. GTK는 설치할 수 없는
구성을 비활성화하며 TUI도 실제 로컬 인덱스의 누락·순환 의존성을 검토 단계에서
차단합니다. 실제 설치 전에는 별도로 Ed25519 서명과 패키지 해시를 검증합니다.
AI 패키지가 없는 미디어에서는 일반 서버도 AI를 끈 기본값으로 설치할 수 있습니다.

`ki2ctl group install`은 서비스 정책을 출력·기록합니다. 설치 후 그룹 명령만 실행하는
경우 서비스 활성화와 기본 부팅 대상 전환은 관리자가 별도로 적용해야 합니다.
새 OS를 설치하는 GTK·TUI·무인 설치 경로는 이 정책을 설치 대상에 적용합니다.
