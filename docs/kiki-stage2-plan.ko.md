# KIKI OS Stage 2 진행 메모

이 문서는 `stage2-v2`의 상세 작업 메모다. 현재 진행 기준과 완료 조건은
[KIKI OS Stage 2 V2 완료 문서](kiki-stage2-v2-progress.ko.md)를 우선한다.

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
   - HTTP, `file://`, 로컬 경로 기반 저장소를 같은 명령으로 다룬다.
   - `repo remove`로 저장소 설정과 캐시된 인덱스를 제거할 수 있다.

2. 저장소 메타데이터 서명
   - `tools/ki2repo.py keygen`, `generate --sign-key`, `verify` 명령을 추가했다.
   - `ki2ctl update --verify-key <key>`로 저장소 metadata 서명과 index 해시를 검증한다.
   - 현재 서명 방식은 Stage 2 개발용 `hmac-sha256`이다.
   - 운영 단계에서는 공개키 기반 서명으로 교체하는 것이 맞다.

3. 네트워크 패키지 준비
   - `nftables`, `iptables`, `conntrack-tools`, `firewalld`, `bridge-utils`,
     `socat`, `ethtool`, `chrony` 레시피를 Stage 2 패키지로 구성했다.
   - Stage 2에서는 빌더 호스트의 검증된 바이너리와 필요한 공유 라이브러리를
     `host-files` payload로 묶는다.
   - Stage 3에서는 이 계층을 source-backed build 또는 upstream release artifact 기반으로 승격한다.

4. Go 기반 설치 계획 TUI 확장
   - `kiki-installer-tui`에서 local installer media, mirror, remote repository source를 선택할 수 있다.
   - 원격 저장소 검증키 경로를 계획서에 기록할 수 있다.
   - 런타임 선택값은 `none`, `cri-o`, `containerd`를 지원한다.
   - 기본 네트워크는 계속 DHCP와 `systemd-networkd`다.

5. 컨테이너 런타임 패키지 준비
   - KIKI 기본 Kubernetes 런타임은 `cri-o`다.
   - 선택 런타임인 `containerd`와 `runc`는 pinned upstream release binary를
     `.ki2`로 재패키징한다.
   - `kube-node-config-containerd`를 추가해 `crictl`과 `kubelet` endpoint를
     `unix:///run/containerd/containerd.sock`으로 맞출 수 있다.
   - `kiki-kube-bootstrap-containerd`, `kiki-kube-control-containerd`,
     `kiki-kube-compute-containerd` 프로파일과 설치 계획서를 추가했다.
   - `crio.service`는 아직 skeleton 보호를 위해 `ConditionPathExists`를 사용한다.
     `containerd.service`는 실제 `/usr/bin/containerd`를 실행한다.

6. Kubernetes 패키지 준비
   - `kubelet`, `kubeadm`, `kubectl`, `cri-tools`, `cni-plugins`,
     `kube-node-config`, `kube-node-config-containerd`를 패키지 계획에 포함했다.
   - `kubelet`, `kubeadm`, `kubectl`, `cri-tools`, `cni-plugins`는 pinned upstream
     release binary를 `.ki2`로 재패키징한다.
   - `kiki-kube-bootstrap`, `kiki-kube-control`, `kiki-kube-compute` 프로파일은
     기본값으로 CRI-O, CNI, kubelet, kubeadm, kubectl, nftables/firewalld 계층을 포함한다.
   - `*-containerd` 프로파일은 CRI-O 대신 containerd, runc, containerd용 kube-node config를 포함한다.
   - 설치기 패키지 선택 메뉴에는 bootstrap/control/compute 전용 선택지를 추가한다.
   - 설치 직전 Kubernetes 필수 패키지 세트를 다시 보정하고, 누락된 패키지가 있으면
     설치를 중단한다.
   - `kube-node-config*`는 kubeadm v1beta4 init/control-plane join/compute join
     템플릿을 `/etc/kubernetes/kiki/` 아래 설치한다.
   - 설치 계획서는 role, kubeadm action, config template, local config output,
     command, CRI socket을 명시한다.
     전체 패키지 선택의 `60`은 중복 release record를 제외한 고유 패키지 이름 수다.

