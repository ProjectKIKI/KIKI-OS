# CVE 확인 및 OpenSCAP 설정 검사 도입 검토

검토일: 2026-10-29. 이 문서는 최초 구현 제안이다. 이후 구현·실제 시험 현황은 [보안 검사 운영 문서](security-checks.ko.md)에 기록한다. 사용자 요청의 OpenSCAPE는 OpenSCAP을 뜻하는 것으로 해석했다.

## 결론과 현재 코드의 연결점

두 기능 모두 도입할 수 있다. CVE는 빌드 서버에서 패키지·소스 식별자를 대상으로 조회하고, 설정은 대상 KIKI OS에서 OpenSCAP 정책으로 검사한다. 기존 업데이트 화면과 KIKI 관리자가 결과를 표시하고, 기존 VM 검증기가 후보 적용 전후의 차이를 수집하는 구성을 권장한다.

현재 확인한 근거:

- `tools/ki2updates.py`의 `baseline()`은 서명과 인덱스 해시를 검사한다. `source_rows()`는 원본 버전·주소를 만들지만 CVE 식별자, 커밋, 패치 판정은 제공하지 않는다.
- `tools/ki2origins.py`에는 소스 종류·주소·해시와 출처 검증 정보가 있다. 이를 원본 프로젝트 매핑의 근거로 사용할 수 있다.
- `tools/ki2updatevm.py`에는 패키지 인벤토리, 재부팅, 서비스, GUI, 서명 보고서가 있다. 현재 CVE·OpenSCAP 검사는 없다.
- `distro/sources/kiki-admin/usr/libexec/kiki-admin-backend.py`의 `diagnose()`는 디스크·서비스·저장소·트랜잭션을 진단한다. 보안 설정 검사와 결과 조회를 추가할 수 있다.
- `distro/sources/base-files/etc/os-release`는 `ID=kiki`를 사용한다. RPM·DEB 기반 배포판으로 가장해서 검사하지 않는다.
- 레시피 검색에서 OpenSCAP·libxslt·xmlsec 레시피는 발견하지 못했다. libxml2·OpenSSL·curl·ACL·libcap 레시피는 있으며 PCRE2는 Kubernetes 레시피에 있다. 레시피 존재가 현재 데스크톱 설치를 보장하지는 않는다.

## CVE 조회 설계

1. 서명된 저장소 스냅샷과 실제 설치 인벤토리를 각각 입력으로 사용한다. 현재 저장소 224개와 VM에 설치된 207개를 구분한다. ISO에 포함되지 않은 패키지를 설치 시스템의 취약점으로 집계하지 않는다.
2. 패키지마다 검토된 원본 프로젝트 매핑을 둔다. `upstream_name`, `upstream_version`, `repository_url`, 확인 가능한 `commit`·태그, OSV 식별자, CPE, 소스·레시피·패키지 SHA-256, 패치 근거를 저장한다. 이름 유사도만으로 확정하지 않는다.
3. KI2 `release`와 원본 버전을 분리한다. 예를 들어 `2.3.2-7`의 자체 릴리스 증가만으로 상위 프로젝트 CVE가 수정됐다고 판단하지 않는다. 백포트는 실제 패치·커밋 또는 검토된 근거에 연결한다.
4. OSV의 지원 생태계·Git 조회와 NVD의 CPE·버전 조건, 원저자 보안 공지를 조합한다. 자체 KI2 패키지를 Rocky·Debian 패키지로 조회하지 않는다. 범용 PURL을 만들었다고 OSV가 해당 프로젝트를 지원하는 것은 아니다.
5. Linux·linux-headers처럼 같은 원본을 쓰는 바이너리는 원본 단위로 조회를 공유하되, 영향을 받는 바이너리를 각각 표시한다. 자체 코드·보존 외부 파일·내장 라이브러리도 별도 식별하며 자동 매핑이 없으면 미확인으로 남긴다.
6. CVE 별칭을 통합하고, 영향 범위·수정 버전·CVSS 출처와 버전·공식 공지·조회 시각·판정 근거를 보관한다. CISA KEV는 실제 악용 여부를 나타내는 우선순위 정보로 사용한다. CVSS나 CPE 정보가 없는 CVE도 버리지 않는다.

표시 상태는 `영향 확인`, `영향 가능`, `수정 확인`, `비해당`, `매핑 필요`, `조회 실패/오래된 결과`로 구분한다. 취약점 검색 결과가 없더라도 모든 패키지가 검사됐다는 뜻은 아니다. 매핑·조회 완료 수와 미확인 수를 함께 표시한다. 예외에는 근거·작성자·만료일을 남기며, 만료 또는 입력 해시 변경 시 다시 검토한다.

