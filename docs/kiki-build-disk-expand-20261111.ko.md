# 원격 빌드 디스크 200GiB 확장 완료

검증일: 2026-11-12(한국 시간). 대상은 로컬 E:가 아니라 원격 `build-server.novalocal`의 `/build-kikios`다.

## 최종 결과

| 항목 | 결과 |
|---|---|
| 클라우드 볼륨 | `build-disk` / `f1305661-ced6-4ed0-a569-c9c51ec70cea` |
| 원래 서버 재연결 | `build-server` / `3b778824-515a-4955-a8a1-4acae7629384` |
| 클라우드 상태 | `in-use`, 200GiB |
| 원시 장치 | `/dev/vdd`, 214748364800바이트 |
| 마운트 | `/dev/vdd1` → `/build-kikios`, XFS |
| 파일시스템 용량 | 214680186880바이트, df 표시 200G |
| 사용량·여유 | 약94GiB 사용, 113889726464바이트(약106.1GiB) 여유, 사용률47% |
| XFS UUID | `828cebec-78b6-476a-8950-e3394c1c9d22` 유지 |
| 파티션 | DOS ID `0xa60d86fc`, 시작2048섹터 유지, 크기419428319섹터 |
| fstab | 보호 사본과 바이트 단위 동일 |
| 루트·백업 디스크 | 기존20GiB·300GiB 유지, 백업 UUID 유지 |
| 서비스 | 원래 활성 사용자5개·시스템1개 복구 |
| 컨테이너 | candidate-buildd / release-worker / build-auth / build-llm-relay 모두 running |
| 실패 서비스 | system·lab 사용자 목록 모두 없음 |
| 로그인 응답 | 올바른 Host의 로컬8092 및 기존 외부 HTTPS `/login` 모두200 |

외부 확인 주소: https://cloud-7-3b778824-09936d.lab.terminal-lab.kr/login
확장 후 재부팅 검증은 이번 작업에서 수행하지 않았다. fstab의 기존 UUID 설정은 변경하지 않았다.

## 보존 검증

기존 설치기·패키지·ISO를 삭제·재포맷하지 않았다. 왼쪽 화면·호스트 입력·클립보드는 조작하지 않았다.
웹사이트 업데이트와 incident-ai 자동 연동은 진행하지 않았다.

원격 보호 사본: `/kiki-backups/pre-expand-20261111-200g` (루트 전용).

- 보호 경로15,208개: 패키지14,646개, ISO19개와 소스·wheel·인덱스·메타데이터·공개키.
- hardlink 중복 제외4,378개 파일, 35,951,203,521바이트(약33.5GiB).
- 확장 전 원본과 보호 사본의 SHA-256 대조 완료.
- 확장 후15,208개 원본 경로의 존재·크기·mtime 대조에서 변경0건.
- 최신 후보 패키지6개 SHA-256을 다시 계산해 후보 인덱스와 일치 확인.
- 후보 인덱스 SHA: `4ae47bbd46c977f4bf2628cd53dc0bbe063fa9b72750fcdde26851083e8e207a` 유지.
- 인증 DB의 일관된 사본 `auth-before.sqlite3`, 파티션 표·fstab·XFS 정보 보존.
- 기존 전체 시스템 백업은 취소 상태였으며, 이번 파일 보호를 전체 OS 복원 검증으로 간주하지 않는다.

확장 후 모든 보호 파일의 SHA를 다시 계산한 것은 아니다. 전체 대상은 메타데이터로 재검사했고, 후보6개와 인덱스는 SHA를 재계산했다.

## 처리한 문제와 실행 순서

