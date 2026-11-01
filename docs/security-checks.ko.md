# CVE 알림과 OpenSCAP 설정 검사

빌드 콘솔의 `/updates/security`에서 서명된 패키지 스냅샷의 CVE 조회 결과·조회 범위·알림을 확인한다. `/updates`와 후보 상세 화면에도 연결돼 있다. 알림은 콘솔 내 알림이며 이메일·메신저 전송은 하지 않는다.

## CVE 조회

`tools/ki2security.py`는 OSV, NVD, CISA KEV의 공식 HTTPS API를 사용한다. `deploy/security/mappings.json`을 release worker의 `security-mappings.json`으로 배포한다. 원본 출처 접두사와 일치하는 검토된 프로젝트만 조회하며, 보존 출처 감사 자료도 사용한다. KI2 release를 원본 버전으로 보내지 않는다.

원본·후보마다 별도 결과를 `updates/security/<snapshot>.json`에 저장한다. 새로운 후보는 기존 작업 대기열의 `update-security` 작업으로 확인하고, 기준 스냅샷은 기본 6시간 주기로 재확인한다. 외부 API 캐시도 6시간이다. OSV는 페이지 토큰을 따라가고, NVD는 100개 단위로 최대 50페이지를 조회하며 공용 호출 사이에 6.5초 이상 간격을 둔다. 제한을 넘거나 일부 페이지가 실패하면 조회 실패로 남긴다. 대용량 OSV 커널 응답은 사용하지 않고 Linux는 NVD로 조회한다.

NVD의 Expat CPE는 공식 CVE-2024-45490 데이터의 `libexpat_project:libexpat` 식별자로 대조했다. 매핑 파일을 바꿀 때에는 출처와 실제 공급자 식별자를 함께 확인한다. 프로젝트별 지원 범위가 다르므로 신규 패키지는 매핑 검토가 필요하다.

판정은 영향 가능, 지원 데이터에서 일치 없음, 매핑 필요, 조회 실패로 나눈다. 조회 실패 시 기존 경고를 보존한다. 별칭이 같은 CVE는 통합하며, CVE·패키지 해시·심각도·KEV가 바뀌면 새 콘솔 알림을 만든다. 동일 결과 재조회는 알림을 중복 생성하지 않고 읽음 상태를 유지한다. KEV 공급자 실패도 별도로 표시한다.

버전 매칭만으로 취약점 영향을 확정하거나 백포트 수정을 인정하지 않는다. 공개 공지·빌드 옵션·패치 근거를 검토해야 한다. 현재는 정보 제공 정책이며 CVE 점수만으로 안정 채널을 차단하지 않는다. 특히 미매핑·조회 실패를 안전하다고 판정하지 않는다.

`/updates/security/sbom?base=<snapshot>`은 CycloneDX 1.6 JSON을 반환한다. 패키지 해시, 원본 버전, KI2 release, 레시피 지문과 보관된 소스 정보를 포함한다. 저장소 전체 인벤토리이며 설치 VM의 구성은 서명된 VM 보고서의 `packages`가 기준이다.

## OpenSCAP 패키지

`distro/recipes/security-audit.json`은 libxslt 1.1.45, XMLSec 1.3.13, OpenSCAP 1.4.6을 고정한다. `deploy/security/build-inputs.json`에 공식 소스 주소·SHA-256을 보관한다. 초기 소스 확보 때 libxslt의 공식 SHA-256과 OpenSCAP의 공식 SHA-512 목록도 대조했다. XMLSec은 HTTPS 공식 배포 파일의 SHA-256 고정이며 원저자 서명 검증을 주장하지 않는다.

`tools/build_security_audit.py`는 기존 KIKI SDK를 복사해 빌드한다. 기존 SDK와 안정 저장소를 수정하지 않는다. 실제 테스트는 KIKI libxml2 2.15.4·OpenSSL 3.3.1을 사용했다. 초기 실행에서 발견한 불필요한 YAML 프로브 의존성을 제외했고, libgcrypt·util-linux의 링크 의존성을 명시했다. YAML 프로브·RPM·SCE·원격 실행 도구는 이 구성의 지원 범위가 아니다.

