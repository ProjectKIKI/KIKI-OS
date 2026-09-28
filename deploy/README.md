# KIKI 배포 경계

`kubernetes/base`는 일반 노드에서 Pod로 운영하는 InfraOps, 모델 Pod 조정기, 읽기 전용 인벤토리 DaemonSet을 배포한다. 적용 전 모든 `registry.invalid` 다이제스트를 검증된 릴리스 다이제스트로 교체하고 `kiki-infraops-auth`에 서로 다른 `admin-token`, `agent-token`, `factory-token`을 넣는다. 같은 값을 재사용하면 API 역할 경계가 무너진다. 신뢰된 공급망 결과 보고자용 `build-token`도 별도로 추가한다.

Git·소스 아카이브·레지스트리 허용 목록, 프록시 URL/CIDR, BuildKit 주소/CIDR, 0으로 채워진 예시 다이제스트를 실제 값으로 교체한다. 외부에서 관리하는 rootless BuildKit 엔드포인트와 `kiki-build`의 `kiki-registry-auth`, `kiki-artifact-signing`, `build-artifacts` PVC를 제공한다. 저장소는 임의의 비밀 값이나 스토리지 클래스를 가정하지 않아 이 리소스를 예시 값으로 만들지 않는다.

## 빌드와 격리

다이제스트 고정 `bos-builder` 이미지는 일반 셸 이미지가 아닌 빌드 프로필이다. `/usr/local/bin/bosbuild`, `/usr/local/bin/kiki-bos-recipe`, `/usr/local/bin/kiki-bos-deps`를 포함해야 한다. `/etc/kiki/bos-build-capabilities.json`에는 불변 이미지에 이미 포함된 빌드 의존성을 나열한다. Recipe의 `build_requires`가 목록에 없는 기능을 요구하면 거부하며 빌드 도중 미승인 저장소에서 패키지를 설치하지 않는다.

웹 UI는 Recipe 요청마다 `.bos` 산출물 하나를 생성한다. 입력 소스는 자격 증명이 없는 HTTPS `tar.gz` URL과 정확한 SHA-256이다. 빌더는 경로 순회·링크·선언되지 않은 출력·해시 불일치·`-allowed-source-hosts` 밖의 호스트를 거부한다. 기존 Git 패키지 트리는 고급 빌드 모드로 유지한다.

`kiki-system`은 인벤토리 DaemonSet의 호스트 PID 조회와 읽기 전용 machine-id 마운트 때문에 제한적으로 특권을 가진다. 모델 런타임 Pod는 Restricted 정책의 `kiki-models` 네임스페이스에 배치한다. 일반 사용자 워크로드를 `kiki-system`에 배치하지 않는다.

`image-factory/kiki-image-factory.service`는 일반 노드 Pod가 아니다. KVM, Podman, xorriso, QEMU/OVMF, Syft, Grype, Cosign이 있는 폐기 가능한 VM 또는 전용 호스트에만 설치한다. 해당 호스트는 일반 워크로드 풀에 참여하지 않는다. 공장 토큰에는 Image Factory 수령·결과 권한만 주고 서명 키와 토큰은 각각 별도의 root 관리 파일에 둔다.

InfraOps는 ClusterIP 서비스다. 인증된 TLS Gateway/Ingress로만 노출하고 게이트웨이 네임스페이스에만 `kiki.io/infraops-client=true` 레이블을 붙인다. 그렇지 않으면 NetworkPolicy가 포트 8090 접근을 시스템 평면과 노드 에이전트로 제한한다.

실제 임의 토큰은 셸 기록에 입력하지 말고 비밀 관리자에서 파일로 공급한다.

```sh
kubectl -n kiki-system create secret generic kiki-infraops-auth \
  --from-file=admin-token=/secure/admin-token \
  --from-file=agent-token=/secure/agent-token \
  --from-file=factory-token=/secure/factory-token \
  --from-file=build-token=/secure/build-token
kubectl -n kiki-build create secret generic kiki-build-reporter \
  --from-file=build-token=/secure/build-token
```
