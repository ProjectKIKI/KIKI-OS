# 빌드 서버 임시 KI2 HTTP 저장소

현재 공개 운영 구성은 [빌드 후보 저장소 자동 배포](build-repository-deployment.ko.md)를 따른다.
아래 내용은 먼저 구성했던 SSH 전용 24시간 임시 서비스의 기록이다.

2026-10-28에 최신 로컬 후보 `kiki-admin-20261028-r4`를 빌드 서버에 배치했다.
GNOME 기본 앱과 KIKI 관리자, KI2 CLI를 포함한 x86_64 패키지 224개(약 560MiB)를 제공한다.
기존 서버의 일치하는 패키지 222개를 하드링크로 재사용하고 새 패키지 2개만 전송했다.
서명된 후보의 바이트를 그대로 제공하며 공식 릴리스 승격이나 새 ISO 생성은 수행하지 않았다.

| 항목 | 값 |
|---|---|
| 서버 | `lab@external.terminal-lab.kr:41816` |
| 서버 내부 HTTP | `http://127.0.0.1:8096` |
| 현재 로컬 SSH 터널 | `http://127.0.0.1:18096` |
| systemd 사용자 서비스 | `kiki-temp-repo-20261028.service` |
| 시작 | 2026-10-28 21:24:37 KST |
| 자동 종료 예정 | 2026-10-29 21:24:37 KST (시작 후 최대 24시간) |
| 서버 경로 | `/build-kikios/kiki-build/candidates/mesa-native-20261023/temporary-http-20261028` |

서버의 8096 포트는 루프백에만 바인딩한다. SSH 터널을 연 컴퓨터에서 접근할 수 있다.
외부 익명 공개 주소는 구성하지 않았다. 기존 웹 인증, 포트 80 라우팅, 방화벽, 빌드 작업자는 유지한다.
VM의 `127.0.0.1`은 VM 자신을 가리키므로 호스트에 연 터널 주소를 그대로 VM에 등록하면 안 된다.
24시간 제한은 서비스 종료만 수행하며 검증 자료와 패키지는 삭제하지 않는다.

## 접속

현재 Windows 로컬에서 아래 인덱스 접속을 확인했다.

- [패키지 인덱스](http://127.0.0.1:18096/repo/index.x86_64.json)
- [서명 메타데이터](http://127.0.0.1:18096/repo/metadata.x86_64.json)

터널을 다시 열려면 `terminal-lab.pem`이 있는 디렉터리에서 PowerShell로 실행한다.
명령이 실행 중인 동안 터널을 유지하며 `Ctrl+C`로 닫는다. 현재 터널이 살아 있으면 같은 포트를 중복 사용하지 않는다.

```powershell
ssh -N -T -i .\terminal-lab.pem -p 41816 -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:18096:127.0.0.1:8096 lab@external.terminal-lab.kr
```

Windows 검증 시 WSL의 SSH 프로세스로 로컬 포워딩을 유지했다. Windows/WSL 종료나 연결 단절 시에는 다시 열어야 한다.
다른 클라이언트는 해당 클라이언트에서 별도로 SSH 터널을 구성한다.

## KI2 CLI 등록

신뢰하는 경로로 후보 공개키를 클라이언트의 `/etc/ki2/trust/build-temp.ed25519.pub`에 배치한다.
공개키의 SHA-256은 다음과 같다. HTTP로 받은 키를 대조 없이 곧바로 신뢰하지 않는다.

```text
b6aaadb5491676d154efc62c0bf20a2f6b1026a741d92698d99c75f18390f4f4
```

동일한 Linux 클라이언트에 18096 터널을 연 후:

```sh
sudo ki2ctl repo set http://127.0.0.1:18096 --name build-temp --verify-key /etc/ki2/trust/build-temp.ed25519.pub
sudo ki2ctl update --require-signature
ki2ctl info kiki-admin
ki2ctl info gnome-control-center
```

KIKI 관리자 GUI의 저장소 추가는 HTTPS 정책을 유지한다. 이 임시 HTTP 후보는 CLI에서 검증하여 사용한다.

## 제공 범위와 검증

`tools/ki2http.py`는 기동 전에 Ed25519 메타데이터, 서명에 고정된 인덱스 SHA-256,
224개 패키지의 크기와 SHA-256을 검증한다. 공개 경로는 메타데이터·인덱스·공개키와
인덱스에 명시된 패키지뿐이다. 디렉터리 목록, 경로 이동, 임의 파일, 업로드는 허용하지 않는다.
기동 후 파일의 inode·크기·수정 시간이 달라지면 503을 반환하고 재검증을 요구한다.
서비스는 일반 `lab` 사용자로 실행하며 `NoNewPrivileges`, 메모리·작업 수 제한 및 24시간 제한을 적용했다.

검증 기록:

- `artifacts/temp-http-tests.log`: 서명/인덱스/패키지 변조, 심볼릭 링크, 파일 변경, HTTP 접근 제한 테스트.
- `artifacts/temp-http-server-validation.txt`: 서비스 실행, 루프백 바인딩, 인덱스 해시, 기존 빌드 서비스 상태.
- `artifacts/temp-http-acceptance.json`: 실제 SSH 터널을 통한 CLI 서명 검증 및 관리자·KI2·GNOME 설정·파일 관리자 다운로드.

## 종료와 재기동

SSH 접속 후 일반 `lab` 사용자로 종료:

```sh
systemctl --user stop kiki-temp-repo-20261028.service
```

자동 종료 후 다시 24시간 제공하려면 기존 전용 서비스 정의를 재사용한다.
서버 재부팅으로 사라지는 transient 서비스이므로 재부팅 후에는 아래 명령으로 다시 생성한다.

```sh
base=/build-kikios/kiki-build/candidates/mesa-native-20261023/temporary-http-20261028
systemctl --user reset-failed kiki-temp-repo-20261028.service
systemd-run --user --unit=kiki-temp-repo-20261028 \
  --property=RuntimeMaxSec=24h --property=NoNewPrivileges=yes --property=UMask=0077 \
  --property=MemoryMax=256M --property=TasksMax=64 --property=LimitNOFILE=128 \
  --working-directory="$base/code" /usr/bin/python3 -u "$base/code/ki2http.py" \
  --root "$base/candidate" --public-key "$base/candidate/desktop-installer.ed25519.pub" \
  --client "$base/code/ki2ctl" --port 8096
```

재생성 전에 서비스가 inactive이고 8096 포트가 비어 있는지 확인한다. 서비스 정의가 아직 남아 있으면
`systemctl --user restart kiki-temp-repo-20261028.service`로 같은 제한을 적용하여 다시 시작할 수 있다.