```sh
python3 tools/build_security_audit.py --sdk /path/to/kiki-sdk \
  --work /path/to/new-security-build --inputs deploy/security/build-inputs.json \
  --tools /path/to/repository/tools
```

`kiki-security-content`는 별도 자체 소스 패키지다. 선택형 `security-audit` 그룹이 엔진·정책을 설치한다. 그룹과 패키지가 있는 서명 저장소를 먼저 등록·동기화해야 한다. 원래 데스크톱 스냅샷에 새 패키지가 있다고 가정하지 않는다.

```sh
sudo ki2ctl group install security-audit
sudo /usr/libexec/kiki-security-scan
```

원래 관리자 앱의 진단 및 복구 화면에는 검사 계획 버튼을 추가했다. 고정된 polkit 작업만 실행하며 사용자 지정 정책·명령·경로를 받지 않는다. 새 버튼은 갱신된 kiki-admin 패키지가 필요하다.

## 정책과 결과

정책은 `/usr/share/kiki-security/`의 XCCDF·OVAL·CPE 세 파일이다. `tools/generate_security_content.py`로 재생성할 수 있다. KIKI OS 식별을 별도로 검사하며 다른 배포판으로 가장하지 않는다. 세 파일의 이름과 바이트를 묶은 SHA-256이 정책 식별자다.

현재 9개 규칙: passwd·shadow 소유권/권한, UID 0 중복, root 컨텍스트의 SSH 직접 로그인·빈 암호 인증, 실행 중 하드링크/심볼릭 링크 보호, 지원 시간 동기화 서비스, nftables input 체인의 기본 차단 정책이다. SSH는 `sshd -T -C user=root,host=localhost,addr=127.0.0.1`의 유효 설정을 사용한다. 다른 원격 주소·사용자의 Match 조건은 별도 확장 대상이다.

검사 결과는 pass·fail·error·unknown·notapplicable·notchecked를 보존한다. 빠진 도구는 관측 오류로 표시한다. 규칙 통과 수만으로 전체 OS의 보안을 보증하지 않으며 CIS/STIG 인증을 의미하지 않는다. 자동 수정은 실행하지 않는다.

JSON과 원본 XCCDF XML은 root 전용 `/var/lib/kiki-security/`에 보관한다. 수집하는 유효 설정은 점검에 필요한 값뿐이며 암호·키 내용은 수집하지 않는다. 공개 HTTP 패키지 저장소에는 검사 보고서를 게시하지 않는다.

## VM 업데이트 연동

release worker의 `updates/config.json`의 `security.scap`에 `profile`, 정책 `sha256`, 필수 규칙 ID 목록을 지정한다. 검증 요청 시 이 정책을 후보 요청에 복사한다. 검증 대상 VM에는 사전에 보안 검사 그룹이 설치돼 있어야 하며 설치 인벤토리가 후보 기준 스냅샷과 일치해야 한다.

Windows 검증기는 업데이트 적용 전과 정상·복구 부팅 후 OpenSCAP을 실행한다. 결과는 기존 nonce·후보 해시·설치 인벤토리에 연결된 보고서에 들어가 Ed25519로 서명된다. 서버는 프로파일·정책 해시·필수 규칙·실행 증거를 확인한다. 검사 도구 실행 실패나 결과 누락은 검증 통과를 차단한다. 설정 불일치는 현재 경고 정책으로 보존하며 전후 결과를 화면에서 확인한다. 안정 승격은 계속 수동이다.

