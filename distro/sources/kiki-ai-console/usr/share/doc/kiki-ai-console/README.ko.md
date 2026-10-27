# KIKI OS AI 관리 콘솔

`tty1`은 AI 관리 콘솔이고 `tty2`는 AI와 독립된 복구 셸입니다.
새 설치본의 tty1은 `kiki-ai-console-kmscon@tty1.service`로 설정됩니다.
이 서비스는 나눔고딕코딩 글꼴과
두벌식 입력을 사용합니다. `Ctrl+Space`로 한/영을 전환합니다.
복구용 tty2는 변경하지 않습니다. 실제 VM에서 전환 전에 검증하세요.
콘솔은 네트워크·디스크·서비스 상태를 읽어 로컬 모델에 전달하고, 모델이
반환한 정확한 명령과 영향 및 롤백 계획을 화면에 표시합니다. 사용자가
`execute`라고 입력하기 전에는 명령을 실행하지 않습니다.

인사와 일반 설명은 실행 명령이 없는 대화 응답으로 표시합니다.
관리 작업은 정확한 argv를 담은 계획으로 표시하고 승인을 기다립니다.
응답 JSON은 생성 시 스키마 제약과 수신 후 검증을 모두 적용합니다.
잘못되거나 잘린 응답은 한 번만 재시도하고, 계속 실패하면 실행하지 않습니다.
소형 모델의 답변/계획은 틀릴 수 있으므로 실행 전 반드시 검토하세요.

기본 런타임은 CPU용 `llama.cpp`이며 API는 `127.0.0.1:8080`에만 바인딩됩니다.
서버는 기본적으로 `systemd-nspawn` 경량 머신에서 실행되고, 머신 실행이
불가능하면 systemd 샌드박스 직접 실행으로 전환됩니다. tty1 콘솔은 서버의
`/health` 응답을 최대 90초 기다립니다.
기본 ISO에는 공식 `Qwen2.5-1.5B-Instruct-GGUF`의 `Q4_K_M` 모델이
`/var/lib/kiki/models/kiki-ops.gguf`로 포함됩니다. 모델과 함께 Apache-2.0
라이선스 전문을 설치하며, 빌드할 때 고정된 SHA-256을 검증합니다.

모델을 승인한 다른 GGUF로 교체했다면 다음을 실행합니다.

    systemctl restart kiki-llama-server.service

연결 오류 진단은 tty2에서 다음 순서로 수행합니다.

    systemctl status kiki-llama-server.service
    journalctl -b -u kiki-llama-server.service
    machinectl status kiki-ai-runtime
    curl http://127.0.0.1:8080/health

교체 모델의 SHA-256과 배포 라이선스는 별도로 기록하고 배치 전에 검증하십시오.
콘솔 감사 로그에는 승인된 명령이 그대로 기록되므로
명령 인자에 비밀번호나 토큰을 직접 넣지 않는 것이 좋습니다.

복구가 필요하면 `Ctrl+Alt+F2`로 전환하십시오. `tty2`의 getty는 모델 및
AI 콘솔 서비스와 의존 관계가 없습니다.
