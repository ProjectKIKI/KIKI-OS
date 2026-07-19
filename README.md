# AOS(KIKI Arte Operating System) 패키징 시스템 v0.0.3

이 저장소는 AOS 패키징 도구의 최소 **실행 가능** 프로토타입을 담고 있습니다.

- `bosctl`: BaseOS 패키지 관리자
- `cpmctl`: 컨테이너 패키지 관리자
- `bosbuild`: BOS 패키지 아카이브 빌더
- `tools/ki2build.py`: 초기 KIKI OS 레시피 빌더와 루트 파일시스템 조립기

## KIKI OS 시드 빌드 시스템

독립 배포판 작업은 `distro/` 아래에서 시작합니다. 이 경로에는 40개 패키지 규모의
systemd/glibc 시드 카탈로그와 작은 Python 빌드 오케스트레이터가 들어 있습니다.

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 40
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --dry-run
python tools/ki2build.py rootfs --profile distro/profiles/bootstrap-stage1.toml --rootfs-dir dist/rootfs/bootstrap-stage1
```

현재 WSL/Rocky 빌더 스모크 상태: 실제 `.ki2` 산출물 17개와 검증된 pre-systemd
`bootstrap-stage1` 루트 파일시스템이 생성되었습니다. `systemd`는 현재 컴파일/링크
단계까지 도달하며, 다음 단계에서는 KIKI 헤더가 호스트 libc와 섞이지 않도록 실제 대상
sysroot 도구체인이 필요합니다.

패키지 범위, 캐시 모델, 빌드 상태, 다음 부트스트랩 단계는 `distro/README.md`를
참조하세요.

## 빌드

프로젝트 루트에서 실행합니다.

```bash
go mod tidy

go build -o bosctl ./cmd/bosctl
go build -o cpmctl ./cmd/cpmctl
go build -o bosbuild ./cmd/bosbuild

go test ./cmd/... ./internal/...
```

## BOS(BaseOS) 로컬 DB 사용법

```bash
./bosctl init
./bosctl add baseos 0.0.1 x86_64 "Base OS core" 1
./bosctl add kernel 5.15.130 x86_64 "Linux kernel" 1 --deps baseos

./bosctl list
./bosctl info baseos
./bosctl remove kernel
```

이 명령은 `${HOME}/.bosctl/bosdb.json` 아래의 JSON DB를 사용합니다.

## CPM(컨테이너 패키지) 로컬 DB 사용법

```bash
./cpmctl init
./cpmctl add nginx 1.25.0 registry.example.com/aos/nginx:1.25.0 "NGINX web server"
./cpmctl list
./cpmctl info nginx
./cpmctl remove nginx
```

DB 경로: `${HOME}/.cpmctl/cpmdb.json`.

## BOS 패키지 빌드

`bosbuild`는 최상위 `manifest.yaml` 파일과 선택적 `rootfs/`, `scripts/`
디렉터리를 포함한 작업 디렉터리에서 `.bos` 패키지를 만듭니다.

```bash
bosbuild -C ./workdir -o kernel-5.15.130-1.x86_64.bos
```

예제 구성:

```text
workdir/
  manifest.yaml
  rootfs/
    usr/
    lib/
  scripts/
    post-install.sh
```

빌더는 패키지를 제자리로 옮기기 전에 임시 파일에 먼저 기록합니다. 출력 대상 경로가
소스 작업 디렉터리 안에 있으면 해당 출력 파일은 건너뜁니다.

## BOS HTTP 저장소 인덱스 생성

`bosctl`은 `.bos` 패키지가 들어 있는 디렉터리에서 `index.yaml`을 생성할 수 있습니다.
각 `.bos` 파일은 최소한 다음 필드를 가진 최상위 `manifest.yaml` 파일을 포함한
`tar.gz` 아카이브라고 가정합니다.

```yaml
name: kernel
version: "5.15.130"
release: "1"
arch: "x86_64"
summary: Linux kernel
dependencies:
  runtime:
    - baseos
  build:
    - gcc
    - make
```

예제 구성:

```text
/var/www/bos-repo/
  kernel-5.15.130-1.x86_64.bos
  baseos-0.0.1-1.x86_64.bos
```

`index.yaml` 생성:

```bash
bosctl repo-index /var/www/bos-repo
```

이 명령은 각 `.bos` 파일의 SHA-256 다이제스트와 매니페스트에 선언된 패키지 의존성을
포함하는 `/var/www/bos-repo/index.yaml` 파일을 생성합니다.

패키지의 런타임 의존성 설치 순서를 미리 확인합니다.

```bash
bosctl plan /var/www/bos-repo kernel
```

## 참고

- 이 저장소는 다음 항목에 초점을 둔 초기 프로토타입(v0.0.3)입니다.
  - BOS/CPM 로컬 DB 관리
  - BOS 패키지 아카이브 빌드
  - BOS용 HTTP 저장소 인덱스 생성(`index.yaml`)
- 실제 루트 파일시스템에 BOS 패키지를 설치하는 기능과 CPM의 podman/systemd 통합은
  이후 단계에서 다룰 예정입니다.
