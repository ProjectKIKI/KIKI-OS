# KIKI OS 2단계 V2 완료 문서

`stage2-v2`는 KIKI OS를 “반복 설치 가능한 최소 서버 배포판”으로 끌어올리는
기준선이다. 이 문서는 현재 구현된 내용, 2단계 V2 완료 기준, 3단계로 넘길
항목을 구분한다.

## 상태

- 릴리스 라인: `stage2-v2`
- 상태: 2단계 V2 기준선 완료, 2026-07-01 기준 동결
- 저장소 기본 채널: `stage2-v2`
- 설치 계획서 기본 채널: `stage2-v2`
- 저장소 서명 키 예시: `stage2-v2-repo.hmac`
- 목표: 온라인/오프라인 패키지 설치, 무인 설치, Kubernetes 노드 준비 기반

## 목표

2단계 V2의 목표는 1단계 V1에서 검증한 부팅/설치 흐름 위에 운영 가능한
패키지와 저장소 계층을 올리는 것이다.

- `ki2ctl` 온라인 패키지 설치와 의존성 해석
- HTTP 기반 `.ki2` 저장소 메타데이터/채널 운영
- 저장소 서명과 검증 흐름
- 설치된 시스템 패키지 DB
- Go 기반 설치 계획서 TUI 미리보기와 1단계 설치기 계약 공유
- 무인 설치와 오프라인 설치 준비
- Kubernetes 부트스트랩/컨트롤/컴퓨트 프로파일
- CRI-O 기본 런타임
- containerd 선택 런타임
- 빌드 웹 콘솔과 프로파일 단위 빌드

## 현재 반영된 내용

현재 코드 기준으로 다음 항목은 2단계 V2 라인에 들어와 있다.

- `tools/ki2repo.py` 저장소 메타데이터, 채널 파일 생성
- 기본 저장소 채널 `stage2-v2`
- HMAC-SHA256 기반 개발용 저장소 서명/검증 흐름
- `ki2ctl` HTTP 저장소 설정, 업데이트, 검색, 설치 모의 실행 흐름
- `ki2ctl` 로컬 경로와 `file://` 저장소 지원
- `ki2ctl repo remove`로 저장소 설정과 캐시된 인덱스 정리
- `ki2ctl` 설치 전 파일 충돌 탐지
- `ki2ctl` 트랜잭션 기록과 실패 시 기본 롤백
- Go 기반 `kiki-installer-tui` 미리보기
- Go TUI의 `source local`, `source mirror`, `source remote` 계획서 작성 흐름
- 설치 계획서 source/repo/channel/verify-key 필드
- 2단계 설치 계획서 스펙의 `runtime`, `kubernetes`, `firewall`, `artifacts` 필수화
- `kiki-kubeadm` 패키지로 kubeadm 설정 렌더링과 보호 조건 기반 `init`/`join` 실행 지원
- Kubernetes 역할 프로파일:
  - `kiki-kube-bootstrap`: 최초 부트스트랩/컨트롤 플레인 노드
  - `kiki-kube-bootstrap-containerd`: 최초 부트스트랩/컨트롤 플레인 노드, containerd 런타임
  - `kiki-kube-control`: 추가 컨트롤 플레인 노드
  - `kiki-kube-control-containerd`: 추가 컨트롤 플레인 노드, containerd 런타임
  - `kiki-kube-compute`: 컴퓨트 노드
  - `kiki-kube-compute-containerd`: 컴퓨트 노드, containerd 런타임
- Kubernetes 필수 패키지 선택 보장:
  - `cri-o`
  - `conmon`
  - `crun`
  - `containerd`
  - `runc`
  - `cni-plugins`
  - `cri-tools`
  - `kubelet`
  - `kubeadm`
  - `kubectl`
  - `kube-node-config`
  - `kube-node-config-containerd`
  - `nftables`
  - `iptables`
  - `conntrack-tools`
  - `firewalld`
  - `bridge-utils`
  - `socat`
  - `ethtool`
  - `chrony`
