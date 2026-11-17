# 서버 Xvfb 기반 GTK 검사 보완·재검증 — 2026-11-17

## 판정

검사 도구를 보완하고 **80건을 통과**했다. 이전에 실패한 GTK 화면 검사 2건은 보완한 환경에서 각각 5회 연속 통과했다. 설치기 앱 코드·패키지·ISO·GNOME 환경은 변경하지 않았다. incident-ai 자동 연동은 계속 보류한다.

최초 실패의 정확한 촉발 조건까지 확정한 것은 아니다. 당시 GTK는 `Failed to open display`를 출력했지만, 임시 래퍼가 Xvfb stderr를 `/dev/null`로 버려 서버의 당시 종료·연결 상태를 복원할 수 없다. 같은 이미지에서 직접 연결과 기존 조건 재실행은 성공했다. 따라서 설치기 기능 오류나 GTK의 X11 미지원으로 단정하지 않는다.

## 확인한 사실과 수정

- 검증 이미지 `localhost/kiki-installer-validation:v13-20261116`, ID `b637789713980bcd4afb8b7a262778d0af0b1e0638930e5a5d5a749764d1de6b`를 유지했다.
- GTK 4.12.3의 X11·Wayland 지원 심벌, Xvfb 실행과 실제 GDK 디스플레이 연결을 확인했다.
- 진단 출력을 넣은 1회와 출력 타이밍 영향을 줄인 기존 조건 5회 모두 GTK 3건이 통과했다. 기존 증상은 지속적으로 재현되지 않았다.
- 기존 임시 래퍼는 display 번호 통지만 읽고 GTK를 실행했으며 실제 X11 setup 연결 확인·진단 로그·명령 시간 제한이 없었다.
- `tools/ki2xvfb.py`를 추가했다. display 번호를 받은 뒤 실제 X11 setup 응답을 확인하고, 검사 동안 연결을 유지한다. 시작과 명령 시간을 제한하고 자식의 실패 코드를 그대로 전달한다. 종료·시간 초과·중단 시 자신이 만든 프로세스를 정리한다.
- Xvfb 로그와 준비 여부·display·프로세스·종료 코드 JSON을 저장한다. 실패하면 진단 경로와 서버 로그를 출력한다.
- `tools/test_gtk_installer_ui.py`는 임시 PATH 래퍼 대신 이 공용 도구를 직접 호출한다. 기존 GTK 검사 내용과 검증 조건은 유지했다.
- `tools/test_ki2xvfb.py`로 실제 연결 성공, 실패 코드 23 전달, 명령 시간 초과 124, 서버 누락 125 및 프로세스 정리를 확인했다.

이는 확인된 관측·준비 확인의 공백을 보완한 것이다. 로그가 없는 최초 사건의 세부 원인을 추측해 확정하지 않는다. 재발 시에는 새 X11 준비 결과와 서버 로그를 근거로 조사할 수 있다.

## 서버 재검증

| 검사 | 실행·결과 |
|---|---|
| Xvfb 실행 도구 통합 검사 | 4건 통과 |
| GTK 화면·계획·진행 상태 | 5회 연속 통과 |
| GTK 네트워크 탐색·모드 전환 | 5회 연속 통과 |
| 쓰기 가능한 전체 디스크 탐색 | 5회 연속 통과 |
| 설치기·카탈로그·진행 상태·출처·미디어 회귀 검사 | 61건 통과 |
| 합계 | 80건, skip 0 |
| 실제 X11 준비 기록 | GTK 검사 10세션 모두 ready=true, exit=0, 서버 종료 확인 |

서버 검증 복사본은 `/build-kikios/kiki-build/verification/20261117-xvfb-fix/fixed-r1/source`다. 기반은 Gitea 커밋 `2839388582aaa54002e843dc485d80bd94271958`이며 검사 파일 3개만 보완했다. 기존 ISO의 clean 소스 커밋 기록은 바꾸지 않는다. 검사 당시에는 작업본으로 검증했으며, 후속 Git 반영은 커밋 이력을 따른다.

실행 예시(해당 Linux 검증 복사본 및 기존 검증 이미지 내부):

```text
PYTHONPATH=tools python3 -B -m unittest test_ki2xvfb test_gtk_installer_ui -v
```

상세 실행 환경은 증거 디렉터리의 `server-validate.py`에 보관했다. 단순 재시도나 실패 무시로 통과 처리하지 않았다. 실제 GTK 검사는 5회 모두 별도로 실행했고 모든 종료 코드를 검사했다.

## 보존

- 로컬 보호 파일 5,532개의 SHA가 모두 일치한다. 삭제 파일은 0개다.
- 서버 보호 목록 15,208개는 과거 승인한 ISO 삭제 3개 예외를 적용한 뒤 크기·mtime 변경이 없다. 원본 설치기와 보존 ISO 3개 SHA도 유지된다.
- 빌드 서비스 4개와 외부 로그인 화면이 정상이며 서비스를 재시작하지 않았다.
- 기존 GNOME VM 5개와 r29·metadata-r4·git-r7 후보 VM의 ID·디스크·상태를 읽기 전용으로 확인했다. VM 입력이나 재부팅은 하지 않았다.
- 검사 복사본과 검증 산출물만 새로 만들었다. 설치기·패키지·ISO를 재빌드하거나 교체하지 않았다.

## 증거와 남은 범위

`E:/dev/KIKI-OS/artifacts/kiki-v1.3-lts/20261117-stage5-xvfb/`:

- `server-results/result.json`, `server-results/gtk-0.log`부터 `gtk-4.log`, `contracts.log`, `runner-integration.log`.
- `server-results/gtk-*/xvfb-*.json`, `xvfb-*.log`와 GTK 화면 캡처.
- `verified-source/tools/`: 서버에서 실제 실행한 수정 소스. 로컬과 내용을 대조했다.
- `test-harness.patch`, `test-harness-files.json`, `test-summary.json`, `validation-summary.json`, `SHA256SUMS.txt`.
- `preservation-local.json`, `preservation-server.json`, `preserved-vms-after.json`, `previous-candidate-vm-preserved.json`, `git-candidate-vm-preserved.json`.

최초 실패 및 진단 로그는 이전 `20261117-stage4-git-build/headless-gtk-tests.log`, `xvfb-probe.log`, `xvfb-repeat-2.log`에 그대로 남긴다. 이전 실패 기록을 성공으로 덮어쓰지 않았다. 후속 Git 반영 시 검사 도구·검사 파일 3개를 함께 포함해야 하며, 원래 실패의 세부 촉발 조건은 미확정이라는 제한도 유지한다.
