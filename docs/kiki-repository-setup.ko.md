# KIKI 패키지 저장소 구성 가이드

이 문서는 Stage 2에서 사용할 `.ki2` HTTP 패키지 저장소를 구성하는 방법을
정리한다. 여기서 말하는 저장소는 소스 코드를 보관하는 Gitea/Git 저장소가 아니라,
KIKI OS가 `ki2ctl`로 패키지를 내려받는 정적 HTTP 저장소다.

## 기본 개념

KIKI 패키지 저장소는 단순한 정적 파일 트리다.

```text
publish/
  manifest.json
  repo/
    index.x86_64.json
  packages/
    base-files-0.1.0-17.x86_64.ki2
    systemd-255.7-2.x86_64.ki2
    ...
  iso/
    kiki-stage2-installer-x86_64-20260526-rev42.iso
    ...
```

`repo/index.x86_64.json`은 패키지 이름, 버전, 릴리스, 파일명, 크기, sha256,
런타임 의존성을 담는다. `ki2ctl`은 이 인덱스를 내려받은 뒤 필요한 `.ki2`
파일을 HTTP로 가져와 대상 rootfs에 추출한다.

현재 Stage 2 초반 기준으로 저장소 서명은 아직 구현 전이다. 인덱스의 sha256으로
패키지 파일 무결성은 검증하지만, 저장소 메타데이터 자체의 서명 검증은 이후
작업으로 남겨둔다.

## 빌드 서버 준비

빌드 서버 또는 WSL/Rocky 9 빌더에서 패키지를 만든다.

```bash
python3 tools/ki2build.py validate --profile distro/profiles/minimal-systemd.toml --max-packages 64
python3 tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python3 tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --allow-unpinned
```

패키지 산출물은 다음 위치에 생성된다.

```text
dist/ki2/packages/x86_64/*.ki2
```

패키지를 추가하거나 재빌드한 뒤에는 저장소 인덱스를 반드시 다시 생성한다.

```bash
python3 tools/ki2build.py repo-index
```

인덱스 산출물:

```text
dist/ki2/repo/index.x86_64.json
```

Stage 2부터는 저장소 운영 메타데이터도 함께 생성할 수 있다.

```bash
python3 tools/ki2repo.py generate \
  --name kiki-os \
  --title "KIKI OS Package Repository" \
  --channel stage2 \
  --base-url http://repo.example.internal:8080
```

생성되는 메타데이터:

```text
dist/ki2/repo/index.x86_64.json
dist/ki2/repo/metadata.x86_64.json
dist/ki2/repo/channels.json
```

`metadata.x86_64.json`은 패키지 개수, 전체 크기, tier별 개수, 최신 패키지 목록,
ISO 산출물 목록, 저장소 보안 상태를 기록한다. `channels.json`은 `stage2`,
`testing`, `stable` 같은 릴리스 채널이 어떤 인덱스와 메타데이터를 가리키는지
기록한다.

요약 확인:

```bash
python3 tools/ki2repo.py summary
```

## 개발용 임시 저장소

개발 중에는 `dist/ki2`를 그대로 HTTP로 열 수 있다.

```bash
python3 -m http.server 8080 --directory dist/ki2
```

이 방식의 URL 구조는 다음과 같다.

```text
http://SERVER:8080/repo/index.x86_64.json
http://SERVER:8080/packages/x86_64/<package>.ki2
```

`ki2ctl`은 `packages/x86_64/` 경로를 지원하므로 개발 테스트에 바로 사용할 수
있다.

## 운영용 publish 트리

운영 또는 장기 테스트용으로는 `tools/ki2publish.py`로 배포 트리를 만든다.

```bash
python3 tools/ki2publish.py --target /srv/www/kiki
```

기본 산출물:

```text
/srv/www/kiki/
  manifest.json
  repo/index.x86_64.json
  packages/*.ki2
  iso/*.iso
```

`ki2publish.py`는 다음 디렉터리를 복사한다.

```text
dist/ki2/repo/                 -> <target>/repo/
dist/ki2/packages/x86_64/      -> <target>/packages/
dist/iso/                      -> <target>/iso/
```