- `stage2-stub` 패키지 타입
- `host-files` 패키지 타입
- `tools/ki2stage2.py verify-kubernetes` 준비도 검증
- `tools/ki2stage2.py verify-install-plan` 설치 계획서 계약 검증
- `tools/ki2stage2.py verify-package-manager` HTTP/로컬 미러/오프라인 저장소 흐름 검증
- 빌드 웹 콘솔과 CI 스모크/stage2 단계
- 날짜 + Git 리비전 기반 ISO 이름
- kubeadm v1beta4 init/join 템플릿과 설치 계획서 계약

## Kubernetes 범위

Kubernetes 설치 준비는 2단계 V2에서 다룬다. 2단계의 책임은 노드가
`kubeadm` 기반 클러스터에 들어갈 수 있도록 패키지, CRI 런타임, systemd 유닛,
CNI/방화벽/네트워크 기본값, 설치 계획서를 갖추는 것이다.

- 부트스트랩 노드: 최초 컨트롤 플레인을 `kubeadm init` 대상으로 준비한다.
- 컨트롤 노드: 기존 부트스트랩 노드 뒤에 추가 컨트롤 플레인으로 join할 준비를 한다.
- 컴퓨트 노드: 워커 노드로 join할 준비를 한다.
- CRI-O는 기본 Kubernetes 런타임으로 유지한다.
- containerd는 `*-containerd` 프로필과 `runtime containerd` 명령으로 선택한다.
- 설치 계획서는 `kubernetes.role`, `kubernetes.kubeadm.action`,
  `config_template`, `config_output`, `command`, `cri_socket`을 반드시 기록한다.
- 1단계 설치기와 Go TUI는 같은 `/run/kiki/install-plan.yaml` 계약을 사용하고,
  설치 후 `/var/lib/ki2/install-plan.yaml`에 보존한다.
- `kiki-kubeadm render|init|join`은 보존된 설치 계획서를 읽어
  `/etc/kubernetes/kiki/kubeadm.local.yaml`을 만들고, 실행 기록을
  `/var/lib/kiki/kubernetes/state.json`과 `/var/log/kiki/kubeadm.log`에 남긴다.
- join 계열은 엔드포인트/토큰/CA 해시가 없으면 실행하지 않는다.

다중 노드 토큰 발급, 컨트롤 플레인 인증서 배포, CNI 실제 배포, 클러스터 전체 운영
자동화는 3단계 자동화 대상으로 넘긴다.

## 완료된 부트스트랩 패키징

- `containerd`, `runc`, `cni-plugins`, `cri-tools`는 고정된 upstream 릴리스 바이너리를
  `.ki2`로 재패키징한다.
- `cri-o`, `conmon`, `crun`은 고정된 upstream 릴리스 바이너리 또는 CRI-O 정적 번들을
  `.ki2`로 재패키징한다.
- `kubelet`, `kubeadm`, `kubectl`은 `dl.k8s.io`의 고정된 v1.36.1 바이너리를
  `.ki2`로 재패키징한다.
- `kubelet.service`는 CRI-O와 containerd 양쪽 유닛 이후 시작되도록 구성하고,
  `kube-node-config*` drop-in에서 선택한 CRI 엔드포인트와 systemd cgroup 드라이버를 지정한다.
- `kube-node-config*`는 `kubeadm.k8s.io/v1beta4` 기반 `init`,
  컨트롤 플레인 `join`, 컴퓨트 `join` 템플릿을 `/etc/kubernetes/kiki/` 아래 제공한다.
- 설치 계획서는 역할별 kubeadm 작업, 템플릿, 로컬 설정 출력, CRI 소켓을 기록한다.
- `nftables`, `iptables`, `conntrack-tools`, `socat`, `firewalld`, `bridge-utils`,
  `ethtool`, `chrony`는 `host-files` 페이로드로 실제 명령과 서비스 경로를 제공한다.
