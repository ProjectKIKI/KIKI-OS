# KIKI OS Stage 2 진행 메모

이 문서는 Stage 2의 1~6번 작업을 코드와 패키지 기준으로 정리한다. 현재 목표는
Stage 1에서 확인한 부팅/설치 흐름 위에 온라인 패키지 관리자, 서명 저장소,
네트워크 도구, 런타임, Kubernetes 노드 준비 패키지를 얹는 것이다.

## 현재 반영 범위

1. `ki2ctl` 트랜잭션 안정화
   - 설치 전 파일 충돌을 검사한다.
   - 다른 패키지가 소유한 파일이나 소유자가 없는 기존 파일을 덮어쓰지 않는다.
   - 설치 실패 시 변경 파일과 installed DB를 가능한 범위에서 rollback한다.
   - 트랜잭션 기록은 `/var/lib/ki2/transactions/*.json`에 남는다.
   - systemd unit, shared library, tmpfiles 설치 시 pending hook을 기록한다.

2. 저장소 메타데이터 서명
   - `tools/ki2repo.py keygen`, `generate --sign-key`, `verify` 명령을 추가했다.
   - `ki2ctl update --verify-key <key>`로 저장소 metadata 서명과 index 해시를 검증한다.
   - 현재 서명 방식은 Stage 2 개발용 `hmac-sha256`이다.
   - 운영 단계에서는 공개키 기반 서명으로 교체하는 것이 맞다.

3. 네트워크 패키지 준비
   - `nftables`, `iptables`, `conntrack-tools`, `firewalld`, `bridge-utils`,
     `socat`, `ethtool`, `chrony` 레시피를 Stage 2 패키지로 구성했다.
   - 아직 upstream source-backed binary가 아니라 경로, 의존성, 서비스, 기본 설정을
     예약하는 `stage2-stub` 패키지다.

4. Go 기반 설치 계획 TUI 확장
   - `kiki-installer-tui`에서 로컬/원격 저장소 source를 선택할 수 있다.
   - 원격 저장소 검증키 경로를 계획서에 기록할 수 있다.
   - 런타임 선택값은 `none`, `cri-o`, `containerd`를 지원한다.
   - 기본 네트워크는 계속 DHCP와 `systemd-networkd`다.

5. 컨테이너 런타임 패키지 준비
   - KIKI 기본 Kubernetes 런타임은 `cri-o`다.
   - 선택 런타임으로 `containerd`와 `runc` skeleton 패키지를 추가했다.
   - `crio.service`, `containerd.service`는 실제 바이너리 경로가 있을 때만 시작되도록
     `ConditionPathExists`를 사용한다. 따라서 skeleton만 설치된 VM에서 서비스 실패로
     부팅을 망가뜨리지 않는다.

6. Kubernetes 패키지 준비
   - `kubelet`, `kubeadm`, `kubectl`, `cri-tools`, `cni-plugins`,
     `kube-node-config`를 패키지 계획에 포함했다.
   - `kiki-kube-bootstrap`, `kiki-kube-controller`, `kiki-kube-node` 프로파일은
     기본값으로 CRI-O, CNI, kubelet, kubeadm, kubectl, nftables/firewalld 계층을 포함한다.
   - 설치기 패키지 선택 메뉴에는 bootstrap/controller/worker 전용 선택지를 추가한다.
   - 설치 직전 Kubernetes 필수 패키지 세트를 다시 보정하고, 누락된 패키지가 있으면
     설치를 중단한다.
     전체 패키지 선택의 `59`는 중복 release record를 제외한 고유 패키지 이름 수다.

## Stage 2 패키지 상태

현재 새로 생성한 Kubernetes/runtime/network 패키지는 운영용 바이너리 패키지가 아니라
설치 가능한 준비 패키지다. 패키지 안에는 다음이 들어간다.

- `/usr/bin`, `/usr/sbin`, `/opt/cni/bin` 아래 예약된 명령 경로
- `/usr/lib/systemd/system/*.service` 단위 파일
- `/etc` 아래 기본 설정 또는 README
- `/usr/share/doc/kiki-stage2/<package>.txt`
- `/usr/share/kiki/stage2/<package>.json`

stub 명령은 `--version`에는 0으로 응답하고, 실제 실행 시에는 Stage 2 placeholder임을
알린 뒤 종료 코드 69로 끝난다.