새 패키지를 빌드한 뒤 운영 저장소를 갱신하는 기본 순서는 다음과 같다.

```bash
python3 tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --allow-unpinned
python3 tools/ki2repo.py generate --channel stage2 --base-url http://repo.example.internal:8080
python3 tools/ki2publish.py --target /srv/www/kiki
```

## HTTP 서버 예시

가장 단순한 테스트 서버:

```bash
cd /srv/www/kiki
python3 -m http.server 8080
```

nginx 예시:

```nginx
server {
    listen 8080;
    server_name repo.example.internal;

    root /srv/www/kiki;
    autoindex off;

    location / {
        try_files $uri =404;
    }
}
```

운영 환경에서는 저장소 서버를 사설망, VPN, 방화벽 또는 인증 리버스 프록시 뒤에
둔다. Stage 2 초반에는 저장소 서명이 없으므로, 신뢰할 수 없는 네트워크에 직접
노출하지 않는다.

## KIKI OS에서 저장소 등록

설치된 KIKI OS에서 저장소를 등록한다.

```bash
sudo ki2ctl repo set http://repo.example.internal:8080
sudo ki2ctl repo list
```

저장소 설정 파일은 다음 위치에 저장된다.

```text
/etc/ki2/repos.d/default.repo
```

예시:

```json
{
  "name": "default",
  "schema": "ki2-repo-config-v1",
  "url": "http://repo.example.internal:8080"
}
```

인덱스를 내려받는다.

```bash
sudo ki2ctl update
```

내려받은 인덱스는 다음 위치에 저장된다.

```text
/var/lib/ki2/repos/default/index.x86_64.json
```

## 패키지 조회와 설치

패키지 검색:

```bash
ki2ctl search curl
ki2ctl info curl
```

설치 계획 확인:

```bash
sudo ki2ctl install curl --dry-run
```

설치:

```bash
sudo ki2ctl install curl
```

설치된 패키지 기록:

```bash
ki2ctl list
cat /var/lib/ki2/installed.json
```

설치와 업그레이드는 트랜잭션으로 기록된다.

```text
/var/lib/ki2/transactions/<transaction-id>.json
```

트랜잭션 파일에는 작업 종류, 대상 패키지, 상태, 이벤트, rollback을 위한 백업
목록이 기록된다. 설치 중 오류가 나면 `ki2ctl`은 변경된 파일과 설치 DB를 가능한
범위에서 되돌리고 트랜잭션 상태를 `rolled-back`으로 남긴다.

패키지 캐시는 다음 위치에 저장된다.

```text
/var/cache/ki2/packages/x86_64/
```

`ki2ctl`은 설치 전에 payload 경로를 검사한다.

- 다른 설치 패키지가 소유한 파일은 덮어쓰지 않는다.
- 기존에 존재하지만 어떤 패키지에도 기록되지 않은 파일은 덮어쓰지 않는다.
- 같은 패키지의 재설치나 업그레이드는 허용한다.
- 디렉터리는 기존 디렉터리와 공존할 수 있다.

## 업그레이드

저장소를 갱신한 뒤 업그레이드 후보를 확인한다.

```bash
sudo ki2ctl update
sudo ki2ctl upgrade --dry-run
```

전체 업그레이드:

```bash
sudo ki2ctl upgrade
```

특정 패키지만 업그레이드:

```bash
sudo ki2ctl upgrade ki2ctl
```

현재 `upgrade`는 설치된 패키지 DB와 저장소 인덱스의 최신 버전을 비교해서 더 높은
버전/릴리스가 있을 때 다시 설치한다. Stage 2 초반 기준으로 파일 충돌 탐지와
기본 트랜잭션 rollback은 들어갔지만, systemd hook, pre/post script, 완전한
스냅샷 rollback은 아직 남은 작업이다.

## 설치 중 대상 rootfs에 적용

설치기 또는 복구 환경에서 `/mnt/target`에 패키지를 설치할 수 있다.

```bash
ki2ctl --root /mnt/target repo set http://repo.example.internal:8080
ki2ctl --root /mnt/target update
ki2ctl --root /mnt/target install openssh
```