- CRI-O 기본 설정은 systemd cgroup 드라이버와 `registry.k8s.io/pause:3.10` pause image를
  `/etc/crio/crio.conf.d/10-kiki.conf`에 기록한다.

## 완료 기준

2단계 V2는 다음 조건을 만족해 완료로 본다.

1. 새 VM을 설치 계획서만으로 반복 설치할 수 있다.
2. HTTP 저장소에서 패키지를 설치할 수 있다.
3. 저장소 메타데이터 서명을 검증할 수 있다.
4. 설치된 패키지 DB가 파일 목록과 의존성을 기록한다.
5. 패키지 충돌을 탐지한다.
6. 오프라인 ISO 또는 로컬 미러로 같은 설치를 재현할 수 있다.
7. Go TUI가 설치 계획서를 작성하고 1단계 설치기와 같은 계획서 계약을 검증한다.
8. Kubernetes 부트스트랩/컨트롤/컴퓨트 프로파일이 실제 패키지 페이로드로 설치된다.
9. `crictl info`, `kubelet --version`, `kiki-kubeadm init --dry-run`,
   `kiki-kubeadm join --dry-run` 수준의 스모크 테스트가 가능하다.
10. 운영자가 문서만 보고 2단계 노드를 다시 만들 수 있다.

## 명령 예시

저장소 메타데이터 생성:

```bash
python tools/ki2build.py repo-index
python tools/ki2repo.py keygen --output build/ki2/keys/stage2-v2-repo.hmac --force
python tools/ki2repo.py generate --channel stage2-v2 --sign-key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2repo.py verify --key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2stage2.py verify-kubernetes --require-signed-metadata
python tools/ki2stage2.py verify-network-userspace
python tools/ki2stage2.py verify-network-userspace --strict-production
python tools/ki2stage2.py verify-binary-smoke
python tools/ki2stage2.py verify-package-manager
python tools/ki2stage2.py verify-installed-rootfs --root /mnt/target --runtime containerd
python tools/ki2stage2.py verify-install-plan --plan /run/kiki/install-plan.yaml --runtime containerd --role compute
python tools/ki2ci.py run stage2
```

`ki2stage2.py verify-kubernetes`는 CRI-O/containerd 프로파일, 설치 계획서, kubeadm
init/join 계약, 패키지 페이로드, 저장소 메타데이터를 확인한다. `--strict-production`을 붙이면
`stage2-stub` 자리표시자 패키지를 실패로 처리하므로 실제 바이너리 전환 완료 여부를
판정할 수 있다.

`ki2stage2.py verify-network-userspace`는 `nftables`, `iptables`,
`conntrack-tools`, `socat`, `firewalld`, `bridge-utils`, `ethtool`, `chrony`,
`kiki-netconfig`
패키지의 명령/서비스 경로와 자리표시자 메타데이터 부재를 따로 보여준다. 기본 모드는
상태를 점검하고, `--strict-production`은 자리표시자가 남아 있으면 실패하도록 쓴다.

`ki2stage2.py verify-binary-smoke`는 Linux/WSL 빌더에서 런타임과 Kubernetes 바이너리의
버전 명령을 실제 실행하고, kubeadm init/join 템플릿을 `kubeadm config migrate`로
파싱한다.

`ki2stage2.py verify-package-manager`는 실제 2단계 저장소 산출물을 대상으로
HTTP 설치, 로컬 미러 설치, Kubernetes 패키지 의존성 모의 실행을 확인한다.

`ki2stage2.py verify-install-plan`은 설치기가 만든 계획서가 선택한 Kubernetes 역할과
CRI 런타임에 맞는지 확인한다. 현재는 Go TUI가 `start` 또는 `--write`로 작성한
계획서를 2단계 CI에서 검증한다.