## 저장소 생성 명령

서명키는 publish 대상인 `dist/ki2/repo` 아래에 두지 않는다. 기본 위치는 다음이다.

```bash
python tools/ki2repo.py keygen --output build/ki2/keys/stage2-repo.hmac
```

저장소 메타데이터 생성과 서명:

```bash
python tools/ki2repo.py generate \
  --channel stage2 \
  --base-url http://repo.example.internal:8080 \
  --sign-key build/ki2/keys/stage2-repo.hmac
```

검증:

```bash
python tools/ki2repo.py verify --key build/ki2/keys/stage2-repo.hmac
python tools/ki2repo.py summary
```

설치된 KIKI OS에서 검증 업데이트:

```bash
sudo ki2ctl repo set http://repo.example.internal:8080
sudo ki2ctl update --verify-key /etc/ki2/trust/stage2-repo.hmac
```

## Go TUI 명령 예시

```text
source local
source remote http://repo.example.internal:8080
verify-key /etc/ki2/trust/stage2-repo.hmac
runtime crio
runtime containerd
profile kiki-kube-node
write /run/kiki/install-plan.yaml
```

TUI 계획서에는 `source.repo_url`, `source.channel`, `source.verify_key`,
`runtime.container_runtime`이 기록된다.

## 현재 산출물 메모

2026-05-26 기준 Stage 2 저장소 메타데이터:

- repository channel: `stage2`
- package records: 92
- unique package names: 59
- `ki2ctl`: `0.1.0-5`
- `kiki-installer-tui`: `0.1.0-2`
- 저장소 metadata: signed, `hmac-sha256`

2026-05-26 Stage 2 테스트 ISO:

- file: `dist/iso/kiki-stage2-test-installer-x86_64-20260526.iso`
- size: `879187968` bytes
- sha256: `79EBAC0C2DE64145D6DF1351D52027CFF450847DF91507FDE2117FA319EF97EF`
- mode: stage-1 installer ISO
- Hyper-V VHDX: 생성하지 않음
- 기존 `kiki-stage2-test-installer-x86_64.iso`가 VM에 연결되어 있으면 Windows가 파일을
  잠글 수 있으므로, 이번 산출물은 날짜가 붙은 파일명으로 보존했다.

이후 ISO 기본 파일명은 다음 규칙을 따른다.

```text
kiki-<release-channel>-<mode>-<arch>-YYYYMMDD-revN.iso
```

`release-channel`은 기본적으로 저장소 metadata의 `channel` 값이다. Stage 2
저장소에서는 `stage2`가 되며, `revN`은 `git rev-list --count HEAD` 기준이다.
`--release-name` 또는 `--output`을 지정하면 운영자가 명시한 이름을 우선한다.

ISO payload 확인 항목:

- `/kiki/repo/metadata.x86_64.json`
- `/kiki/packages/x86_64/ki2ctl-0.1.0-5.x86_64.ki2`
- `/kiki/packages/x86_64/kubelet-1.36.1-1.x86_64.ki2`
- `/kiki/packages/x86_64/kubeadm-1.36.1-1.x86_64.ki2`
- `/kiki/packages/x86_64/kubectl-1.36.1-1.x86_64.ki2`
- `/kiki/packages/x86_64/cri-o-1.36.0-1.x86_64.ki2`
- `/kiki/packages/x86_64/containerd-2.1.0-1.x86_64.ki2`
- `/kiki/packages/x86_64/nftables-1.1.1-1.x86_64.ki2`
- `/boot/initramfs-kiki.img` 안에 `sbin/cfdisk`, `lib/libsmartcols.so.1`,
  `lib/libtinfo.so.6`, `lib/libncursesw.so.6` 포함 확인

ISO는 시간이 오래 걸리므로 이후에도 사용자가 명시적으로 요청할 때만 생성한다.

## 다음 작업

- CRI-O, conmon, crun의 source-backed build 전환
- containerd, runc의 source-backed build 전환
- Kubernetes `kubelet`, `kubeadm`, `kubectl` 실제 바이너리 빌드
- nftables, iptables, conntrack-tools 실제 userspace 빌드
- HMAC 서명을 공개키 기반 repository signing으로 교체
- `ki2ctl` pre/post install/remove hook 규격화
- 설치기에서 원격 저장소와 disconnected mirror를 실제 설치 플로우에 연결