## Stage 2 패키지 상태

현재 Stage 2 패키지는 두 종류가 섞여 있다.

containerd 계열과 Kubernetes 기본 도구는 실제 upstream release binary payload를 담는다.

- `runc`
- `containerd`
- `cni-plugins`
- `cri-tools`
- `kubelet`
- `kubeadm`
- `kubectl`

network userspace 도구는 `host-files` 빌드 타입으로 실제 명령과 공유 라이브러리를
패키지에 담는다. 이 방식은 Stage 2 검증용 bootstrap packaging이며, 소스 빌드 재현성은
Stage 3에서 강화한다.

- `conntrack-tools`: `/usr/sbin/conntrack`
- `nftables`: `/usr/sbin/nft`, `nftables.service`, 기본 `/etc/nftables.conf`
- `iptables`: nft 호환 `iptables`, `ip6tables`, save/restore 명령
- `firewalld`: `firewalld`, `firewall-cmd`, `firewalld.service`
- `bridge-utils`: `/usr/sbin/bridge`와 `brctl` 호환 wrapper
- `socat`, `ethtool`, `chrony`: 실제 명령과 `chronyd.service`

## 저장소 생성 명령

서명키는 publish 대상인 `dist/ki2/repo` 아래에 두지 않는다. 기본 위치는 다음이다.

```bash
python tools/ki2repo.py keygen --output build/ki2/keys/stage2-v2-repo.hmac
```

저장소 메타데이터 생성과 서명:

```bash
python tools/ki2repo.py generate \
  --channel stage2-v2 \
  --base-url http://repo.example.internal:8080 \
  --sign-key build/ki2/keys/stage2-v2-repo.hmac
```

검증:

```bash
python tools/ki2repo.py verify --key build/ki2/keys/stage2-v2-repo.hmac
python tools/ki2repo.py summary
```

ISO 없이 Stage 2 기준선을 검증하려면 다음 파이프라인을 사용한다.