1. 연결 중 NFS 볼륨 확장은 `Error Extending`, `VOLUME_VOLUME_007_010`으로 실패했다. 게스트 장치·파일시스템은100GiB에 유지됐다.
2. 사용자의 별도 명시 승인 후 실제 연결 상태에 맞춰 `In-use`를 복구했다. 연결 중인 볼륨을 Available로 강제 표시하지 않았다.
3. 실행·대기 빌드0건을 확인하고 기존 활성 서비스만 정상 중지했다. 인증 DB 사본을 만들고 호스트 `/build-kikios`를 정상 unmount했다.
4. Terminal Lab 포털의 정상 분리 요청은 실패했다. Horizon의 연결 관리에서 같은 볼륨을 정상 분리해 `Available / 100GiB / 연결 안됨`을 확인했다.
5. 오프라인 확장 후 `Available / 200GiB`를 확인하고, 소유 프로젝트 포털에서 같은 build-server에 재연결했다.
6. 재연결 장치가 `/dev/vdb`에서 `/dev/vdd`로 바뀌어 UUID·파티션 ID·시작 위치·원시200GiB로 다시 식별했다.
7. 첫 마운트는 XFS 중복 UUID로 거절됐다. 기존 rootless Podman의 idle catatonit 대기 네임스페이스가 제거된 이전 `/dev/vdb1` 마운트를 붙잡고 있었다. 단순 호스트 unmount만으로는 이 참조가 해제되지 않았음을 확인했다.
8. Podman의 migrate 절차는 저장소 미마운트 상태에서 ps 조회 실패로 실행되지 않았다. 모든 빌드 서비스가 중지됐고 해당 scope에 대기 프로세스1개만 있음을 확인한 뒤 정확한 pause scope만 systemd로 정상 중지했다. UUID 변경·nouuid 옵션·파일시스템 수리는 하지 않았다.
9. 기존 fstab으로 정상 마운트하고 `growpart -N`의 시작2048·기존 크기를 검토한 후 growpart와 xfs_growfs를 실행했다. XFS 블록은26214144→52428539로 늘었다.
10. 기존 활성 서비스만 복구했다. 초기 컨테이너 시작 지연으로 Podman 조회30초 제한과 외부502가 발생했으나, 기동 후 조회 대기를 늘려 최종4개 running과 로그인200을 확인했다.

루트 `/dev/vda`, 백업 `/dev/vdc`, 기존 파일·볼륨을 삭제하거나 포맷하지 않았다. XFS 축소나 이전 파티션 표 되쓰기도 하지 않았다.

## 재사용할 점검 기준

- lab UID는1001이다. 사용자 systemd/D-Bus와 rootless Podman은 `/run/user/1001`을 사용한다.
- 다음 오프라인 분리 전에는 호스트뿐 아니라 rootless Podman의 마운트 네임스페이스 참조까지 확인한다.
- 장치명 대신 UUID와 클라우드 볼륨ID로 대상을 판별한다.
- 80번은 기존 포트 매핑 방식이므로 로컬127.0.0.1:80 응답만으로 외부 장애를 판정하지 않는다.
- 인증8092는 올바른 공개 Host·HTTPS 전달 헤더를 사용한다. 인증·SELinux를 완화하지 않았다.

## 증거

로컬: `E:\dev\KIKI-OS\artifacts\kiki-operations\20261111-disk-expansion`

- `cloud-volume-200g.jpg`: 포털200GiB 연결됨 화면.
- `quiesce.log`: 원래 활성 서비스·작업0건·호스트 정상 unmount.
- `mount-error.log`, `namespaces.log`, `pause-scope-release.log`: 이전 namespace 참조와 정상 해제 근거.
- `expansion.log`: /dev/vdd 식별, growpart와 XFS 확장 결과.
- `post-verification-final.json`:15,208개 메타데이터·후보6개 SHA·컨테이너·로그인 검증 완료 결과.
- `preflight.json`: 최종 상태 요약. 이전 pending-result와 오류 화면은 실패 당시의 역사적 증거다.

원격 보호 디렉터리에는 `reattached.json`, `expansion-result.json`, `services-restored.json`, `post-verification.json`도 기록했다.
이 작업에서 Git 커밋·푸시나 신규 빌드는 수행하지 않았다.