기존 release worker에 캐시·호출 제한·재시도·페이지네이션을 둔 작업을 연결한다. 제안 주기는 기존 원본 버전 확인과 같은 6시간이며, 지금 활성화된 작업은 아니다. 신규 CVE, 중요도·KEV 변경, 수정 확인만 중복 제거해 빌드 콘솔에 알린다. 같은 버전에도 새 CVE가 공개될 수 있으므로 버전 변경만 조회 조건으로 삼지 않는다. 외부 API에는 공개 프로젝트 정보만 보내며 시스템 설정·계정·키를 보내지 않는다.

## OpenSCAP 패키지와 KIKI 정책

OpenSCAP은 검사 엔진이며 실행할 XCCDF/OVAL 정책이 별도로 필요하다. 공식 빌드 설정에는 PCRE2, libxml2, libxslt, XMLSec, OpenSSL 요구 사항이 있다. 도입 시 정식 릴리스와 소스 해시를 고정하고, 현재 libxml2 2.15 계열 및 KIKI 툴체인과의 빌드·실행 호환성을 시험해야 한다. 이 검토에서 호환 빌드 성공을 확인한 것은 아니다.

제안 패키지 그룹은 선택형 `security-audit`이고, 검사 엔진과 버전이 고정된 `kiki-security-content`를 분리한다. XML 스키마·XSL·프로브·필요 라이브러리를 함께 패키징한다. CMake 옵션에 따라 빠지는 기능은 `oscap -V`와 실제 규칙 실행으로 확인한다. 전체 데스크톱에 SCAP Workbench를 추가할 필요 없이 기존 관리자 앱을 사용한다.

ComplianceAsCode의 공통 Linux 규칙을 재사용하되, KIKI용 제품 정의·OS 식별·프로파일을 만든다. RHEL/Ubuntu 정책의 RPM·DPKG·배포판 경로 검사를 그대로 적용하면 비해당·오류 또는 오판정이 생길 수 있다. KI2 인벤토리 검사는 별도 관리 모듈에서 제공하고, 필요한 경우 검토된 확장 검사를 작성한다. 다른 배포판의 OVAL 취약점 피드를 KIKI에 그대로 적용하지 않는다.

초기 프로파일은 `kiki-desktop-baseline`, 이후 `kiki-server-baseline`을 제안한다. 이름은 자체 기준을 뜻하며 CIS/STIG 인증을 의미하지 않는다.

| 초기 점검 영역 | 검사 내용과 조건 |
|---|---|
| 계정·인증 | UID 0 중복, 빈 암호 계정, passwd/shadow 권한, 설치된 PAM 정책 |
| SSH | 서비스 사용 여부, 유효한 설정과 Include/Match, root·암호 로그인 정책; 실제 접속 방식에 맞춘 기준 |
| 권한 | 중요 설정·저장소 키 소유권, 쓰기 권한, SUID/SGID 허용 목록 |
| 커널 설정 | sysctl의 현재 값과 영구 설정; 데스크톱·컨테이너의 필요한 예외 구분 |
| 네트워크·서비스 | 실제 리슨 소켓, 불필요 서비스, nftables 설치·활성·규칙; 단순 설정 파일 존재로 합격 처리하지 않음 |
| 로깅·시간 | journald 보관 정책, 시간 동기화, audit 지원·설치·활성 상태 |
| 패키지 신뢰 | 서명 키·저장소·업데이트 결과를 KI2 모듈로 확인; SCAP 표준 검사와 결과 출처 구분 |

결과는 `pass`, `fail`, `error`, `unknown`, `notapplicable`, `notchecked`를 보존한다. 필수 방화벽·감사 기능이 빠진 경우 정책 실패인지 지원하지 않는 검사인지 구분하고, 둘 다 합격으로 계산하지 않는다. 적용 규칙 수·실행 완료 수와 미검사 수를 공개한다.

읽기 전용 검사를 기본으로 한다. 지원되는 파일 검사는 이미지 rootfs에서도 할 수 있지만, 실행 중 sysctl·systemd·방화벽·리슨 소켓은 부팅한 VM/실제 OS에서 검사해야 한다. 빌드 컨테이너의 설정을 ISO 설정 검사 결과로 사용하지 않는다. `--remediate`는 초기 자동 검사에 넣지 않는다. SSH·PAM·방화벽 수정은 별도 변경 계획·백업·복구 검증이 필요한 기능이다.

## 화면과 빌드 흐름

