# 웹 패키지 그룹·메타정보 관리

웹 콘솔의 **패키지 그룹 관리**에서 그룹 생성·수정·삭제, 선행 그룹, 필수·기본·선택 패키지, systemd 서비스 정책, 기본 시작 대상과 프로필 연결을 관리한다. 패키지 목록에서 이름을 누르면 설명·라이선스·분류를 편집할 수 있다. 버전·소스·의존성 변경은 기존 업데이트 후보의 검토·빌드·VM 검증 절차를 사용한다.

## 저장과 적용

- 편집본은 CI artifact root 아래 `catalog/current.json`에 저장한다. `seed.json`이 있으면 최초 그룹 구성을 여기서 읽고, 없으면 소스 트리의 `package-groups.json`을 사용한다.
- `catalog/revisions/<revision>.json`에 이전·현재 편집본을 보관한다. 변경 시각·작성자·사유를 기록하며, 화면에 표시된 리비전이 현재와 다르면 HTTP 409로 거부한다.
- 이력 화면에서 과거 리비전을 새로운 리비전으로 복원할 수 있다. 이력과 이미 제출한 빌드는 보존한다. JSON 내보내기는 인증된 사용자에게만 제공된다.
- admin·operator는 저장할 수 있고 viewer는 조회만 한다. 기존 Host·Origin·CSRF 검사를 재사용한다. 인증 게이트웨이가 작성자 헤더를 덮어쓰므로 브라우저가 작성자 이름을 지정할 수 없다.
- 존재하지 않는 패키지·그룹, 중복 패키지 분류, 그룹 순환, 잘못된 서비스 이름, 빈 프로필 연결은 저장할 수 없다. 다른 그룹·프로필이 참조하는 그룹을 삭제하려면 연결을 먼저 정리한다.

개별 패키지 빌드 요청 시 편집본 JSON과 빌드 엔진 복사본, 각각의 SHA-256을 작업 폴더에 고정한다. 실행 시 해시를 검증하고 소스의 작업별 복사본에 레시피 메타정보와 그룹 JSON을 반영하며 GTK·TUI 설치기 테이블도 재생성한다. JSON 레시피를 지원하지 않는 옛 Git 소스에서도 고정한 엔진을 사용한다. Git 작업은 해당 작업의 Git 내보내기에 반영하며, 원래 Git 저장소와 보존 소스 트리는 수정하지 않는다. 재시도는 원래 편집본·엔진을 검증하고 재사용한다.

메타정보 저장 시 다음 빌드 release를 증가시켜 기존 패키지 파일과 구분한다. 원본 버전이 달라진 경우 메타정보를 다시 검토해야 한다. 그룹 카탈로그를 포함하는 ki2ctl·설치기 패키지는 카탈로그 리비전에 따라 release를 증가시킨다. 생성 결과는 기존 완료 작업 동기화에서 레시피 지문을 검사하고 웹 카탈로그 출처와 함께 보관한다. 기존 서명 패키지·고정 스냅샷·안정 채널은 편집하지 않는다.

업데이트 후보를 생성할 때도 그 시점의 웹 메타정보를 레시피에 복사한다. 업데이트의 release는 기존 바이너리·후보 전체에서 계산하는 규칙을 유지한다. ki2ctl 업데이트는 해당 시점의 그룹 JSON을 후보에 보관하고 소스 아카이브에 넣는다. 이후 웹 변경은 준비 중인 후보의 입력을 바꾸지 않는다. 새 그룹을 설치기 선택 화면에 표시하려면 설치기 패키지를 재빌드한 뒤 새 ISO로 검증해야 한다. 저장 버튼 자체가 설치된 OS나 기존 ISO를 수정하지 않는다.

## 운영과 검증

단일 CI 프로세스의 builder lease와 카탈로그 잠금으로 쓰기를 직렬화한다. 편집본은 임시 파일에 쓰고 fsync 후 원자 교체한다. 서비스 재시작 후에도 artifact root의 편집본·이력을 유지한다. 백업 대상에 `catalog/`와 각 작업의 `catalog.json`을 포함한다. 웹 편집본을 Git에 자동 커밋하거나 푸시하지 않으므로 Git에 반영하려면 JSON을 내보내 검토 후 적용한다.

검증 명령은 다음과 같다.

```sh
python3 -m unittest discover -s tools -p test_ki2catalog.py
python3 -m unittest discover -s tools -p test_ki2ci.py
python3 -m unittest discover -s tools -p test_ki2ci_auth.py
python3 -m unittest discover -s tools -p test_ki2build.py
python3 -m unittest discover -s tools -p test_ki2updates.py
python3 -m unittest discover -s tools -p test_ki2release.py
```

카탈로그 테스트는 실제 Linux 빌드 작업을 실행해 수정된 설명과 release가 `.ki2` manifest에 들어가는 것을 검사한다. 업데이트 테스트는 웹 메타정보·그룹 JSON의 후보 고정과 소스 아카이브 내용을 확인한다. 브라우저에서는 그룹 생성·수정, 패키지 메타정보 저장, 이력·복원과 검색을 확인한다. Browser plugin은 세션에 없으므로 내장 브라우저의 Playwright 경로를 사용한다.
