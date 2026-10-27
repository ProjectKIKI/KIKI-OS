# KIKI Stage 3 네이티브 Mesa 후보

이 작업은 보존한 GNOME r6 후보에서 Mesa bootstrap 공급 경로를 분리한다.
Mesa·LLVM 소스 빌드, 패키지 SHA·의존성 검사, 별도 VM의 GDM/Wayland 로그인과
GTK4·Libadwaita 앱 실행을 통과했다. 검증한 182개 아카이브를 별도 후보 저장소에
배치하고 후보 전용 Ed25519 키로 서명했다. `release_ready=false`를 유지한다.

## 보존 범위와 경로

- 기존 설치기와 원본 280개 파일을 보존한다.
- r6 후보의 패키지·ISO·메타데이터·설치 VM 부모 디스크 189개 항목을 보존한다.
- 새 후보: `dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017`.
- 별도 SDK·캐시: WSL의 `/home/tang/kiki-build/mesa-native-20261017`.
- 새 차등 VM: `kiki-mesa-native-20261017`. r6 부모 디스크는 읽기 공급자로만 사용한다.
- 라이브 설치기는 기존 전용 런타임을 유지하고, 설치 대상 GNOME은 네이티브
  `mesa`·`llvm` 패키지를 사용한다.

## 고정한 소스와 빌드 범위

| 항목 | 버전 | 공식 소스 | SHA-256 |
|---|---|---|---|
| Mesa | 25.2.7 | https://archive.mesa3d.org/mesa-25.2.7.tar.xz | `b40232a642011820211aab5a9cdf754e106b0bce15044bc4496b0ac9615892ad` |
| LLVM | 21.1.8 | https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/llvm-project-21.1.8.src.tar.xz | `4633a23617fa31a3ea51242586ea7fb1da7140e426bd62fc164261fe036aa142` |

Mesa의 서명자는 Eric Engestrom이며 지문은
`57551DE15B968F6341C248F68D8E31AFC32428A6`이다. LLVM의 서명자는 Douglas Yung이며
지문은 `FFB3368980F3E6BB5737145A316C56D064CACBA5`다.
공식 배포자 키를 별도 GPG 디렉터리에 가져와 서명과 잠금 SHA를 대조한다.

호스트는 GCC/G++ 11.5.0, CMake 3.26.5, Ninja 1.10.2, Python 3.9.25를 사용한다.
Meson 1.9.2와 Mako 1.3.10·packaging 25.0·PyYAML 6.0.3은 새 격리 환경에 둔다.
이 기록은 GCC 14.4 대상 툴체인 완성을 뜻하지 않는다.
현재 GCC 기본 CPU 기준은 `x86-64-v2`, 튜닝은 `generic`이다. 이번 빌드는 이 기준을
승계하므로 모든 초기 x86-64 CPU까지 지원한다고 표시하지 않는다.

LLVM TableGen과 LLD 21.1.8은 빌드 호스트 도구로만 재사용한다. 대상 LLVM
공유 라이브러리는 공식 소스로 새로 컴파일하며, 호스트의 RPM 라이브러리를
대상 패키지에 복사하지 않는다. 정확한 도구·소스 지문은 `validation/build-inputs.json`에 둔다.
LLVM 런타임 패키지와 Mesa 빌드를 구분하며, Mesa의 LLVM 헤더·설정 도구는 같은
소스 빌드 트리에서 사용한다. 개발용 SDK 패키지와 정식 공용 빌더 레시피로의 이관은
파이널 전 재현성 점검에서 별도로 정리한다.

LLVM은 X86 백엔드의 공유 런타임으로 구성한다. Mesa는 Wayland·EGL·GBM·GLVND·
OpenGL/GLES와 llvmpipe·softpipe·svga·virgl을 구성한다. X11 GLX와 Vulkan은
이번 빌드 범위에 포함하지 않는다. Intel·AMD 실기기 GPU 지원도 완료로 표시하지 않는다.

## 의존성 전환과 검증 순서

1. 새 SDK에서 bootstrap 패키지가 소유한 파일만 기존 해시와 대조하여 제거한다.
2. LLVM 공유 런타임을 소스 빌드하고 패키지 내부 파일 SHA를 검사한다.
3. 네이티브 LLVM을 사용해 Mesa·GBM 백엔드·EGL 공급자를 함께 소스 빌드한다.
4. Mutter와 데스크톱 메타패키지의 의존성을 `kiki-mesa-bootstrap`에서 `mesa`로
   변경한다. Mutter 실행 파일의 내용은 보존한다.
