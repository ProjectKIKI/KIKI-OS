# KIKI OS 관리 콘솔

빌드 웹 콘솔과 작업 기록도 같은 관리 콘솔에서 사용할 수 있다:

```bash
python3 tools/kiki_console.py build-web --jobs 8
python3 tools/kiki_console.py pipeline-plan smoke
python3 tools/kiki_console.py jobs
python3 tools/kiki_console.py job <작업-ID> --json
```

대화형 `shell`에서도 `jobs`, `job <작업-ID>`, `pipeline-plan smoke`, `build-web`을
입력할 수 있다. 명령마다 지원하는 기본 옵션만 전달하며, 명시적으로 입력한
옵션이 셸 기본값보다 우선한다. 웹 화면의 실행 미리보기, 대기열, 실시간 로그,
취소·재실행 동작은 [빌드 자동화 가이드](kiki-os-build-automation.ko.md)에 설명한다.

`tools/kiki_console.py`는 ISO를 만들기 전에 Git 상태, Stage 3 진행률, 패키지 저장소,
rootfs와 ISO 산출물을 한 화면에서 확인하고 검증·빌드 작업을 제어하는 운영자용 CLI다.
CI 서버용 `ki2ci.py`와 선언형 실행기 `ki2osbuild.py`를 대체하지 않고 안전한 관리
진입점으로 묶는다.

## 시작

터미널에서 인자 없이 실행하면 대화형 콘솔이 열린다.

```bash
python3 tools/kiki_console.py
```

자동화 환경처럼 표준 입력이 터미널이 아니면 기본적으로 `status`만 출력한다.

```text
KIKI OS 관리 콘솔
  브랜치       feat/stage-3-kiki-platform (ahead 16 / behind 0)
  작업 트리    변경 39개
  Stage 3      17/21 완료, 4개 대기
  기본 계획    distro/build-plans/stage3-server-core.yaml (준비됨)
  패키지       0개 / 0.0 B
  저장소 인덱스 없음
  rootfs       0개
  ISO          0개
```

## 명령

```bash
python3 tools/kiki_console.py status
python3 tools/kiki_console.py status --json
python3 tools/kiki_console.py doctor
python3 tools/kiki_console.py doctor --iso
python3 tools/kiki_console.py verify
python3 tools/kiki_console.py plan
python3 tools/kiki_console.py plan --iso
python3 tools/kiki_console.py build --dry-run
python3 tools/kiki_console.py build
python3 tools/kiki_console.py artifacts
```

- `status`: Git 동기화, 계획 체크리스트, 패키지·rootfs·ISO와 최근 실행을 표시한다.
- `doctor`: 필수 호스트 도구, Stage 3 계약, 빌드 계획 렌더링, Git 공백 오류를 검사한다.
- `doctor --iso`: `xorriso`와 `grub-mkrescue`까지 필수 조건으로 검사한다.
- `verify`: `tools/ki2stage3.py verify` 종합 검증을 실행한다.
- `plan`: 실제 실행 없이 패키지, Ed25519 저장소, rootfs 단계와 명령을 보여준다.
- `build`: ISO를 만들지 않고 패키지·저장소·rootfs와 검증 단계까지만 실행한다.
- `artifacts`: 만들어진 패키지, rootfs, ISO와 크기를 표시한다.

## ISO 안전 게이트

ISO 생성은 별도 `iso` 명령으로 분리되어 있다. 비대화형 환경에서는 `--yes` 없이
실행되지 않으며, 대화형 환경에서도 확인 질문을 거친다.

```bash
python3 tools/kiki_console.py doctor --iso
python3 tools/kiki_console.py plan --iso
python3 tools/kiki_console.py iso --dry-run --yes
python3 tools/kiki_console.py iso --yes
```

기존 패키지를 재사용할 때만 `--skip-build`를 사용한다.

```bash
python3 tools/kiki_console.py iso --skip-build --yes
```

## Stage 3 기본 계획

기본 계획은 `distro/build-plans/stage3-server-core.yaml`이다. 이 계획은 다음 순서를
선언한다.

1. `server-core` 패키지 프로필 검증과 빌드
2. 패키지 저장소 인덱스 작성
3. Stage 3 Ed25519 개인키·공개키 확보
4. `stage3-v3` 저장소 메타데이터 서명과 공개키 검증
5. `dist/rootfs/server-core` 조립
6. Stage 3 계약, 네트워크 사용자 공간, 패키지 관리자 검증
7. 명시적으로 승인한 경우에만 설치 ISO 생성

다른 계획은 모든 계획 기반 명령에서 `--build-plan`으로 지정할 수 있다.

```bash
python3 tools/kiki_console.py plan \
  --build-plan distro/build-plans/stage2-kube-compute-containerd.yaml
```

저장소 개인키는 `build/ki2/keys/` 아래에 생성되며 Git에 커밋하거나 ISO에 포함하면
안 된다. ISO와 게시 산출물에는 공개키만 배포한다.
