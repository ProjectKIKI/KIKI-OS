# KIKI 컨테이너 빌더

이 컨테이너는 Rocky 9 환경 안에서 KIKI 웹 콘솔과 빌드 도구를 실행한다.
저장소는 컨테이너의 `/work`에 마운트되므로 빌드 산출물은 호스트의 `build/`와
`dist/` 아래에 남는다.

## 이미지 빌드

Podman:

```bash
podman build \
  -f deploy/container/Containerfile \
  -t kiki-buildd:rocky9 \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  .
```

Docker:

```bash
docker build -f deploy/container/Containerfile -t kiki-buildd:rocky9 .
```

## 웹 콘솔 실행

```bash
podman run --rm -it \
  -p 8090:8090 \
  -v "$PWD:/work" \
  -e KIKI_JOBS="$(nproc)" \
  kiki-buildd:rocky9
```

접속 주소:

```text
http://127.0.0.1:8090
```

웹 콘솔에는 자체 인증이 없다. 실제 빌드 서버에서는 localhost, VPN, 또는 인증
리버스 프록시 뒤에서만 노출한다.

## 웹 UI 없이 파이프라인 실행

```bash
podman run --rm -it \
  -v "$PWD:/work" \
  -e KIKI_JOBS="$(nproc)" \
  kiki-buildd:rocky9 run smoke

podman run --rm -it \
  -v "$PWD:/work" \
  -e KIKI_JOBS="$(nproc)" \
  kiki-buildd:rocky9 run stage2
```

사용 가능한 파이프라인:

```text
smoke
bootstrap
minimal-systemd
stage2
security
iso
bootiso
installer-iso
publish
release
```

## Compose 실행

```bash
KIKI_UID="$(id -u)" KIKI_GID="$(id -g)" \
podman compose -f deploy/container/compose.yaml up --build
```

SELinux가 켜진 호스트에서는 `compose.yaml`의 `/work` volume 또는 `podman run -v`
옵션에 `:Z`를 추가한다.

## 운영 참고

- 빌드는 컨테이너 내부에서 실행된다.
- source, cache, package, rootfs, ISO, publish 산출물은 마운트된 `/work`를 통해
  호스트에 기록된다.
- `bootiso`는 GRUB, KIKI 커널, 생성된 initramfs를 포함한 VM 부팅 테스트 ISO를
  만든다.
- `installer-iso`는 부팅 로고, stage-1 TUI 설치기, `/install/kiki-stage1.img`,
  파괴적 작업 확인 절차를 포함한 설치 ISO를 만든다.
- 기본 toolchain ID는 `container-rocky9-stage0-gcc11-v1`이다. 이 값은 패키지
  빌드 캐시 키에 들어가므로 의도적으로 바꿔야 한다.
- KIKI 기본 네트워크 정책은 `systemd-networkd`다. `NetworkManager`는 추후
  데스크톱/무선/VPN 프로파일용 선택 패키지로 추가한다.