5. 모든 대상 패키지의 SHA·의존성·파일 소유권을 대조하고 패키지 아카이브만으로
   새 루트를 조립한다. ELF 공급자와 직접 의존성, 빌드 경로 잔류 여부를 검사한다.
6. 새 루트에서 GLES 셰이더를 컴파일해 그린 뒤 실제 픽셀을 읽어 렌더링을 확인한다.
7. 별도 VM에서 기존 bootstrap 파일을 해시 확인 후 제거하고 새 네 패키지를 적용한다.
   재부팅 후 GDM 비밀번호 로그인·Wayland 세션·GTK4/Libadwaita 앱을 확인한다.
8. GNOME Shell과 GTK 앱의 실제 메모리 매핑을 새 Mesa·LLVM 패키지 해시와 대조한다.
   이전 bootstrap 전용 파일 잔류 여부와 GBM 장치 생성, 셰이더 결과도 확인한다.
9. VM을 종료하고 보존 SHA를 재검사한 뒤 통과한 아카이브만 별도 후보 저장소에
   복사하고 후보 전용 Ed25519 키로 서명한다.

VM 적용은 차등 디스크의 런타임 교체 시험이다. 패키지 관리자 DB를 변경하는 정식
업그레이드 시험이나 새 ISO에서의 신규 설치 시험으로 계산하지 않는다.
검증 데이터 ISO도 부팅·설치 ISO와 구분한다.

## 확정한 공급 패키지

| 패키지 | 변경 | 아카이브 SHA-256 |
|---|---|---|
| `mesa-25.2.7-1.x86_64.ki2` | Mesa·EGL·GBM·DRI 백엔드를 같은 소스로 빌드 | `0291b7b715c3c1122bb2edb8c53d6dd9b0fecc1b8a877faf45bf11b56c91eb05` |
| `llvm-21.1.8-2.x86_64.ki2` | X86 런타임 소스 빌드와 upstream 호환 링크 | `0daa73ba3e107565e7fa6fda60bf011029f889544e43b8b7eb6e99a6f36dcd0e` |
| `mutter-50.4-5.x86_64.ki2` | 실행 파일을 보존하고 Mesa 공급 의존성 변경 | `42fd6578db4bbcdb71e4f94559312971b707aefeccbf9a3cc57fe976966dd597` |
| `kiki-gnome-desktop-0.1.0-3.x86_64.ki2` | 네이티브 Mesa 의존성과 후보 범위 설명 반영 | `c6bfd0a40c3e482b2f5efe488a337594526c638f89c888f9339e353a03e16a36` |

재사용한 주요 런타임 공급자는 glibc 2.39, libgcc·libstdcxx 11.5.0, zlib 1.3.1,
zstd 1.5.6, Expat 2.6.2, libdrm 2.4.128, libglvnd 1.7.0, Wayland 1.26.0,
systemd·libsystemd 255.7이다. 실제 직접 의존성과 파일 소유권은 전체 대상 180개
패키지를 기준으로 대조했다. ELF 공급자 누락·빌드 RPATH 잔류·추가 직접 의존성 요구는 0개다.

LLVM 설정 도구는 명시적 로더 실행 시 `/proc/self/exe`를 로더 경로로 판별했다.
빌드 전용 `llvm-config`에 새 SDK 로더·라이브러리 경로를 지정해 직접 실행하도록
정리했다. 이 도구는 대상 런타임 패키지에 포함하지 않는다. 개발 트리 조회에 필요한
LLVMTableGen 정적 라이브러리도 빌드 전용으로 준비했다.

LLVM r2는 upstream 설치 규칙의 `libLLVM-21.so` 호환 링크를 보완한 패키지다.
Mesa 빌드 시점 LLVM r1과 r2의 실행 라이브러리·라이선스 파일은 동일하다.
실행 라이브러리 SHA는 `40543280e7db862e7d13f57583a46c50aaf3669dc832a1968a4f3392044dd7f6`이며,
이 동일성을 저장소 승격 조건에서도 확인한다.

## 실제 검증 결과

