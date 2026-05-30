# KIKI OS Stage 2 V2 진행 문서

`stage2-v2`는 KIKI OS를 “반복 설치 가능한 최소 서버 배포판”으로 끌어올리는
진행형 라인이다. 이 문서는 현재 구현된 내용, 진행 중인 작업, 완료 기준을
구분한다. Stage 2 V2는 아직 최종 릴리스가 아니다.

## 상태

- 릴리스 라인: `stage2-v2`
- 상태: 진행형
- 저장소 기본 channel: `stage2-v2`
- 설치 계획서 기본 channel: `stage2-v2`
- 저장소 서명 키 예시: `stage2-v2-repo.hmac`
- 목표: 온라인/오프라인 패키지 설치, 무인 설치, Kubernetes 노드 준비 기반

## 목표

Stage 2 V2의 목표는 Stage 1 V1에서 검증한 부팅/설치 흐름 위에 운영 가능한
패키지와 저장소 계층을 올리는 것이다.

- `ki2ctl` 온라인 패키지 설치와 의존성 해석
- HTTP 기반 `.ki2` 저장소 metadata/channel 운영
- 저장소 서명과 검증 흐름
- 설치된 시스템 패키지 DB
- Go 기반 설치 계획서 TUI를 주 설치기로 승격
- 무인 설치와 disconnected 설치 준비
- Kubernetes bootstrap/control/compute 프로파일
- CRI-O 기본 런타임
- containerd 선택 런타임
- 빌드 웹 콘솔과 프로파일 단위 빌드

## 현재 반영된 내용

현재 코드 기준으로 다음 항목은 Stage 2 V2 라인에 들어와 있다.

- `tools/ki2repo.py` 저장소 metadata, channel 파일 생성
- 기본 저장소 channel `stage2-v2`
- HMAC-SHA256 기반 개발용 저장소 서명/검증 흐름
- `ki2ctl` HTTP 저장소 설정, 업데이트, 검색, 설치 dry-run 흐름
- Go 기반 `kiki-installer-tui` preview
- 설치 계획서 source/repo/channel/verify-key 필드
- Kubernetes 역할 프로파일:
  - `kiki-kube-bootstrap`: 최초 bootstrap/control-plane 노드
  - `kiki-kube-control`: 추가 control-plane 노드
  - `kiki-kube-compute`: compute 노드
- Kubernetes 필수 패키지 선택 보장:
  - `cri-o`
  - `conmon`
  - `crun`
  - `cni-plugins`
  - `cri-tools`
  - `kubelet`
  - `kubeadm`
  - `kubectl`
  - `kube-node-config`
  - `nftables`
  - `iptables`
  - `conntrack-tools`
  - `firewalld`
  - `bridge-utils`
  - `socat`
  - `ethtool`
  - `chrony`
- `stage2-stub` 패키지 타입
- 빌드 웹 콘솔과 CI smoke 단계
- 날짜 + Git revision 기반 ISO 이름

## 진행 중인 내용

다음 항목은 구조가 잡혔지만 아직 완료로 보지 않는다.

- `kubelet`, `kubeadm`, `kubectl` 실제 upstream 바이너리 패키징
- `cri-o`, `conmon`, `crun` 실제 빌드 전환
- `cni-plugins`, `cri-tools` 실제 빌드 전환
- `nftables`, `iptables`, `conntrack-tools`, `socat` 실제 userspace 도구 검증
- kubelet systemd cgroup 설정
- CRI-O pause image와 registry 설정
- kubeadm init/join 선언형 입력
- 설치된 시스템 패키지 DB의 충돌/롤백 정책
- Go TUI를 실제 설치기의 주 흐름으로 연결
- 무인 설치 파일 형식 고정
- disconnected mirror 설치 검증

## 완료 기준

Stage 2 V2는 다음 조건을 만족할 때 완료로 본다.

1. 새 VM을 설치 계획서만으로 반복 설치할 수 있다.
2. HTTP 저장소에서 패키지를 설치할 수 있다.
3. 저장소 metadata 서명을 검증할 수 있다.
4. 설치된 패키지 DB가 파일 목록과 의존성을 기록한다.
5. 패키지 충돌을 탐지한다.
6. disconnected ISO 또는 로컬 mirror로 같은 설치를 재현할 수 있다.
7. Go TUI가 설치 계획서를 작성하고 실제 설치 흐름에 연결된다.
8. Kubernetes bootstrap/control/compute 프로파일이 실제 패키지 payload로 설치된다.
9. `crictl info`, `kubelet --version`, `kubeadm init --dry-run` 수준의 smoke test가 가능하다.
10. 운영자가 문서만 보고 Stage 2 노드를 다시 만들 수 있다.

## 명령 예시

저장소 metadata 생성:

```bash
python tools/ki2build.py repo-index
python tools/ki2repo.py generate --channel stage2-v2
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
```

Go TUI preview:

```bash
go test ./cmd/kiki-installer-tui
go run ./cmd/kiki-installer-tui --profile kiki-kube-compute --render
```

Stage 2 설치 ISO 이름 예시:

```text
dist/iso/kiki-stage2-v2-installer-x86_64-YYYYMMDD-revN.iso
```

ISO는 사용자가 명시적으로 요청했을 때만 생성한다.

## Stage 1과의 경계

Stage 1 V1은 부팅/설치/로그인 기준선이다. Stage 2 V2는 그 위에서 패키지와
운영 흐름을 만든다.

- Stage 1 V1에서 고정: 부팅, 디스크 설치, 로그인, systemd 기본 서비스
- Stage 2 V2에서 진행: 저장소, 패키지 관리자, 무인 설치, Kubernetes 준비

Stage 2 진행 중에도 Stage 1 V1 기준선은 깨지지 않아야 한다.

## Stage 3로 넘기는 기준

다음 항목은 Stage 2 V2가 아니라 Stage 3 후보로 둔다.

- KIKI OS 내부에서 KIKI OS를 다시 빌드하는 self-hosting
- PXE/네트워크 부팅 설치
- 웹 기반 설치기
- Kubernetes 클러스터 전체 운영 자동화
- 장기 보안 업데이트 채널
- 실제 lab 인프라 운영 릴리스
