# KIKI OS 빌드 자동화 도구

> Stage3 신규 빌드는 `distro/build-plans/stage3-server-core.yaml`을 명시한다.
> 아래의 인자 없는 명령은 도구의 Stage2 기본 계획을 사용한다. 로컬 서버 설치와
> 실제 Stage3 절차는 [로컬 빌더 가이드](kiki-stage3-local-builder.ko.md)를 참조한다.

`tools/ki2osbuild.py`는 KIKI OS 전체 빌드를 선언형 YAML 계획서로 실행하는
오케스트레이터다. 기존 도구를 새로 대체하지 않고 다음 흐름을 하나로 묶는다.

운영자가 ISO 전에 상태를 확인하고 이 오케스트레이터를 안전하게 제어하려면
`tools/kiki_console.py`를 사용한다. 관리 콘솔의 Stage 3 기본 계획은
`distro/build-plans/stage3-server-core.yaml`이며 Ed25519 저장소 서명을 사용한다.

```text
빌드 계획 YAML
  -> ki2build validate/plan/build
  -> ki2build repo-index
  -> ki2repo keygen/generate/verify
  -> ki2build rootfs
  -> ki2stage2 verify
  -> 선택적 ki2bootiso
  -> build/ki2osbuild/<run-id>/manifest.json
```

## 기본 계획서

기본 계획서는 다음 파일이다.

```text
distro/build-plans/stage2-kube-compute-containerd.yaml
```

이 계획서는 2단계 containerd Kubernetes 컴퓨트 노드용 루트 파일시스템을 만든다. ISO 생성은
기본값으로 꺼져 있다.

Stage 3 서버와 설치 ISO 준비 계획은 다음 파일이다.

```text
distro/build-plans/stage3-server-core.yaml
```

## 계획서 목록

```bash
python tools/ki2osbuild.py list
```

## 실행 전 단계 확인

```bash
python tools/ki2osbuild.py plan
```

ISO까지 포함할 계획을 확인하려면 다음처럼 실행한다.

```bash
python tools/ki2osbuild.py plan --build-plan distro/build-plans/stage3-server-core.yaml --iso
```

## 실제 빌드

```bash
python tools/ki2osbuild.py run
```

긴 빌드가 부담될 때 기존 패키지를 재사용하려면:

```bash
python tools/ki2osbuild.py run --skip-build
```

명령만 확인하고 실행하지 않으려면:

```bash
python tools/ki2osbuild.py run --dry-run
```

ISO까지 생성하려면 명시적으로 `--iso`를 붙인다.

```bash
python tools/ki2osbuild.py run --build-plan distro/build-plans/stage3-server-core.yaml --iso
```

WSL에서 패키지의 임시 작업과 빌드 상태를 Linux 파일시스템에 두려면
`--build-dir`을 지정한다. 같은 옵션을 `kiki_console.py build/iso/plan/shell`에서도
사용할 수 있다. 기존 패키지 캐시 판정과 산출물 경로 규칙을 사용한다.

```bash
python3 tools/ki2osbuild.py run --build-plan distro/build-plans/stage3-server-core.yaml --iso --build-dir "$HOME/.cache/kiki-build" --rootfs-dir "$HOME/.cache/kiki-rootfs"
```

`--rootfs-dir`은 조립과 ISO 생성에 같은 경로를 전달한다. Linux 권한을 보존하지
못하는 저장소는 rootfs 정리 전에 거부하므로 WSL에서는 Linux 파일시스템을 지정한다.

## 산출물 기록

실행을 시작하면 전체 단계가 담긴 `manifest.json`이 생성되고, 각 단계의 시작과
완료 때 원자적으로 갱신된다. 실행 중에는 현재 단계와 로그 경로를 확인할 수 있다.
실패한 단계도 종료 코드·오류·로그 경로를 기록하고 후속 단계는 `skipped`로 남긴다.
이미 `manifest.json`이 있는 실행 디렉터리는 덮어쓰지 않는다. 재실행 시 새
`--release-id` 또는 `--run-dir`을 선택한다.

각 실행은 기본적으로 다음 위치에 기록된다.

```text
.ki2osbuild/YYYYMMDD-HHMMSS/
```

주요 파일:

- `manifest.json`: 실행 계획, 각 단계 상태, 명령, 로그 파일 경로
- `NN-<step>.log`: 단계별 stdout/stderr 로그

고정된 실행 디렉터리를 쓰려면:

```bash
python tools/ki2osbuild.py run --release-id 20260612-stage2-test
```