| 검증 | 결과 |
|---|---|
| 공식 Mesa·LLVM 소스 SHA와 배포자 서명 | 통과 |
| 네이티브 대상 180개 패키지 SHA·의존성·소유권·ELF 검사 | 통과, 오류 0개 |
| 새 루트의 셰이더 컴파일·그리기·픽셀 읽기 | EGL 1.5, OpenGL ES 3.2, 픽셀 `[64,128,191,255]` |
| 별도 차등 VM, 검증 ISO 분리 후 디스크 부팅 | 통과 |
| 실제 GDM 비밀번호 로그인 | `gdm-password`, `seat0`, `wayland`, 사용자 UID 1000 |
| GNOME Extensions 앱 | 한국어 GTK4·Libadwaita 창 실행 |
| 실제 프로세스와 공급 파일 해시 | GNOME Shell·GTK 앱의 새 Mesa·LLVM 매핑 확인, 네이티브 일반 파일 16개 SHA 확인 |
| 실제 DRM/GBM | `/dev/dri/card0`, GBM backend `drm` |
| 렌더러 | `llvmpipe (LLVM 21.1.8, 256 bits)`, Mesa 25.2.7 |
| 사용자 D-Bus·logind·Polkit·Upower | 동작 확인 |
| Bash 잘못된 로캘·히스토리 PTY 회귀 / 사용자 네임스페이스 | 통과 |
| `systemd-analyze` 부팅 지표 | 약 3.426초, graphical.target 약 3.122초, 온라인 대기 생략 조건 유지 |
| 실패한 시스템 유닛 | 0개 |
| bootstrap 전용 런타임 파일 잔류 | 0개, 공용 경로는 새 네이티브 패키지 소유 파일로 확인 |
| 원본·r6 후보 보존 재검사 | 469개 항목, 변경 0개 |
| 후보 저장소 | 182개 아카이브, 별도 Ed25519 서명 검증 통과 |

VM은 정상 종료했고 DVD와 네트워크 연결을 분리한 상태다.
위 부팅 지표는 systemd 측정값이며 로그인 화면의 상호작용 준비 시간을 별도로 측정한 값은 아니다.
[GDM 화면](E:/dev/KIKI-OS/artifacts/mesa-native-vm-20261017/mesa-native-gdm.png)과
[GTK 앱 화면](E:/dev/KIKI-OS/artifacts/mesa-native-vm-20261017/mesa-native-gtk.png)은 실제 VM 캡처다.

기존 Zink/libvulkan 로드 경고는 이번 부팅 로그에서 0개다. GTK 앱 실행 시
`fd -1` 장치 조회와 DRI2 초기 탐색 관련 EGL 경고 4줄은 남았다. 이 경고의 세부 원인과
프로브 경로 정리는 후속 항목으로 유지한다. 이번 결과는 실제 셰이더·GBM·Wayland·GTK
실행 성공을 확인한 것이며 경고가 없는 모든 GPU 지원을 의미하지 않는다.

## 후보 위치와 파이널 전 남은 항목

검증한 패키지는
`E:/dev/KIKI-OS/dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017/validated-candidate`
아래에 있다. 원래 r6 저장소·ISO·부모 디스크를 교체하지 않았다.
새 인덱스 SHA는 `6992169904af0a02cf9103808798b60377d83a29903b3c8708223442cabb863e`다.

근거는 새 후보의 `validation/mesa-vm-runtime.json`, `validation/native-root-rendering.json`,
`validation/desktop-root-elf-suppliers.json`, `validation/preservation-current.json`,
`validation/llvm-compatibility-layout.json`, `gate.json`이다.

- 네이티브 Mesa를 포함한 부팅·설치 ISO의 신규 설치 회귀. 이번 39,661,568바이트 ISO는
  패키지 검증용 데이터 미디어이며 부팅 ISO가 아니다. 이번 VM 시험은 r6 설치본의
  새 차등 디스크에서 수행한 런타임 전환 시험이다. `fresh_install_tested=false`다.
- 실기기 GPU·입력 장치·모니터와 지원할 가상화 환경의 검증. 현재 실측은 Hyper-V
  소프트웨어 렌더링이며 Intel·AMD 가속이나 Vulkan 지원을 포함하지 않는다.
- EGL 초기 탐색 경고의 상세 원인 정리와 지원 환경별 처리.
- 정식 공용 빌더 레시피·개발용 SDK·툴체인 기준·캐시 지문을 정리한 재빌드 검증.
- 실제 gnome-settings-daemon과 Settings, 터미널·파일·로그·시스템 감시 앱,
  서버 설치와 선택형 GNOME 설치 프로필 정리.

**Mesa bootstrap의 대상 런타임 의존성 전환은 이번 후보에서 통과했다.
운영 데스크톱을 포함한 Stage 3 파이널 승격은 보류한다.**
