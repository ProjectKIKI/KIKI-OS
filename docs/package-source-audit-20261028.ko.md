# 패키지 출처 대조 결과

2026-10-28, 공개 `desktop-test/kiki-admin-20261028-r4` 후보의 224개 패키지를 대조했다.

| 구분 | 개수 | 확인 범위 |
|---|---:|---|
| 외부 원본 | 210 | 원본 HTTPS 주소, 입력 파일 SHA-256, 해당 패키지의 레시피 연결 |
| 자체 소스·설정 | 12 | 저장소 입력 경로 또는 설정 생성 스크립트, 해당 패키지의 레시피 연결 |
| 보존된 외부 파일 포함 | 2 | 폰트 묶음, 호스트 그래픽 런타임을 포함한 인스톨러 |
| 출처 미연결 | 0 | 위 후보의 패키지 단위 기준 |

전체 `.ki2` 바이트의 SHA-256을 후보 인덱스와 대조하고, 내장 `manifest.json`의
`recipe_digest`를 보존된 정규화 레시피와 모두 대조했다. 처음 미연결이었던 79개도
정확한 레시피 지문으로 찾았으며, 이름·버전만으로 출처를 추측해 연결하지 않았다.
210개 외부 패키지가 공유하는 고유 입력 파일은 201개이며, 보존된 실제 파일을 다시 해시해
레시피·빌드 기록에 고정된 SHA-256과 모두 대조했다. 여기에는 압축 소스가 아닌
`ca-certificates`의 공개 CA PEM 입력 파일도 포함한다.

빌드 후 설정·파일 배치를 수정한 패키지는 이전 패키지 SHA-256과 정확한 빌드 기록을 따라갔다.
`fast-float`, `fmt`, `lz4`, `simdutf`, `vte`처럼 임시 staging 경로만 레시피에 남은 경우에는
내장 `build_key`와 보존된 소스 잠금 입력을 대조했다. `gnome-settings-daemon`처럼 빌드 옵션 안의
`source.source`에 원본이 기록된 경우도 처리한다.

## 보존 파일과 한계

- `kiki-desktop-fonts`: Noto Sans CJK 파일을 이전 인스톨러 패키지에서 분리했다.
  호스트 RPM `google-noto-sans-cjk-ttc-fonts-20230817-2.el9.noarch`의 `rpm -V`가 통과하고,
  현재 패키지 파일 명세·보존 staging·호스트 파일의 해시가 일치했다.
  공급자는 Rocky Enterprise Software Foundation이며 원 프로젝트는
  <https://github.com/notofonts/noto-cjk>다. RPM에 기록된 소스 패키지는
  `google-noto-cjk-fonts-20230817-2.el9.src.rpm`이다. 그 소스 RPM을 내려받아 검증한 것은 아니다.
  폰트 해시는 `b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`다.
- `kiki-installer-gtk`: 자체 프런트엔드와 호스트에서 복사한 그래픽 런타임·폰트를 함께 포함한다.
  `tools/ki2graphics.py`가 이 경계를 정의한다. 이 패키지를 순수한 자체 소스 빌드로 표시하지 않는다.
  포함 라이브러리 각각의 원본 압축파일까지 확인한 전체 SBOM 감사는 별도 작업이다.
- 자체 생성 설정의 과거 Git 커밋이 기록되지 않은 경우에는 계속 미기록으로 표시한다.
- 이번 검사는 보존된 기록과 파일의 무결성 대조다. 원저자 서명, 최신 버전 여부,
  모든 벤더 코드의 개별 출처·라이선스 적합성을 확인했다는 의미는 아니다.

## 운영 반영

감사 매핑은 `deploy/repository/source-origins-20261028.json`에 보존한다. 패키지 SHA-256과
이름·버전·release가 모두 일치할 때만 적용하며, 다른 빌드에 감사 결과를 재사용하지 않는다.
새 패키지는 빌드 기록의 출처를 표시하고, 기록이 없으면 다시 확인 필요 상태로 남긴다.

게시기 `provenance.audit_file`은 이 매핑, `provenance.audit_objects`는 추가로 보존한
원본 입력 파일의 해시 저장소를 지정한다. 기존 서명 패키지·인덱스·공개키는 수정하지 않는다.
공개 페이지에는 서버 절대 경로를 노출하지 않고, 허용된 입력 파일만 파일 해시를 다시 확인해 제공한다.
확장자 없는 Git 압축파일은 실제 압축 헤더에 맞는 파일명을 붙여 링크한다.

버전 관리 작업자의 `/app/source-origins.json`에도 같은 매핑을 읽기 전용으로 배치한다.
인증된 버전 화면과 공개 출처 화면이 동일한 감사 결과를 사용한다. 원본 카탈로그의
다운로드 작업 입력이나 서명된 패키지 명세를 감사 결과로 덮어쓰지는 않는다.

검증 근거: `artifacts/source-audit-all-manifests.json`, `source-audit-recipe-index.json`,
`source-audit-recipe-matches.json`, `source-audit-archive-index.json`, `source-audit-tests.log`.
산출물 경로는 로컬 감사 증거이며 Git 저장소에 포함하지 않는다.

운영 확인: 관련 단위·통합 테스트 54개 통과, 외부 HTTPS 보관 링크 201개 모두 HEAD 200,
CA 입력·accountsservice·확장자 없는 Git 아카이브였던 NetworkManager의 다운로드 바이트 해시 일치.
서명 인덱스·공개키 해시 유지, 미인증 관리 API·임의 파일 접근 차단도 확인했다.
브라우저에서 미확인 필터 0개, 외부 파일 포함 필터 2개, 검색 1개와 콘솔 오류 없음을 확인했다.