`ki2stage2.py verify-installed-rootfs`는 설치된 대상 루트 파일시스템에서 패키지 목록,
CRI 런타임 혼용 여부, kubelet 엔드포인트, systemd 활성화 상태, Kubernetes swap 비활성
상태를 점검한다. VM 설치 테스트 후 `/mnt/target` 또는 마운트한 디스크 루트 파일시스템에 대해
실행하는 사후 검증 명령이다.

`ki2ci.py run stage2`는 ISO를 만들지 않고 스모크 검증, CRI-O/containerd Kubernetes
프로파일 계획, Go TUI containerd 계획서 작성과 계약 검증, 2단계 준비도, 런타임/Kubernetes
바이너리 스모크, CRI-O/containerd 설치 루트 파일시스템 검증, 서명된 저장소 메타데이터 생성과
검증을 묶어 확인한다.

오프라인/로컬 미러 테스트:

```bash
ki2ctl repo set /run/install-media/kiki
ki2ctl update
ki2ctl install curl --dry-run

ki2ctl --repo file:///srv/kiki-mirror info kubelet
ki2ctl repo remove
```

저장소 서명:

```bash
python tools/ki2repo.py keygen --output build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2repo.py generate \
  --channel stage2-v2 \
  --sign-key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2repo.py verify --key build/ki2/keys/stage2-v2-repo.hmac
```

Kubernetes 프로파일 계획 확인:

```bash
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-bootstrap.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-control.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-bootstrap-containerd.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-control-containerd.yaml
python tools/ki2build.py plan --profile distro/profiles/kiki-kube-compute-containerd.yaml
```

Go TUI 미리보기:

```bash
go test ./cmd/kiki-installer-tui
go run ./cmd/kiki-installer-tui --profile kiki-kube-compute --render
go run ./cmd/kiki-installer-tui --write --plan ./install-plan.yaml
```

Go TUI source 명령:

```text
source local /run/install-media
source mirror /srv/kiki-mirror
source remote http://repo.example.internal:8080
verify-key /etc/ki2/trust/stage2-v2-repo.hmac
profile kiki-kube-compute-containerd
runtime containerd
```

2단계 설치 ISO 이름 예시:

```text
dist/iso/kiki-stage2-v2-installer-x86_64-YYYYMMDD-revN.iso
```

ISO는 사용자가 명시적으로 요청했을 때만 생성한다.

## 완료 증거

2026-07-01 전환 기준 2단계 검증 파이프라인:

- 명령: `python tools/test_ki2stage2.py`
- 명령: `python3 tools/ki2stage2.py verify-kubernetes --repo-root /mnt/f/GitHub/KIKI-OS --require-signed-metadata --strict-production`
- 명령: `python3 tools/ki2stage2.py verify-network-userspace --repo-root /mnt/f/GitHub/KIKI-OS --strict-production`
- 명령: `python3 tools/ki2stage2.py verify-package-manager --repo-root /mnt/f/GitHub/KIKI-OS`
- Kubernetes 준비도: `ok=247 warnings=0 errors=0`
- 네트워크 사용자 공간 엄격 검증: `ok=41 warnings=0 errors=0`
- 런타임/Kubernetes 바이너리 스모크: `ok=54 warnings=0 errors=0`
- Go TUI 설치 계획서 계약: `ok=27 warnings=0 errors=0`
- CRI-O Kubernetes 루트 파일시스템: `ok=41 warnings=0 errors=0`
- containerd Kubernetes 루트 파일시스템: `ok=40 warnings=0 errors=0`
- 패키지 관리자 저장소 흐름: `ok=44 warnings=0 errors=0`
- 저장소 요약: `stage2-v2`, `Packages: 62`, `Signed: True`
- 최신 설치 ISO: `dist/iso/kiki-stage2-v2-installer-x86_64-20260711-rev9.iso`
- 최신 설치 ISO sha256: `F4732724182765A1DC47B270255D9473078636A17957548BA281EBE89A902B06`