로컬 소스의 보조 입력도 각각 고정된 아카이브로 보관한다. 관리자 후보 빌드 중 발견한 누락 의존성 때문에, `build_prerequisites.kiki-admin`에 `linux-headers`를 지정했다. 기준에 없는 pkgconf·커널 헤더는 공식 소스를 고정해 빌드 전용으로 사용하며 업데이트 결과에 설치하지 않는다. 헤더 버전은 기준 커널과 대조한다.

## 실제 시험 중 확인한 결과

전용 VM `kiki-gnome-apps-r3-20261028`에 서명된 선택 패키지를 KI2로 설치하고 재부팅했다. OpenSCAP 실행과 XCCDF·OVAL 스키마 검증을 확인했다. 처음 9개 규칙 결과는 통과 6, 설정 불일치 2, 관측 오류 1이었다. SSH root 로그인 정책과 시간 동기화가 불일치했고, nftables 도구 부재가 오류로 표시됐다. 자동으로 해당 설정을 변경하지 않았다.

하드링크 보호 값을 일시적으로 0으로 바꾸는 실패 유도 시험에서 해당 규칙이 fail로 바뀌었고, finally에서 값을 복구한 뒤 pass로 돌아오는 것을 확인했다.

최종 후보 `6c038762bdd044caa55fbccd59edc928`은 기존 빌드 대기열의 `20261028-191554-8868`에서 kiki-admin 0.1.0-6과 ki2ctl 0.1.0-30을 실제 빌드했다. 기존 Windows 예약 작업이 nonce `3e0d1e051a1545b18f5b38373e872a58` 요청을 처리했고 종료 코드는 0이었다. 설치된 211개 패키지, 오프라인 적용·설정 보존·서비스·HTTPS·복구/기본 부팅·GNOME Wayland 로그인 화면·OpenSCAP 실행을 모두 확인했다. 대화형 사용자 로그인과 앱 직접 조작은 자동 검증 범위에 포함하지 않는다.

업데이트 전후 9개 규칙은 각각 통과 6·설정 불일치 2·관측 오류 1로 같았다. 서버에서 보고서 서명·정책 해시·규칙 목록을 검증하고 후보를 `validated`로 확인했다. 보고서 SHA-256은 `ea2e46ebdf19dfb84939aaa9313203502aa6f0bd3e2f83c3331daf6e843d70df`이다. 정책 SHA-256은 `d5a06f768b2fdd897e3354a7e6cb4d980559f0c4fcf33b45bffa8c075df33d8a`다. 실제 갱신된 관리자 백엔드의 검사 계획·실행 경로와 security-audit 그룹도 확인했다.

공개 후보 저장소의 Ed25519 서명·인덱스를 다시 검증했고, CycloneDX SBOM 228개의 패키지 해시가 스냅샷과 일치했다. 익명 CVE API는 401, 공개 경로의 비공개 검사 보고서는 404로 차단됐다. 안정 채널은 `update-55f351d06ff14a20a8746e49f5e2e7de`로 유지했다.

최종 기준 CVE 조회는 224개 중 16개의 매핑을 사용해 완료됐으며, 영향 가능 12·일치 없음 4·조회 실패 0·추가 매핑 필요 208개였다. Curl은 OSV 공식 문서의 Git 조회 형식을 사용했고 NVD와 통합해 CVE-2024-8096의 원본 수정 경계 8.10.0과 CVSS 6.5 표시를 확인했다. 조회 완료와 영향 확정은 구분한다.

관련 Python 테스트는 CVE 15개, 업데이트·기존 라이브러리 47개, 관리자 14개, 인증 44개가 통과했다. 설치 카탈로그 재생성 일치·Python 구문·`git diff --check`도 확인했다. 웹은 전용 Browser 플러그인이 없어 내장 브라우저/CUA로 데스크톱 1157×1228에서 검사했다. CVE 수동 조회·검색·상세 펼침, VM 요청·보고서 확인을 실제 조작했고 빈 화면·오류 화면·관련 콘솔 경고/오류가 없었다. 모바일 화면은 검증하지 않았다.