```bash
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

`ki2stage2.py verify-kubernetes`는 CRI-O/containerd 프로파일과 설치 계획서가 서로
섞이지 않았는지, Kubernetes/runtime 패키지 payload가 필요한 경로와 설정을 담고
있는지 확인한다. `--strict-production`을 붙이면 아직 `stage2-stub`인 패키지를
실패로 처리한다.

`ki2stage2.py verify-network-userspace`는 `nftables`, `iptables`,
`conntrack-tools`, `socat`, `firewalld`, `bridge-utils`, `ethtool`, `chrony`의
명령/서비스 경로와 placeholder metadata 부재를 확인한다. `--strict-production`을
붙이면 placeholder가 하나라도 남았을 때 실패한다.

`ki2stage2.py verify-binary-smoke`는 `runc`, `containerd`, `conmon`, `crun`,
`crio`, `crictl`, `critest`, `kubelet`, `kubeadm`, `kubectl`을 패키지에서
임시 rootfs로 추출한 뒤 버전 명령을 실행한다. 또한 `kube-node-config*`의
kubeadm init/join 템플릿을 `kubeadm config migrate`로 파싱해 템플릿 형식도
확인한다. 이 검증은 Linux/WSL 빌더에서 실행해야 한다.

`ki2stage2.py verify-installed-rootfs`는 설치된 디스크 rootfs를 대상으로 패키지 목록,
CRI endpoint, kubelet/systemd enable 상태, Kubernetes swap 비활성 상태를 확인한다.

`ki2stage2.py verify-package-manager`는 실제 `dist/ki2` 저장소를 HTTP와 local mirror
방식으로 `ki2ctl`에 연결하고, `base-files` 설치와 Kubernetes 패키지 의존성 dry-run을
검증한다.

`ki2stage2.py verify-install-plan`은 stage-1 설치기 또는 Go TUI가 만든 설치 계획서가
bootstrap/control/compute 역할, CRI 런타임, kubeadm 템플릿, local config output,
CRI socket, 설치 계획서 보존 경로를 올바르게 기록했는지 검증한다.

`stage2` 파이프라인은 smoke 테스트, CRI-O/containerd Kubernetes 프로파일 계획, Go TUI
containerd 계획서 작성과 계약 검증, readiness 검증, 런타임/Kubernetes 바이너리 smoke, CRI-O/containerd
설치 rootfs 조립과 `verify-installed-rootfs`, 저장소 인덱스와 서명된 `stage2-v2`
metadata 생성을 확인한다. POSIX/WSL 환경에서는 rootfs 조립을 `/tmp/kiki-ki2ci/`
아래에서 수행해 Windows 마운트 성능 병목을 피한다.

설치된 KIKI OS에서 검증 업데이트:

```bash
sudo ki2ctl repo set http://repo.example.internal:8080
sudo ki2ctl update --verify-key /etc/ki2/trust/stage2-v2-repo.hmac
sudo ki2ctl repo remove
```

## Go TUI 명령 예시

```text
source local /run/install-media
source mirror /srv/kiki-mirror
source remote http://repo.example.internal:8080
verify-key /etc/ki2/trust/stage2-v2-repo.hmac
runtime crio
runtime containerd
profile kiki-kube-compute
profile kiki-kube-compute-containerd
start
write /run/kiki/install-plan.yaml
```

TUI 계획서에는 `source.repo_url`, `source.channel`, `source.verify_key`,
`runtime.container_runtime`, `kubernetes.kubeadm.*`, `artifacts.runtime_plan`,
`artifacts.installed_plan`이 기록된다. Stage 2 V2에서 실제 디스크 설치는 initramfs의
Stage 1 설치기가 담당하고, Go TUI는 같은 계획서 계약을 작성/검증하는 preview와
운영자용 plan authoring 도구로 둔다. Go TUI를 단독 설치기로 승격하는 작업은 Stage 3
후보로 넘긴다.

## 현재 산출물 메모

2026-05-31 기준 Stage 2 저장소 메타데이터:

- repository channel: `stage2-v2`
- package records: 60
- unique package names: 60
- `ki2ctl`: `0.1.0-6`
- `kiki-installer-tui`: `0.1.0-4`
- `conmon`: `2.1.13-2`
- `crun`: `1.23.1-2`
- `cri-o`: `1.36.0-2`
- `runc`: `1.3.0-2`
- `containerd`: `2.1.0-3`
- `cni-plugins`: `1.7.0-2`
- `cri-tools`: `1.36.0-2`
- `kubelet`: `1.36.1-3`
- `kubeadm`: `1.36.1-2`
- `kubectl`: `1.36.1-2`
- `kube-node-config`: `0.1.0-3`
- `kube-node-config-containerd`: `0.1.0-2`
- `conntrack-tools`: `1.4.7-2`
- `nftables`: `1.0.9-2`
- `iptables`: `1.8.10-2`
- `firewalld`: `1.3.4-2`
- `bridge-utils`: `0.1.0-2`
- `socat`: `1.7.4.1-2`
- `ethtool`: `6.15-2`
- `chrony`: `4.8-2`
- 저장소 metadata: `stage2` 파이프라인에서는 임시 HMAC 키로 서명/검증한다. 수동 `ki2repo.py generate`는 `--sign-key`를 주지 않으면 unsigned로 생성된다.
- `ki2stage2.py verify-kubernetes --require-signed-metadata --strict-production` 기준: `ok=228 warnings=0 errors=0`
- `ki2stage2.py verify-network-userspace --strict-production` 기준: `ok=26 warnings=0 errors=0`
- `ki2stage2.py verify-installed-rootfs --runtime cri-o` 기준: `ok=41 warnings=0 errors=0`
- `ki2stage2.py verify-installed-rootfs --runtime containerd` 기준: `ok=40 warnings=0 errors=0`
- `ki2stage2.py verify-package-manager` 기준: `ok=27 warnings=0 errors=0`
- Kubernetes/runtime readiness 대상 패키지의 남은 placeholder: 없음
- network userspace 패키지의 남은 placeholder: 없음
- `ki2ci.py run stage2` 최종 통과 job: `20260531-021152-7191`
- Stage 2 repository summary: `Packages: 60`, `Signed: True`

2026-05-26 Stage 2 테스트 ISO:

- file: `dist/iso/kiki-stage2-v2-test-installer-x86_64-20260526.iso`
- size: `879187968` bytes
- sha256: `79EBAC0C2DE64145D6DF1351D52027CFF450847DF91507FDE2117FA319EF97EF`
- mode: stage-1 installer ISO
- Hyper-V VHDX: 생성하지 않음
- 기존 `kiki-stage2-v2-test-installer-x86_64.iso`가 VM에 연결되어 있으면 Windows가 파일을
  잠글 수 있으므로, 이번 산출물은 날짜가 붙은 파일명으로 보존했다.

이후 ISO 기본 파일명은 다음 규칙을 따른다.

```text
kiki-<release-channel>-<mode>-<arch>-YYYYMMDD-revN.iso
```

`release-channel`은 기본적으로 저장소 metadata의 `channel` 값이다. Stage 2
저장소에서는 `stage2-v2`가 되며, `revN`은 `git rev-list --count HEAD` 기준이다.
`--release-name` 또는 `--output`을 지정하면 운영자가 명시한 이름을 우선한다.

ISO payload 확인 항목:

- `/kiki/repo/metadata.x86_64.json`
- `/kiki/packages/x86_64/ki2ctl-0.1.0-6.x86_64.ki2`
- `/kiki/packages/x86_64/conmon-2.1.13-2.x86_64.ki2`
- `/kiki/packages/x86_64/crun-1.23.1-2.x86_64.ki2`
- `/kiki/packages/x86_64/cri-o-1.36.0-2.x86_64.ki2`
- `/kiki/packages/x86_64/runc-1.3.0-2.x86_64.ki2`
- `/kiki/packages/x86_64/containerd-2.1.0-3.x86_64.ki2`
- `/kiki/packages/x86_64/cni-plugins-1.7.0-2.x86_64.ki2`
- `/kiki/packages/x86_64/cri-tools-1.36.0-2.x86_64.ki2`
- `/kiki/packages/x86_64/kubelet-1.36.1-3.x86_64.ki2`
- `/kiki/packages/x86_64/kubeadm-1.36.1-2.x86_64.ki2`
- `/kiki/packages/x86_64/kubectl-1.36.1-2.x86_64.ki2`
- `/kiki/packages/x86_64/kube-node-config-0.1.0-3.x86_64.ki2`
- `/kiki/packages/x86_64/kube-node-config-containerd-0.1.0-2.x86_64.ki2`
- `/kiki/packages/x86_64/nftables-1.0.9-2.x86_64.ki2`
- `/kiki/packages/x86_64/iptables-1.8.10-2.x86_64.ki2`
- `/kiki/packages/x86_64/conntrack-tools-1.4.7-2.x86_64.ki2`
- `/boot/initramfs-kiki.img` 안에 `sbin/cfdisk`, `lib/libsmartcols.so.1`,
  `lib/libtinfo.so.6`, `lib/libncursesw.so.6` 포함 확인

ISO는 시간이 오래 걸리므로 이후에도 사용자가 명시적으로 요청할 때만 생성한다.

## 다음 작업

- CRI-O, conmon, crun의 source-backed build 전환
- containerd 계열 upstream-binary packaging을 source-backed build로 승격
- Kubernetes `kubelet`, `kubeadm`, `kubectl` upstream-binary packaging을 source-backed build로 승격
- network userspace `host-files` bootstrap packaging을 source-backed build로 승격
- HMAC 서명을 공개키 기반 repository signing으로 교체
- `ki2ctl` pre/post install/remove hook 규격화
- Go TUI 단독 설치기 승격과 원격 YAML unattended executor