2026-07-19 마감 재검증:

- `python tools/test_ki2stage2.py`: 통과, `Ran 20 tests`
- `python tools/test_ki2bootiso.py`: 통과, `Ran 13 tests`, `skipped=3`
- `verify-kubernetes --require-signed-metadata --strict-production`: `ok=247 warnings=0 errors=0`
- `verify-network-userspace --strict-production`: `ok=41 warnings=0 errors=0`
- `verify-package-manager`: `ok=44 warnings=0 errors=0`

2단계 V2는 이 상태에서 기능 동결한다. 이후 기능 추가는 3단계 V3 문서와
별도 브랜치/커밋 범위로 관리한다.

## 1단계와의 경계

1단계 V1은 부팅/설치/로그인 기준선이다. 2단계 V2는 그 위에서 패키지와
운영 흐름을 만든다.

- 1단계 V1에서 고정: 부팅, 디스크 설치, 로그인, systemd 기본 서비스
- 2단계 V2에서 완료: 저장소, 패키지 관리자, 커널 파라미터 기반 무인 설치,
  Kubernetes 준비, CRI-O/containerd 런타임 프로파일

2단계 V2 이후에도 1단계 V1 기준선은 깨지지 않아야 한다.

## 3단계로 넘기는 기준

다음 항목은 2단계 V2가 아니라 3단계 후보로 둔다.

- KIKI OS 내부에서 KIKI OS를 다시 빌드하는 자체 빌드
- PXE/네트워크 부팅 설치
- 웹 기반 설치기
- Kubernetes 클러스터 전체 운영 자동화
- 장기 보안 업데이트 채널
- 실제 lab 인프라 운영 릴리스

## 2026-05-31 추가 메모: 2단계 무인 설치 경로

2단계 설치기는 이제 커널 파라미터 기반의 얇은 무인 설치 경로를 제공한다. 전체 YAML 파서를 initramfs의 C `/init` 안에 넣는 방식은 크기와 안정성 부담이 크므로, 2단계에서는 ISO 부팅 파라미터로 설치 계획의 핵심 입력값을 전달하고 설치기가 동일한 `kiki-install-plan-v1` 파일을 생성한 뒤 실행한다.

지원하는 파라미터:

```text
kiki.autoinstall=erase|quick-vm
kiki.profile=minimal-systemd|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute
kiki.profile=kiki-kube-bootstrap-containerd|kiki-kube-control-containerd|kiki-kube-compute-containerd
kiki.runtime=cri-o|crio|containerd|none
kiki.target=/dev/sda
kiki.hostname=localhost.localdomain
```

예시:

```text
kiki.autoinstall=erase kiki.profile=kiki-kube-compute-containerd kiki.runtime=containerd kiki.target=/dev/sda kiki.hostname=localhost.localdomain
```

동작 원칙:

- `kiki.autoinstall` 값이 없으면 기존 TUI 메뉴로 진입한다.
- `kiki.autoinstall=erase` 또는 `quick-vm`이 있을 때만 콘솔 확인 없이 설치를 진행한다.
- `kiki.target`이 없으면 가장 큰 VM 디스크를 자동 선택한다.
- Kubernetes 프로파일은 swap을 끄고 `runtime`, `kubernetes`, `firewall`, `artifacts` 섹션을 포함한 설치 계획서를 생성한다.
- 설치 중 `/run/kiki/install-plan.yaml`을 만들고, 설치 후 대상 rootfs의 `/var/lib/ki2/install-plan.yaml`로 보존한다.

3단계 후보:

- 원격 YAML 설치 계획서를 직접 가져와 해석하는 완전한 무인 설치 실행기는 3단계 초입에서 다룬다.
- 네트워크 사용자 공간은 2단계 검증을 위해 `host-files` 페이로드로 전환했다. 운영 재현성을 위해 3단계에서 소스 기반 빌드로 승격한다.
