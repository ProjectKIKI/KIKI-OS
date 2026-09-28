# KIKI OS Podman 시험 패키지

`kiki-podman-bootstrap`은 KIKI OS용 **시험용 rootful Podman 5.8.2 KI2**다.
Podman 본체, Quadlet systemd generator, netavark, aardvark-dns, catatonit,
필요한 Rocky 9 ABI 라이브러리를 포함한다. 기존 KIKI 시스템 라이브러리는
교체하지 않고 전용 `/usr/lib/kiki-podman/lib`에서만 적재한다.
`conmon`과 `crun`은 별도 KI2 의존 패키지다.

이 패키지는 네이티브 KIKI 소스 빌드가 아니다. 격리된 호스트 ABI
부트스트랩이므로 KIKI OS VM에서 컨테이너와 Quadlet을 실제 실행하기 전에는
정식 기본 설치 그룹으로 승격하지 않는다. 별도의 Stage 3 서명 후보 저장소와
시험용 설치 ISO로만 제공한다. rootless 실행,
SELinux 정책, 레지스트리 인증, 운영 환경의 네트워크와
스토리지는 검증되지 않았다. 패키지 설치만으로 컨테이너를 실행하거나
네트워크 서비스를 켜지는 않는다.
이미지 정책은 기본 거부(`reject`)이며, 승인된 이미지 출처·서명 검증 정책을
관리자가 설정하기 전에는 pull이 차단된다.

## 빌드와 정적 검증

Rocky-9 WSL에서 다음과 같이 스테이징한 뒤 KI2를 만든다. 스테이징 도구는
기존 출력 디렉터리를 덮어쓰지 않고, 기본 rootfs 파일과 충돌하면 중단한다.

```sh
python3 tools/ki2podman.py \
  --base-rootfs build/ki2/host-graphics/rootfs \
  --output build/ki2/host-podman/rootfs
python3 tools/ki2build.py validate --profile distro/profiles/podman-bootstrap.toml
python3 tools/ki2build.py build --profile distro/profiles/podman-bootstrap.toml \
  --only conmon crun kiki-podman-bootstrap
KIKI_TEST_PODMAN=1 python3 tools/test_ki2podman_runtime.py -v
```

호스트 측 테스트는 KI2의 KIKI glibc 로더와 전용 라이브러리로
`podman --version`을 호출하고, 라이브러리 경로가 추출된 시험 rootfs 안에
있는지 확인한다. **부팅한 KIKI OS에서 동작한다는 증거는 아니다.**

## 다음 검증 단계

격리된 KIKI OS VM에서 `kiki-podman-check`, `podman info`, 고정 digest
이미지의 pull/run, 컨테이너 DNS, 재부팅 뒤 Quadlet systemd unit,
스토리지 드라이버와 정리 절차를 검증한다. 이 단계까지 통과하면
패키지 의존성·이미지 출처 정책을 확정하고 정식 배포 채널로 승격한다.

## 서명 후보 배포

`dist/ki2/signed-podman-r21/`은 기존 r20의 116개 KI2에 Podman,
`conmon`, `crun` 3개를 추가한 119개 패키지의 별도 서명 후보 저장소다.
Podman 패키지는 `kiki-podman-bootstrap-5.8.2-5.x86_64.ki2`이며,
실행 래퍼의 `/usr/bin/bash`는 `bash` 런타임 의존성으로 보장한다.
`releases/ki2/stage3-v3-20260929-podman/repo/`에는 Git에 올릴 공개
메타데이터만 둔다. Git의 인덱스 파일만으로는 패키지를 설치할 수 없으며,
실제 배포에는 동일한 `packages/x86_64/`의 KI2 바이너리 119개와
검증된 Stage 3 공개키를 함께 제공해야 한다. 개인키는 배포하지 않는다.

`ki2ctl`을 사용한 격리 루트 시험에서 새 저장소의 Ed25519 서명 검증 및
`kiki-podman-bootstrap` 의존성 설치 계획과 실제 설치는 통과했다. WSL의
격리 마운트 네임스페이스에서 `kiki-podman-check`는 cgroup v2,
netavark 및 overlay 스토리지를 보고했다. 현재 후보 저장소는
부팅한 KIKI OS에서 컨테이너 실행이 확인된 운영 채널이 아니다.

시험용 ISO는
`dist/iso/kiki-stage3-v3-installer-x86_64-20260929-r21-podman.iso`다.
ISO에서 다시 추출한 저장소의 Ed25519 서명과 119개 KI2 SHA-256을
`ki2media.py`로 검증했다. BIOS·UEFI 부팅 카탈로그를 확인했지만
KIKI VM의 실제 설치·부팅·컨테이너 실행 시험은 아직 남아 있다.
