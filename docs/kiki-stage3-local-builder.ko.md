# Stage3 로컬 빌드 서버 (x86_64)

현재 기준은 `stage3-v3` 개발 라인이다. 로컬 빌드는 Rocky Linux 9 x86_64 또는
Rocky-9 WSL2에서 수행한다. 빌더의 Rocky와 완성된 KIKI OS는 서로 다른 환경이다.
WSL2에서의 패키지 실행 검증은 KIKI VM 부팅 검증을 대신하지 않는다.

## 준비

전용 빌드 사용자와 충분한 디스크 공간을 마련하고, 이 저장소를 그 사용자에게
체크아웃한다. 소스 다운로드가 필요한 레시피는 인터넷 접근이 필요하다. WSL2에서는
Windows 드라이브 경로보다 Linux 파일시스템의 작업 사본을 권장한다. 기존 `dist/`,
`build/`, `.ki2osbuild/`가 있는 작업 사본은 삭제하지 말고 용량과 소유권을 먼저 확인한다.

```bash
uname -m                         # x86_64 확인
cat /etc/os-release              # Rocky 9 확인
df -h .                          # 빌드 공간 확인
bash distro/builders/stage3-local-build.sh deps
```

`deps`는 기존 `rocky9-wsl-deps.sh`를 실행하며 `sudo dnf`로 시스템 패키지를 설치한다.
서버 설정이나 Git 자격 증명, 서명 키는 자동 생성·변경하지 않는다. 이미 준비된 빌더에서는
`deps`를 생략한다. Git에는 소스와 공개 서명 메타데이터만 넣고, 개인키·KI2·ISO는 넣지 않는다.

## 빌드 순서

```bash
bash distro/builders/stage3-local-build.sh check
bash distro/builders/stage3-local-build.sh build
bash distro/builders/stage3-local-build.sh iso
```

`check`는 서버 프로필을 검증하고 Stage3 계획을 출력할 뿐 패키지를 만들지 않는다.
`build`는 `distro/build-plans/stage3-server-core.yaml`의 패키지·Ed25519 서명
저장소·rootfs 검증 흐름을 실행한다. `iso`는 같은 흐름에 설치 ISO를 추가한다.
기본 병렬도는 `nproc`; 예: `KIKI_BUILD_JOBS=8 bash .../stage3-local-build.sh build`.
`iso`는 빌드 단계를 다시 수행할 수 있으므로 실행 계획을 먼저 확인하고 시간을 확보한다.
로그·단계별 결과는 `.ki2osbuild/`의 실행 디렉터리에 기록된다. 실패하면 이 기록과
해당 단계 로그를 확인하고 수정 후 재실행한다. 이전 산출물을 무조건 삭제하거나
`--force-key`로 개인키를 교체하지 않는다.

직접 실행할 때:

```bash
python3 tools/ki2osbuild.py plan --build-plan distro/build-plans/stage3-server-core.yaml --iso
python3 tools/ki2osbuild.py run --build-plan distro/build-plans/stage3-server-core.yaml --iso
python3 tools/ki2repo.py verify --key build/ki2/keys/stage3-v3-repo.ed25519
```

서명 키는 비밀로 취급하고 별도 백업·접근통제를 적용한다. 공개키와 저장소 인덱스만
서버에 노출한다. 검증 완료 전 패키지 저장소를 운영 채널로 승격하지 않는다.
HTTP로 KI2를 제공할 때는 공개 메타데이터뿐 아니라 그 인덱스가 가리키는
`packages/x86_64/` 파일 전체가 필요하다.

## 현재 후보와 남은 검증

2026-09-29의 Podman r21 후보는 119개 서명 KI2를 포함한 시험 ISO다.
정확한 파일명·SHA-256·검증 범위는 [r21 기록](kiki-podman-r21-release.ko.md)에 있다.
이는 일반 Stage3 빌드 계획의 산출물과 동일하다고 가정하면 안 된다. Podman은
Rocky 9 ABI 부트스트랩이며 KIKI OS VM에서 설치·부팅, 컨테이너 네트워크,
Quadlet 재부팅 시험이 남아 있다. 따라서 이 문서의 자동화가 r21을 재생성하거나
운영 배포까지 수행한다고 주장하지 않는다.