- 빌드 콘솔에 보안 검사 화면을 두고 패키지별 CVE, 영향 판정, 수정 후보, 매핑 상태와 출처를 표시한다. 업데이트 상세에는 적용 전후 CVE 변화와 설정 검사 요약을 연결한다.
- KIKI 관리자에는 설치된 시스템의 보안 상태, 검사 실행, 마지막 검사 시각, 권한이 필요한 항목을 표시한다. 기존 고정 동작 polkit 경계를 유지하고 임의 명령·업로드 정책 실행은 허용하지 않는다.
- 후보 빌드 완료 후 패키지 CVE를 검사하고, 기존 요청 기반 VM 검증에 설정 검사를 추가한다. 현재 등록된 Windows 예약 작업을 별도 작업으로 복제할 필요는 없다. 검사 기능이 구현·검증된 뒤 기존 요청 처리에 연결한다.
- VM 보고서에는 대상 스냅샷·설치 인벤토리 해시, 검사 엔진 버전, 정책 SHA-256, 취약점 데이터 조회 시각/식별자, 결과 파일 해시를 포함해 서명한다. CVE 조회 실패와 설정 검사 실행 실패를 정상으로 처리하지 않는다.
- 초기에는 정보·경고를 표시해 오탐을 교정한다. 이후 영향이 확인된 중대 CVE·KEV와 필수 설정 실패에 승격 차단을 적용한다. 차단 정책·예외·허용 만료를 명시하고 안정 채널 승격은 수동으로 유지한다.
- HTML·ARF/XML 원본과 요약 JSON을 보관한다. 사용자명·호스트·설정 정보가 담긴 보고서는 인증된 관리자만 조회하게 하고 공개 HTTP 패키지 저장소에는 게시하지 않는다. 외부 공지와 결과 문자열은 UI에서 이스케이프하며 HTML 보고서는 분리된 실행 제한 환경에서 표시한다.

## 구현 순서와 완료 조건

1. 패키지 식별자 매핑, SBOM, CVE 공급자·캐시·미확인 상태·알림과 웹 화면을 먼저 구현한다. 실제 취약/수정 경계 버전, 백포트, 동명이인, API 실패·오래된 데이터·페이지네이션을 검증한다.
2. OpenSCAP 및 누락 의존성의 KI2 레시피를 추가하고, 작은 KIKI 전용 정책으로 XML 검증과 실제 VM 실행을 통과시킨다. 의도적으로 잘못된 설정을 둔 시험에서 실패를 탐지하고, 올바른 설정에서는 통과하며 미지원 항목을 숨기지 않는지 확인한다.
3. 관리자 앱·기존 VM 검증 보고서에 연결하고, 업데이트 전후 차이와 서명·권한·보고서 해시 검증을 시험한다. 정상 부팅·로그인 화면 검증도 계속 유지한다.
4. 데이터 품질을 검토한 뒤 배포 차단 정책과 예외 처리를 적용한다. 새 커널 후보 검증은 현재의 initramfs 생성 제한을 해결하는 별도 작업이다.

## 확인한 공식 자료

- [OSV API: 패키지·버전·Git 조회](https://google.github.io/osv.dev/post-v1-query/)와 [데이터 범위](https://google.github.io/osv.dev/data/): 지원 생태계와 정확한 프로젝트 식별이 필요하다.
- [NVD CPE API](https://nvd.nist.gov/developers/products): CPE 이름과 버전 조건을 조회한다. [NIST의 2026 NVD 운영 변경](https://www.nist.gov/news-events/news/2026/04/nist-updates-nvd-operations-address-record-cve-growth)은 모든 CVE의 부가 정보가 같은 수준으로 제공되지 않음을 설명한다.
- [CISA KEV 카탈로그](https://www.cisa.gov/known-exploited-vulnerabilities-catalog): 실제 악용 취약점 우선순위용. 이번 검토에서는 해당 웹페이지 직접 열기가 403이었고, [CISA 공식 배포 공지](https://content.govdelivery.com/accounts/USDHSCISA/bulletins/42c823a)로 용도를 확인했다. 실제 피드 연결성은 구현 시 별도 검증한다.
- [OpenSCAP 설명](https://www.open-scap.org/tools/openscap-base/)과 [사용 설명서](https://static.open-scap.org/openscap-1.3/oscap_user_manual.html): XCCDF·OVAL 정책 평가와 결과 보고를 제공한다.
- [OpenSCAP 공식 빌드 설정](https://github.com/OpenSCAP/openscap/blob/main/CMakeLists.txt): 필수 라이브러리와 선택 프로브를 확인했다. main 브랜치를 릴리스 고정 대신 사용하자는 제안은 아니다.
- [ComplianceAsCode 정책 작성 문서](https://complianceascode.readthedocs.io/en/latest/manual/developer/03_creating_content.html): 제품별 프로파일·식별·공통 규칙 재사용 구조를 확인했다.
