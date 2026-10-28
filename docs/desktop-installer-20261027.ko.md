# GNOME 설치 미디어 개선 및 검증

2026-10-27 로컬 빌드와 격리된 Hyper-V VM에서 검증한 GNOME 설치 후보입니다.
기존 GNOME 50·네이티브 Mesa 환경을 재사용하고 설치기와 기본 데스크톱 도구를 추가했습니다.
패키지 컴파일 속도 최적화는 이번 변경 범위에 포함하지 않았습니다.

## 반영 내용

- 공통 `package-groups.json`에서 GTK·Go·ISO 백엔드의 프로파일과 그룹을 생성합니다.
- ISO의 전이 의존성까지 검사하여 설치 가능한 프로파일과 추가 그룹만 선택할 수 있습니다.
- AI가 없는 미디어에서는 일반 서버의 기본 AI 모드를 끕니다.
- GNOME은 GDM·`graphical.target`을 사용하고 tty2 복구 콘솔을 유지합니다.
- 설정·파일 탐색·GTK4 VTE 터미널과 IBus 두벌식 한글 입력을 제공합니다.
- 키보드·접근성·전원·시간·정리·화면보호·rfkill GNOME 설정 데몬을 추가했습니다.
- 터미널은 유니코드 입력을 정상 처리하는 Bash 로그인 셸로 실행합니다.

설정 앱은 테마·글자 크기·애니메이션·입력 언어를 저장합니다. 파일 앱은 폴더 탐색과
1 MiB 이하 UTF-8 텍스트 미리보기를 제공합니다. GNOME Control Center·Nautilus의 전체
기능은 제공하지 않습니다. 오디오·화면 공유·Xwayland와 실제 하드웨어 GPU는 별도 검증 대상입니다.

## 실제 설치에서 발견하고 수정한 문제

1. 설치된 OS로 전환할 때 `chroot`만 적용하여 UPower의 사용자 네임스페이스 생성이
   실패했습니다. 실제 루트 마운트를 이동한 후 systemd로 전환하도록 수정했습니다.
   UPower의 `PrivateUsers`·`RestrictNamespaces` 제한은 유지합니다.
2. IBus 사용자 서비스의 상대 경로 `sh` 실행이 실패했습니다. 절대 경로의
   `/usr/bin/ibus-daemon`을 실행하도록 수정했습니다.
3. 설치 후 패키지 목록만 있고 버전·파일 소유권 DB가 없었습니다. 서명된 아카이브를
   재검증한 뒤 `installed.json`을 기록하고 `ki2ctl`에서 읽도록 수정했습니다.
4. 기본 BusyBox 셸에서 한글 조합 결과가 `??`로 표시됐습니다. 같은 VTE에서 Bash의
   정상 처리를 확인하고 터미널 실행 파일에 Bash를 명시했습니다.

## 재현과 근거

빌드·패키징·미디어 검증 스크립트와 로그는 `artifacts/desktop-installer-20261027`에 있습니다.
`package-frontends.py`, `build-media.py`, `verify-media.py` 순서로 실행합니다.
이 스크립트는 해당 로컬 SDK·네이티브 빌드 디렉터리를 사용하는 검증 보조 도구입니다.
일반 프로파일 재사용 경로는 `distro/profiles/desktop-gnome.toml`의 서명·해시 고정 저장소입니다.

```sh
python3 tools/ki2installcatalog.py --check
python3 tools/ki2build.py validate --profile distro/profiles/desktop-gnome.toml --max-packages 192
python3 tools/ki2build.py plan --profile distro/profiles/desktop-gnome.toml
python3 tools/ki2build.py rootfs --profile distro/profiles/desktop-gnome.toml \
  --rootfs-dir /tmp/kiki-desktop-rootfs
```

미디어 자체를 다시 읽어 모든 패키지의 서명·해시를 검사합니다. Hyper-V에서는 새 빈
32 GiB 디스크에 GTK로 설치하고 ISO를 분리한 뒤 디스크 부팅·암호 로그인·재부팅을 검사합니다.
최종 판정과 화면 근거는 `hyperv-validation.json`, `iso-readback-validation.json`,
`guest-validation-r3-first.json`, `guest-validation-r3-reboot.json`에 기록합니다.
개인 서명키는 후보 저장소와 ISO에 복사하지 않습니다.

최종 r3 ISO는 `artifacts/desktop-installer-20261027/kiki-desktop-installer-20261027-r3.iso`이며
SHA-256은 `01abf8a7851f3b423fd4419a68eba876a2e0e041986c000edaea476f3dd6240c`입니다.
VM은 `kiki-desktop-install-r3-20261027`(Gen2, 4 GiB, 2 vCPU)이며 검증 후 정상 종료했습니다.
ISO 재검사 192개, 설치 174개, 첫 부팅·재부팅 각각 19개 상태 검사를 통과했습니다.
재부팅 후 시스템·사용자 실패 유닛은 각각 0개이고 오류 우선순위 부팅 저널도 비어 있습니다.
설정 앱에서 선택한 `prefer-dark` 값의 저장·재부팅 후 유지를 확인했습니다.
개별 앱의 시각적인 테마 반영은 해당 앱의 테마 지원에 따르며 이번 유지 검사의 판정 범위와 다릅니다.
보존한 저장소로 프로파일 검증·계획·rootfs 재조립도 통과했습니다. 새 rootfs의 설치 DB는
174개이며 기본 부팅 대상은 `graphical.target`입니다. 일반 소스 레시피 141개의 의존성
검사는 경고 없이 통과했습니다. 결과는 `profile-assembly-validation.json`에 보존했습니다.
