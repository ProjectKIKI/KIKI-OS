# KIKI 관리자

GNOME 데스크톱에서 KIKI 고유의 시스템·KI2·진단 작업을 수행하는 GTK4 /
Libadwaita 앱이다. GNOME 설정, Nautilus, Console은 계속 기본 앱으로 사용한다.

## 화면과 동작

- **시스템 개요**: OS·커널·호스트 이름, 실제 파일시스템 여유 공간, 실패한
  시스템 서비스, 설치 패키지 수와 캐시된 목록 기준 업데이트 수.
- **패키지**: 설치 패키지 검색, 환경 그룹의 구성·등록 여부, 그룹 설치·갱신,
  저장소 목록 동기화와 업데이트 계획. 현재 저장소에 필요한 패키지가 없는
  그룹은 정보 아이콘으로 이유를 안내한다.
- **저장소**: 공급 주소, 공개키 설정, 목록 동기화 시각. HTTPS 주소와
  `/etc/ki2/trust`에 설치한 Ed25519 공개키로 저장소를 추가·수정할 수 있다.
  기존 설치 미디어의 로컬 저장소도 조회·동기화할 수 있다.
- **진단 및 복구**: 여유 공간 부족, 실패 서비스, 저장소 미설정, 미완료
  KI2 트랜잭션·후처리 안내. 사용자 로그는 바로 읽고 시스템 로그는 인증 후
  읽는다. 로그 범위는 이번 부팅, 최근 200줄이다. 실패 서비스만 다시 시작한다.

변경 계획을 확인한 뒤 **인증하고 적용**을 선택한다. 전체 앱은 사용자 권한으로
실행하며 고정된 Polkit helper만 `auth_admin` 인증으로 호출한다. helper는 임의
명령·셸·대상 루트 경로를 받지 않는다. 검토 후 DB·저장소·공개키·목록이 바뀌면
기존 계획은 거부하고 새 검토를 요청한다. GUI와 KI2 CLI는 같은 변경 잠금을 쓴다.

컨테이너·Kubernetes·AI 관리는 후속 기능으로 표시하며 실행 동작은 제공하지 않는다.
GUI/CLI 관리 기능의 추가가 해당 환경의 패키지 공급을 자동으로 추가하지는 않는다.

## 공통 CLI

```sh
kiki-adminctl snapshot
kiki-adminctl diagnose
kiki-adminctl logs
kiki-adminctl logs NetworkManager.service
kiki-adminctl plan refresh
kiki-adminctl plan upgrade
kiki-adminctl plan group-install desktop-gnome
kiki-adminctl plan group-upgrade desktop-gnome
kiki-adminctl plan hooks
kiki-adminctl plan system-logs NetworkManager.service
kiki-adminctl plan restart failed-example.service
```

모두 JSON을 출력한다. `ok: false`와 0이 아닌 종료 코드는 실패다. 조회 실패를
정상 상태로 취급하지 않고 `warnings`에 기록한다. 계획의 토큰은 권한을 부여하는
인증 정보가 아니라 검토한 시스템 상태를 식별하는 해시다.

설치기로 구성했지만 KI2 그룹 소유권이 기록되지 않은 환경은 패키지의 실제 구성
상태와 그룹 등록 여부를 구분한다. **그룹 등록 계획**으로 기존 패키지와 의존성을
검토하고 소유권을 기록할 수 있다.

## 빌드

일반적인 GTK 개발 환경에서는 `make`, 패키징은 `make DESTDIR=/path install`을 쓴다.
KIKI ABI용 네이티브 빌드는 보존한 GNOME SDK와 서명된 기존 후보를 사용한다.

```sh
python3 tools/build_kiki_admin.py \
  --sdk /path/to/kiki-sdk \
  --baseline dist/ki2/gnome-native-apps-20261028-r3 \
  --work /path/to/new-admin-work \
  --output dist/ki2/new-admin-candidate \
  --sign-key /path/to/candidate-signing-key
```

이전 후보는 변경하지 않는다. 기존 공개키·서명·기준 인덱스·패키지 해시를 검증한
뒤 관리자와 KI2를 빌드한다. 동일한 불변 패키지는 가능한 경우 하드링크로 재사용한다.
저장 공간 부족 등으로 내보내기만 중단됐다면 같은 인수에 `--resume-export`를
추가해 이미 서명한 작업 저장소에서 이어간다. 완료된 후보는 다시 쓰지 않는다.
개인 서명키는 후보에 복사하지 않는다. 이 도구는 ISO를 생성하지 않는다.

## 검증

```sh
python3 -m unittest discover -s tools -p test_kiki_admin.py -v
python3 -m unittest discover -s tools -p 'test_ki2ctl*.py'
make -C cmd/kiki-admin ui-test
cmd/kiki-admin/ui-test /path/to/snapshot.json /path/to/png-output
```

`ui_test.c`는 실제 스냅샷 JSON과 결과 디렉터리를 인수로 받는다. GTK 런타임에서
네 화면, 패키지 검색, 변경 검토·닫기, 작은 창, 작업 중 닫기 방지를 검사하고
PNG를 저장한다. 실제 Polkit 암호 입력은 자동화하지 않는다. 테스트의 root helper
직접 실행과 Polkit 정책 검사는 사용자 인증 다이얼로그 검증과 구분한다.
