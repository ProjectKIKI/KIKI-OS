# KIKI OS 네트워크 설정 도구

KIKI OS 2단계의 기본 네트워크 관리는 `systemd-networkd`와
`systemd-resolved`가 담당한다. 설치기는 기본값으로 DHCP를 기록하지만, 설치 후
운영 중에도 같은 규칙으로 네트워크를 바꿀 수 있도록 `kiki-netconfig` 패키지를
추가한다.

## 포함 프로필

`kiki-netconfig`는 다음 프로필에 기본 포함된다.

- `minimal-systemd`
- `node-network-tools`
- `world`
- `kiki-kube-bootstrap`
- `kiki-kube-control`
- `kiki-kube-compute`
- `kiki-kube-bootstrap-containerd`
- `kiki-kube-control-containerd`
- `kiki-kube-compute-containerd`

패키지 레시피는 `distro/recipes/core.toml`의 `kiki-netconfig` 항목이며, 실제
소스는 `distro/sources/kiki-netconfig/usr/bin/kiki-netconfig`다.

## 기본 DHCP

기본 유선 인터페이스 매칭은 `en* eth*`다.

```bash
sudo kiki-netconfig dhcp --apply
```

위 명령은 `/etc/systemd/network/20-kiki.network`를 다음 의미로 렌더링한다.

- `Name=en* eth*`
- `DHCP=ipv4`
- `IPv6AcceptRA=yes`
- `RequiredForOnline=routable`

설치 대상 루트 파일시스템에 미리 기록할 때는 다음처럼 쓴다.

```bash
sudo kiki-netconfig --root /mnt/target dhcp
```

`--root`가 `/`가 아니면 `--apply`를 붙여도 실제 서비스 재시작은 하지 않는다.

## 고정 IPv4

정적 주소는 주소/프리픽스만 필수이고, 게이트웨이/DNS/NTP는 선택이다.

```bash
sudo kiki-netconfig static \
  --match eth0 \
  --address 192.168.122.50/24 \
  --gateway 192.168.122.1 \
  --dns 1.1.1.1,8.8.8.8 \
  --ntp time.cloudflare.com \
  --apply
```

DNS 값을 `systemd-resolved` drop-in으로도 기록하려면 다음 옵션을 추가한다.

```bash
sudo kiki-netconfig static \
  --address 10.10.10.20/24 \
  --gateway 10.10.10.1 \
  --dns 10.10.10.53 \
  --write-resolved-dropin \
  --apply
```

정적 IPv4 기본값은 `IPv6AcceptRA=no`다. IPv6 RA를 함께 받고 싶으면
`--ipv6-ra`를 사용한다.

## 자동 설정 끄기

무인 설치, 오프라인 실험, 혹은 수동 `ip` 설정 테스트가 필요하면 networkd
자동 구성을 끌 수 있다.

```bash
sudo kiki-netconfig off --match eth0 --apply
```

이 명령은 `DHCP=no`, `LinkLocalAddressing=no`, `IPv6AcceptRA=no`를 기록한다.

## 점검

현재 렌더링된 설정만 확인한다.

```bash
kiki-netconfig show
```

실행 중인 OS에서는 `networkctl`과 `resolvectl` 상태까지 함께 확인할 수 있다.

```bash
kiki-netconfig status
```

설정을 파일에 쓰기 전에 미리 볼 때는 `--dry-run`을 쓴다.

```bash
kiki-netconfig static \
  --address 192.168.10.20/24 \
  --gateway 192.168.10.1 \
  --dns 192.168.10.1 \
  --dry-run
```

## 2단계 검증

`kiki-netconfig`는 2단계 네트워크 사용자 공간 검증 대상에 포함된다.

```bash
python tools/ki2stage2.py verify-network-userspace --strict-production
python tools/test_kiki_netconfig.py
```

ISO를 만들기 전에 위 검증을 통과하면 다음을 확인한 것이다.

- 패키지 레시피가 존재한다.
- `.ki2` 패키지 안에 `/usr/bin/kiki-netconfig`가 포함된다.
- DHCP/고정/비활성 렌더링 규칙이 깨지지 않는다.
