# KIKI OS 전체 최신 패키지 서명 저장소 (2026-09-28)

## 결과

- `dist/ki2/signed-all/`: 현재 배포 가능한 x86_64 패키지 116개, 총 2,562,869,126바이트.
- 서명 방식: `repo/metadata.x86_64.json`에 Ed25519 서명. 메타데이터가
  `repo/index.x86_64.json`의 SHA-256을 고정하며, 인덱스가 각 `.ki2` 파일의
  SHA-256을 고정한다. `ki2ctl`은 업데이트 시 서명·인덱스를, 설치 시
  패키지 해시를 검증한다. 개별 `.ki2` 파일의 별도 서명 파일은 만들지 않는다.
- 신뢰 키 ID: `834c0bf30c1d65ab`. r17 ISO의 Stage 3 저장소와 동일하다.
- 소스와 서명 메타데이터만 Git의 `releases/ki2/stage3-v3-20260928/repo/`에 둔다.
  패키지 바이너리는 Git에 포함하지 않는다. 로컬 배포 시에는
  `dist/ki2/signed-all/` 전체를 함께 제공해야 한다.
- 사용하지 않는 예전 빌드 68개는 `dist/ki2/packages/x86_64`에서 제거해
  `build/ki2/obsolete-archive-20260928/`(66개) 및
  `build/ki2/obsolete-archive-20260928-r2/`(6.9 커널 패키지 2개)로 옮겼다. 복구 가능한 보관본이며
  기존 r17 ISO와 그 내부 패키지는 수정하지 않았다.

## 구성 방법

기준은 r17 ISO의 서명된 인덱스, 로컬 KI2 패키지, LightDM 추가 패키지다.
같은 패키지 이름에서는 최신 버전/릴리스를 하나 선택하되, `linux`와
`linux-headers`는 레시피의 6.1.187에 고정한다. r17에서 실제
배포된 `kiki-installer-gtk` release 15, `kiki-ai-console` release 5,
`kiki-netconfig` release 2를 보존한다. 선정 기록은
`build/validation/20260928-signed-all/curation-plan-r2.json`에 있다.

~~~sh
python3 tools/ki2curate.py plan \
  --main-packages dist/ki2/packages/x86_64 \
  --addon-packages dist/ki2/lightdm-repo/packages/x86_64 \
  --iso-index build/validation/20260928-signed-all/r17-index.x86_64.json \
  --iso-metadata build/ki2/host-lightdm/r17-repo/metadata.x86_64.json \
  --public-key build/ki2/keys/stage3-v3-repo.ed25519.pub \
  --plan build/validation/20260928-signed-all/curation-plan-r2.json

python3 tools/ki2curate.py stage \
  --main-packages dist/ki2/packages/x86_64 \
  --addon-packages dist/ki2/lightdm-repo/packages/x86_64 \
  --iso dist/iso/kiki-stage3-v3-installer-x86_64-20260927-r17.iso \
  --plan build/validation/20260928-signed-all/curation-plan-r2.json \
  --output dist/ki2/signed-all/packages/x86_64

python3 tools/ki2repo.py \
  --packages-dir dist/ki2/signed-all/packages/x86_64 \
  --repo-dir dist/ki2/signed-all/repo \
  --iso-dir dist/ki2/signed-all/iso generate \
  --channel stage3-v3 --include-all-staged \
  --sign-key build/ki2/keys/stage3-v3-repo.ed25519 \
  --sign-algorithm ed25519
python3 tools/ki2repo.py --repo-dir dist/ki2/signed-all/repo verify \
  --key build/ki2/keys/stage3-v3-repo.ed25519.pub
~~~

서명 개인키는 `build/ki2/keys/`에서만 사용하고 Git이나 패키지 저장소에
복사하지 않는다. 위 curation 출력 디렉터리는 새 경로여야 한다. 이미 생성한
배포본을 갱신할 때는 서명된 이전 릴리스를 보존하고 새 릴리스 경로를 사용한다.

## 검증과 설치

`ki2repo verify`, 116개 패키지 SHA-256 전수 검사, 메타데이터·채널 해시,
중복 이름 없음, 런타임 의존성 0개 누락을 확인했다. 별도 검증 rootfs에서
`ki2ctl update`가 서명을 확인하고 116개 패키지를 읽었다. 실제 VM에
전체 패키지를 설치하거나 업데이트하는 통합 시험은 아직 수행하지 않았다.

저장소 디렉터리 전체를 KIKI OS에 `/srv/kiki-signed`로 복사했다면:

~~~sh
sudo ki2ctl --repo file:///srv/kiki-signed update
sudo ki2ctl --repo file:///srv/kiki-signed install kiki-lightdm --dry-run
~~~

이 결과를 확인한 다음 필요한 패키지만 설치한다. 서명 검증 우회 옵션은 사용하지 않는다.

## 테스트 ISO

`dist/iso/kiki-stage3-v3-installer-x86_64-20260928-r18.iso`는 r17의
6.1.187 rootfs와 위의 서명된 116개 패키지 저장소로 생성했다. ISO에서
추출한 저장소 메타데이터의 Ed25519 서명 및 인덱스의 커널·헤더 6.1.187
핀을 확인했다. ISO manifest의 `package_media.copied`도 116이다.
ISO 자체는 아직 VM 부팅·설치 시험을 통과한 상태가 아니며, 개발용
부팅 미디어이므로 Hyper-V 2세대 테스트에서는 Secure Boot를 꺼야 한다.
