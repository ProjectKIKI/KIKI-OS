# tty1 한글 입출력 시범 구성

새 설치본에서는 `kiki-ai-console-kmscon@tty1.service`를 기본으로 사용한다.
기존 설치본과 복구용 tty2는 자동 변경하지 않는다. 한글 콘솔은 KMS/FreeType에서
네이버 나눔고딕코딩 2.5를 사용한다. 글꼴 원본 ZIP과 README, OFL 문서는
빌드할 때 SHA-256으로 검증한다. 나눔고딕코딩에 없는 글리프를 위해
기존 Noto CJK 글꼴도 패키지에 유지한다.

tty1 AI 콘솔에서 `Ctrl+Space`로 영문/두벌식 한글을 전환한다.
입력 중인 글자는 완성형 UTF-8로 그리며, 지우기와 공백을 처리한다.
승인 명령(`execute`)은 기존대로 정확히 입력해야 한다.

후보 KI2 파일은 `dist/ki2/korean-console-candidate/`에 있다.
신규 `kiki-ai-console` release 6과 `kiki-kmscon` release 2를 모두
서명된 저장소에 반영하고 시험 VM에 설치한 뒤 다음처럼 전환한다.

```sh
sudo systemctl disable --now kiki-ai-console@tty1.service
sudo systemctl enable --now kiki-ai-console-kmscon@tty1.service
```

화면이 나오지 않으면 tty2에서 복구한다.

```sh
sudo systemctl disable --now kiki-ai-console-kmscon@tty1.service
sudo systemctl enable --now kiki-ai-console@tty1.service
```

두벌식 조합 단위 테스트, 가상 터미널 UTF-8 입출력 테스트,
글꼴/KMS 런타임 빌드는 통과했다.
실제 Hyper-V 화면·키보드 입력은 아직 검증하지 않았다. 따라서 기존 VM의
서비스 전환, 서명된 저장소/기존 ISO 교체, tty2 입력기 적용은 보류한다.