또는:

```bash
python tools/ki2osbuild.py run --run-dir .ki2osbuild/manual-test
```

## 저장소 서명

계획서의 기본 서명키는 다음 경로다.

```text
build/ki2/keys/stage2-v2-repo.hmac
```

키가 이미 있으면 `ki2osbuild`는 keygen 단계를 건너뛴다. 새 키로 덮어쓰려면:

```bash
python tools/ki2osbuild.py run --force-key
```

## 2단계 기본 검증

기본 계획서는 다음 검증을 포함한다.

- 2단계 Kubernetes 준비도
- 네트워크 사용자 공간 엄격 검증
- 런타임/Kubernetes 바이너리 스모크
- `ki2ctl` 패키지 관리자 저장소 흐름
- 설치된 루트 파일시스템 검증

개발 중 빠른 빌드만 필요하면:

```bash
python tools/ki2osbuild.py run --skip-verify
```

## 운영 원칙

- ISO 생성은 시간이 오래 걸리므로 기본값은 비활성화한다.
- 실제 릴리스 전에는 `--skip-verify`를 사용하지 않는다.
- 저장소 서명키는 HTTP 배포 대상에 넣지 않는다.
- 3단계에서는 이 계획서에 소스 기반 빌드, 원격 배포, 클러스터 부트스트랩
  자동화를 추가한다.

## 웹 빌드 콘솔과 CLI

```bash
python3 tools/kiki_console.py build-web --jobs 8
# http://127.0.0.1:8090/jobs
python3 tools/kiki_console.py pipeline-plan smoke
python3 tools/kiki_console.py jobs
python3 tools/kiki_console.py job <작업-ID>
```

웹 화면에서 파이프라인을 선택하면 실제 실행 단계와 명령을 미리 보여준다.
`Queue build`로 제출한 작업은 하나의 워커가 제출 순서대로 실행한다. `--jobs`는
패키지 내부 컴파일 병렬도이며, 동시에 실행하는 파이프라인 수가 아니다.
단일 KI2 빌드는 기존처럼 작업별 디렉터리에 패키지와 의존성을 만든다.

작업 화면은 새로고침 없이 상태·진행 단계·대기 순서·로그를 갱신한다.
`Follow output`으로 로그 자동 스크롤을 끌 수 있다. 로그 API는 한 요청당 최대
64 KiB만 보내고, 화면은 최근 출력만 유지한다. 전체 로그는 작업 디렉터리의
`log.txt`에 보존된다. KI2 다운로드 목록은 완료 후 페이지를 새로고침하면 갱신된다.

`Cancel queued build`는 대기 중 작업만 취소한다. 실행 중인 작업은 이 버튼으로
중단하지 않는다. 완료·실패·취소·중단 작업의 `Retry entire build`는 전체
파이프라인을 새 작업 ID로 다시 제출하며, 원본 기록과 로그를 보존한다.
재실행은 현재 체크아웃과 빌더 설정을 사용하고 기존 패키지 캐시는 빌더의
기존 규칙에 따라 재사용한다. `publish`·`release` 재실행도 전체 단계를 실행한다.

같은 `--artifact-root`를 사용하는 웹 서버와 동기 CLI 실행은 파일 잠금으로
중복 실행을 막는다. 웹 서버 재시작 시 대기 작업은 복구하고, 실행 중이던 작업은
`interrupted`로 표시한다. 중단 작업의 로그를 확인한 뒤 명시적으로 재실행한다.
서로 다른 산출물 루트나 `ki2osbuild` 직접 실행은 이 잠금을 공유하지 않으므로,
공용 패키지·rootfs 경로를 사용하는 빌드는 동시에 실행하지 않는다.

기본 작업 기록 위치는 `build/ki2ci/jobs/<작업-ID>/`다. 다른 위치를 쓰면 웹 서버와
조회 명령 모두 같은 `--artifact-root`를 지정한다. JSON 자동화 인터페이스:

```bash
python3 tools/ki2ci.py plan smoke --json
python3 tools/ki2ci.py list-jobs --json
python3 tools/ki2ci.py show-job <작업-ID> --json
```

`show-job --json`은 로그를 붙이지 않고 메타데이터만 출력한다.
HTTP API는 `GET /api/plan?pipeline=smoke`, `GET /api/jobs/<ID>`,
`GET /api/jobs/<ID>/log?offset=<바이트-위치>`를 제공한다.
기존 로컬 호스트 바인딩과 외부 접근 시 역방향 프록시 보호 원칙을 유지한다.
