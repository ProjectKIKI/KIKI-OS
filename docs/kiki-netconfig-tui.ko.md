# 간단한 네트워크 설정

`sudo kiki-netconfig tui`로 실행합니다. 실제 장치 목록에서 번호를 선택하고 DHCP 또는 고정 IP를 선택한 뒤 검토합니다. 한글 콘솔 글꼴이 없는 환경을 위해 화면은 영어입니다.

- `s`: 저장만 합니다. 재부팅이나 이후 networkd 재구성 시 반영됩니다.
- `a`: 저장하고 적용합니다. 추가로 `APPLY`를 입력해야 합니다.
- `q` 또는 빈 입력: 취소합니다.
- `kiki-netconfig tui --dry-run`: 파일이나 네트워크를 변경하지 않는 미리보기입니다.
- `kiki-netconfig list`: 장치 이름과 IPv4 주소를 출력합니다.

설정은 `/etc/systemd/network/10-kiki-장치명.network`에 저장합니다. 이 도구가 생성한 기존 파일은 변경 전 `.bak-시간값`으로 백업하고, 사용자가 따로 만든 동일 경로 파일은 덮어쓰지 않습니다. 다른 설정 파일은 수정하지 않습니다. 먼저 매칭되는 다른 networkd 파일이 있으면 이 설정보다 우선할 수 있습니다.

적용은 SSH 연결을 끊을 수 있습니다. 자동 시간제 복구 기능은 없으므로 콘솔에서 사용을 권장합니다. 적용 후 `networkctl status 장치명`으로 확인하세요. 저장만 했어도 이후 재구성에 영향을 줍니다.

이 기능은 kiki-netconfig 0.1.0 release 2 소스에 추가했습니다. 기존 r15 ISO에는 포함되지 않습니다.

검증: `python3 -m unittest tools/test_kiki_netconfig.py`. 실제 VM 미리보기 캡처는 `tools/ki2netconfigscreen.py`로 일회용 overlay에서 수행합니다. 미리보기 검증은 실제 네트워크 적용 성공을 의미하지 않습니다.