이 방식은 네트워크 설치, disconnected mirror 설치, 복구용 패키지 재설치의 기반이
된다.

## disconnected 저장소

인터넷이나 중앙 저장소가 없는 환경에서는 publish 트리를 내부 파일 서버, ISO,
USB, 폐쇄망 mirror로 옮긴다.

권장 절차:

```bash
python3 tools/ki2build.py repo-index
python3 tools/ki2publish.py --target dist/publish
tar -C dist -czf kiki-repo-x86_64.tar.gz publish
```

대상 네트워크에서 압축을 풀고 HTTP 서버로 제공한다.

```bash
mkdir -p /srv/www/kiki
tar -C /srv/www/kiki --strip-components=1 -xzf kiki-repo-x86_64.tar.gz
python3 -m http.server 8080 --directory /srv/www/kiki
```

## 저장소 갱신 체크리스트

1. 패키지 레시피 또는 소스 수정
2. 필요한 패키지 빌드
3. `python3 tools/ki2repo.py generate --channel stage2 --base-url http://repo.example.internal:8080`
4. `python3 tools/ki2publish.py --target /srv/www/kiki`
5. 클라이언트에서 `sudo ki2ctl update`
6. `sudo ki2ctl upgrade --dry-run`
7. 문제가 없으면 `sudo ki2ctl upgrade`

## Stage 2 남은 저장소 작업

- 저장소 인덱스 서명과 공개키 배포
- 패키지 파일 서명 또는 manifest 서명
- 디렉터리 정리까지 포함하는 완전한 rollback
- pre/post install/remove hook 정책
- release channel: `stage1-final`, `stage2`, `testing`, `stable`

## Stage 2 저장소 서명 메모

Stage 2부터는 `tools/ki2repo.py`가 저장소 운영 메타데이터와 서명 검증 흐름을 함께
관리한다. 현재 구현은 개발용 `hmac-sha256` 방식이다. 운영 배포에서는 개인키를
서버 밖에 보관하고 공개키 기반 서명으로 바꾸는 것이 맞다.

서명키 생성:

```bash
python3 tools/ki2repo.py keygen --output build/ki2/keys/stage2-repo.hmac
```

서명된 메타데이터 생성:

```bash
python3 tools/ki2repo.py generate \
  --channel stage2 \
  --base-url http://repo.example.internal:8080 \
  --sign-key build/ki2/keys/stage2-repo.hmac
```

검증:

```bash
python3 tools/ki2repo.py verify --key build/ki2/keys/stage2-repo.hmac
```

클라이언트에서는 다음처럼 검증 업데이트를 수행한다.

```bash
sudo ki2ctl update --verify-key /etc/ki2/trust/stage2-repo.hmac
```

중요: `build/ki2/keys/stage2-repo.hmac`는 publish 대상이 아니다. HTTP 저장소에
함께 올리면 서명의 의미가 사라진다.

## Stage 2 테스트 ISO

2026-05-26 기준 테스트용 설치 ISO:

```text
dist/iso/kiki-stage2-test-installer-x86_64-20260526.iso
size:   879187968 bytes
sha256: 79EBAC0C2DE64145D6DF1351D52027CFF450847DF91507FDE2117FA319EF97EF
```

생성 명령:

```bash
python3 tools/ki2bootiso.py \
  --profile bootstrap-stage1 \
  --mode installer \
  --no-hyperv-vhdx
```

이후 새 ISO는 기본적으로 `YYYYMMDD-revN` suffix를 사용한다. 예:

```text
dist/iso/kiki-stage2-installer-x86_64-20260526-rev42.iso
```

기본 release 이름은 저장소 metadata의 `channel` 값이다. 부팅 프로필은
`bootstrap-stage1`이어도 Stage 2 저장소를 담는 설치 ISO는 `stage2` 이름을 쓴다.

이 ISO는 stage-1 installer ISO이며 `/kiki/repo`, `/kiki/packages/x86_64` 아래에
현재 Stage 2 저장소 payload를 포함한다.
- mirror 동기화와 보존 정책
