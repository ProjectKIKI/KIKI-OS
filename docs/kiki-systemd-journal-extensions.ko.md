# 선택형 systemd journal 확장 패키지

2026-09-28 기준 기존 `systemd 255.7-5` KI2에는 `systemd-journal-gatewayd`,
`systemd-journal-remote`, `systemd-journal-upload`가 없다. 기본 OS나 현재 ISO에
이 서비스를 자동 추가하지 않는다.

## 완료된 후보

- GNU `libmicrohttpd 1.0.10-1`: GnuTLS HTTPS 지원으로 KIKI sysroot에서 빌드.
  원본 `COPYING` 포함, `libmicrohttpd.so.12`의 GnuTLS 링크와 RPATH 부재 확인.
- `systemd-journal-gatewayd 255.7-1`: 기존 systemd 255.7과 동일한 공식 소스와
  KIKI 패치를 사용해 별도 KI2로 빌드. 서비스, 소켓, 탐색 HTML 포함.
  빌드 RPATH를 `chrpath`로 제거한 뒤 기존 KIKI systemd 공유 라이브러리와
  대상 로더의 `--version` 실행 및 ELF 링크 검사를 통과했다.
- `systemd-journal-transport 255.7-1`: `systemd-journal-remote`와
  `systemd-journal-upload` 실행 파일, 서비스, remote 소켓, 설정 샘플 및
  remote 전용 sysusers 파일을 담았다. 기존 KIKI systemd 공유 라이브러리로
  두 실행 파일의 `--version` 명령 및 ELF 링크 검사를 통과했다.

세 패키지는 `dist/ki2/systemd-journal-candidate-01`의 **후보 저장소**에만
두었다. Stage 3 Ed25519 서명과 공개키 검증, 인덱스 및 패키지 SHA-256
대조를 통과했다. 이 저장소는 기존 systemd와 나머지 의존 패키지를 포함하지
않으므로 단독 설치용 완전한 배포 채널이 아니다.

`ki2ctl` 그룹 카탈로그 소스에는 `systemd-journal-extensions` 선택형 그룹을
추가했다. 게이트웨이와 송수신 패키지를 선택하되 서비스를 자동 활성화하지
않는다. 아직 후보 패키지가 기본 저장소에 없고 `ki2ctl` 패키지도 재빌드하지
않았으므로 기존 ISO/설치 시스템에서 이 그룹을 바로 설치할 수는 없다.

## 노출 방지

패키지 설치만으로 활성화되는 `sockets.target.wants` 링크가 없다. 소켓을
관리자가 직접 활성화하더라도 기본 바인딩은 `127.0.0.1:19531`이다.
원본의 모든 주소 바인딩(`ListenStream=19531`)을 후보 패키지에서 바꿨다.
remote 수신 소켓 역시 자동 활성화하지 않고, 관리자가 직접 켤 때에도
`127.0.0.1:19532`로만 바인딩한다. upload 서비스는 URL이 주석 처리된
설정 샘플만 제공하며 자동 활성화하지 않는다.
원격 접근을 열려면 인증·TLS·접근 제어·로그 민감정보 정책을 따로 설계해야
한다. HTTP 게이트웨이를 공용 네트워크에 그대로 노출하지 않는다.

## 남은 작업

- 격리 VM에서 실제 journal 요청, systemd 소켓 활성화/비활성화, 서비스
  샌드박스, 로그 열람 권한 및 원격 업로드 TLS 연결을 시험하지 않았다.
  이 검증을 통과한 뒤 완전한 서명 저장소에 병합하고 `ki2ctl`을 재빌드한다.
  그전에는 후보를 ISO에 포함하지 않는다.
- `systemd-importd`는 기존 `systemd` 패키지에 없는 신규 확장 후보이나
  의존성·파일 충돌·VM 기능 검증 후 별도 패키지로 진행한다.
- 빌드 호스트에는 `chrpath`가 필요하다. 이번 빌드에서는 Rocky RPM을
  `/tmp`에만 추출해 사용했고 호스트 패키지로 설치하지 않았다.

재현용 정적 시험:

```sh
KIKI_TEST_JOURNAL_GATEWAY=1 python3 tools/test_systemd_journal_gateway_runtime.py -v
KIKI_TEST_JOURNAL_TRANSPORT=1 python3 tools/test_systemd_journal_transport_runtime.py -v
python3 tools/ki2repo.py --repo-dir dist/ki2/systemd-journal-candidate-01/repo \
  verify --key build/ki2/keys/stage3-v3-repo.ed25519.pub
```
