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
  -p 127.0.0.1:8090:8090 \
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

`/package-build`에서 기존 검토된 KI2 레시피 하나를 선택해 개별 빌드를
요청할 수 있다. 각 작업의 패키지와 로그는 `build/ki2ci/jobs/<작업 ID>/`에
격리된다. 이 단계는 서명·배포를 자동으로 수행하지 않는다. 새 레시피를
웹 입력만으로 생성하는 기능과 BOS 웹 빌드는 아직 구현되지 않았다.

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

- 인증을 포함한 후보 빌드 웹의 한국어 UI, OS 버전별 ISO, x86-64-v3/v4 준비 상태와 보존 규칙은
  [버전·CPU 대상 운영 문서](../../docs/kiki-build-web-version-cpu.ko.md)를 참고한다.
- 릴리즈별 패키지 구성과 ISO 이력, 변경 비교·잠금·보관은
  [릴리즈 관리 운영 문서](../../docs/kiki-build-web-release-management.ko.md)를 참고한다.
- 사용자 추가·권한·비활성화·임시 비밀번호·세션 관리는
  [사용자 관리 운영 문서](../../docs/kiki-build-web-user-management.ko.md)를 참고한다.
- 터미널랩 공통 디자인과 반응형 메뉴는
  [빌드 웹 디자인 운영 문서](../../docs/kiki-build-web-terminal-lab-design.ko.md)를 참고한다.
- 빌드는 컨테이너 내부에서 실행된다.
- 소스, 캐시, 패키지, 루트 파일시스템, ISO, 배포 산출물은 마운트된 `/work`를 통해
  호스트에 기록된다.
- `bootiso`는 GRUB, KIKI 커널, 생성된 initramfs를 포함한 VM 부팅 테스트 ISO를
  만든다.
- `installer-iso`는 부팅 로고, 1단계 TUI 설치기, `/install/kiki-stage1.img`,
  파괴적 작업 확인 절차를 포함한 설치 ISO를 만든다.
- 기본 도구체인 ID는 `container-rocky9-stage0-gcc11-v1`이다. 이 값은 패키지
  빌드 캐시 키에 들어가므로 의도적으로 바꿔야 한다.
- KIKI 기본 네트워크 정책은 `systemd-networkd`다. `NetworkManager`는 추후
  데스크톱/무선/VPN 프로파일용 선택 패키지로 추가한다.
