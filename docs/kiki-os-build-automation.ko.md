# KIKI OS 빌드 자동화 도구

`tools/ki2osbuild.py`는 KIKI OS 전체 빌드를 선언형 YAML 계획서로 실행하는
오케스트레이터다. 기존 도구를 새로 대체하지 않고 다음 흐름을 하나로 묶는다.

```text
build plan YAML
  -> ki2build validate/plan/build
  -> ki2build repo-index
  -> ki2repo keygen/generate/verify
  -> ki2build rootfs
  -> ki2stage2 verify
  -> optional ki2bootiso
  -> build/ki2osbuild/<run-id>/manifest.json
```

## 기본 계획서

기본 계획서는 다음 파일이다.

```text
distro/build-plans/stage2-kube-compute-containerd.yaml
```

이 계획서는 Stage 2 containerd Kubernetes compute 노드용 rootfs를 만든다. ISO 생성은
기본값으로 꺼져 있다.

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
python tools/ki2osbuild.py plan --iso
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
python tools/ki2osbuild.py run --iso
```

## 산출물 기록

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

## Stage 2 기본 검증

기본 계획서는 다음 검증을 포함한다.

- Stage 2 Kubernetes readiness
- network userspace strict 검증
- runtime/Kubernetes binary smoke
- `ki2ctl` package manager repository flow
- installed rootfs 검증

개발 중 빠른 빌드만 필요하면:

```bash
python tools/ki2osbuild.py run --skip-verify
```

## 운영 원칙

- ISO 생성은 시간이 오래 걸리므로 기본값은 비활성화한다.
- 실제 릴리스 전에는 `--skip-verify`를 사용하지 않는다.
- 저장소 서명키는 HTTP publish 대상에 넣지 않는다.
- Stage 3에서는 이 계획서에 source-backed build, 원격 publish, 클러스터 bootstrap
  자동화를 추가한다.
