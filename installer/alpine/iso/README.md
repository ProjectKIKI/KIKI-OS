# KIKI Alpine ISO 빌드: 과거 실험 경로

이 디렉터리는 Alpine `aports/scripts/mkimage.sh`를 사용하던 초기 인스톨러 실험이다. 현재 KI2 기반 Stage3 설치 ISO의 기본 빌드 경로가 아니다. 현행 로컬 빌드는 [Stage3 빌드 서버 가이드](../../../docs/kiki-stage3-local-builder.ko.md)를 따른다.

이 경로는 맞춤형 `profile_kiki`, `installer/dist/kiki-alpine-overlay.tar.gz` 오버레이, `kiki-install` 실행에 필요한 패키지를 묶는다.

## 컨테이너 빌드

저장소 루트에서 Podman 또는 Docker를 선택한다.

```bash
bash installer/scripts/build-alpine-iso.sh --runner podman --release v3.20
bash installer/scripts/build-alpine-iso.sh --runner docker --release v3.20
```

첫 실행에는 Alpine 빌더 이미지와 `aports`를 얻기 위한 네트워크 접근이 필요하다.

## Alpine 호스트에서 로컬 빌드

```bash
apk add alpine-sdk syslinux xorriso squashfs-tools mtools dosfstools grub grub-efi git python3 py3-yaml
git clone --branch v3.20 https://gitlab.alpinelinux.org/alpine/aports.git installer/dist/iso-work/aports
bash installer/scripts/build-alpine-iso.sh --runner local --aports-dir installer/dist/iso-work/aports
```

실제 다운로드·패키지 작업 없이 명령만 보려면 `bash installer/scripts/build-alpine-iso.sh --runner podman --dry-run`을 실행한다. ISO는 `installer/dist/iso/`에 생성되며 파일명은 Alpine `mkimage.sh`가 정한다.
