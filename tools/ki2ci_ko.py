"""Korean presentation for the preserved builder protocol and original logs."""
from html.parser import HTMLParser
import html
import datetime as dt
import json
from pathlib import Path
import re

TEXT = {
    'Dashboard':'운영 현황','Jobs':'빌드 작업','Packages':'패키지','Build KI2':'개별 패키지 빌드',
    'Profiles':'구성 프로필','Artifacts':'산출물','Security':'검증 현황','Deploy':'서버 구성',
    'KIKI Operations Dashboard':'KIKI 운영 현황','KIKI Jobs':'KIKI 빌드 작업',
    'KIKI Packages':'KIKI 패키지','KIKI Individual Package Build':'KIKI 개별 패키지 빌드',
    'KIKI Profiles':'KIKI 구성 프로필','KIKI Artifacts':'KIKI 산출물','KIKI Security':'KIKI 검증 현황',
    'KIKI Deploy':'KIKI 서버 구성','KIKI Build Job':'KIKI 빌드 작업 상세',
    'Pipelines':'빌드 절차','Pipeline':'빌드 절차','Run Pipeline':'빌드 작업 요청',
    'Recent Jobs':'최근 작업','Recent jobs':'최근 작업','Builder':'빌드 환경','Built':'빌드 완료',
    'Queued builds':'대기 중인 작업','Running builds':'실행 중인 작업','Unpinned':'해시 미고정',
    'Queue build':'작업 등록','Build package':'패키지 빌드 시작','Execution plan':'실행 계획',
    'Build one KI2 recipe':'KI2 패키지 개별 빌드',
    'Select an existing reviewed recipe. Dependencies build in an isolated job directory; this does not sign or publish packages.':
        '검토된 패키지 빌드 명세를 선택하세요. 의존 패키지는 작업별 공간에서 빌드하며, 서명·배포는 별도 단계입니다.',
    'One build runs at a time, in submission order. Compiler parallelism: ':'요청 순서대로 한 작업씩 실행합니다. 동시 컴파일 수: ',
    '. Select a pipeline to preview its steps.':'. 빌드 절차를 선택하면 실행 계획을 확인할 수 있습니다.',
    'Arch':'아키텍처','Toolchain':'도구 체인','Repo Root':'작업 경로','Publish Dir':'배포 경로',
    'Job':'작업','Created':'등록 시각','Status':'상태','Step':'단계','Exit':'종료 코드',
    'Version':'버전','Tier':'분류','Runtime':'실행 의존성','Build':'빌드 의존성','Source':'소스',
    'Artifact':'산출물','Files':'파일 수','Package':'패키지','Name':'이름','Size':'크기','Path':'경로',
    'Profile':'프로필','Description':'설명','Roots':'기본 패키지','Runtime Plan':'실행 구성','Build Plan':'빌드 구성',
    'Package Artifacts':'패키지 산출물','Repo Packages':'저장소 패키지','Rootfs Trees':'시스템 파일 트리',
    'ISO Images':'ISO 이미지','ISOs':'ISO 이미지','Disk Images':'디스크 이미지','Publish':'배포',
    'Target':'대상','Manifest':'목록 파일','Rootfs':'시스템 파일 트리','No jobs yet':'등록된 작업이 없습니다.',
    'No packages':'패키지가 없습니다.','No ISO images':'ISO 이미지가 없습니다.',
    'No disk images':'디스크 이미지가 없습니다.','No rootfs directories':'시스템 파일 트리가 없습니다.',
    'not published':'배포 전','Unpinned Sources':'해시 미고정 소스','Scanners Present':'설치된 검사 도구',
    'Shell Scripts':'셸 스크립트','Source Pins':'소스 해시 고정 상태','Scanners':'검사 도구',
    'Present: ':'설치됨: ','Missing: ':'없음: ','Server Units':'서버 서비스','Build Console':'빌드 콘솔',
    'Nightly Build':'정기 빌드','Nightly Timer':'정기 실행 타이머','SVN Hook':'SVN 연결',
    'Publish Targets':'배포 대상','Package Repo':'패키지 저장소','APIs':'API 주소','Overview':'운영 현황',
    'Back to builds':'작업 목록으로','Cancel queued build':'대기 작업 취소','Retry entire build':'전체 작업 다시 실행',
    'KI2 artifacts':'KI2 산출물','Refresh this page after completion to see new downloads.':'작업 완료 후 새로고침하면 다운로드가 표시됩니다.',
    'None yet':'아직 없습니다.','Build log':'빌드 로그','Follow output':'최신 출력 따라가기',
    'none':'없음','missing':'없음','n/a':'해당 없음','pinned':'해시 고정','unpinned':'해시 미고정',
    'pending':'대기','running':'실행 중','succeeded':'완료','failed':'실패','cancelled':'취소됨',
    'interrupted':'중단됨','skipped':'건너뜀',
    'smoke':'기본 검사','bootstrap':'기초 시스템 빌드','minimal-systemd':'최소 systemd 시스템',
    'stage2':'Stage 2 검사','security':'보안 검사','iso':'일반 ISO 생성','bootiso':'부팅 ISO 생성',
    'installer-iso':'설치 ISO 생성','publish':'산출물 배포','release':'전체 빌드 및 배포',
    'native-inputs':'고정 후보 SHA·서명 검사','native-llvm-mesa':'LLVM·Mesa 소스 빌드 및 검증',
    'Native candidate: verify':'고정 후보 SHA·공식 서명 확인','Native candidate: prepare':'격리 SDK 준비',
    'Native candidate: llvm':'LLVM 네이티브 소스 빌드','Native candidate: mesa':'Mesa 네이티브 소스 빌드',
    'Native candidate: validate':'패키지 SHA·ELF 의존성·렌더링 검증',
    'Go unit tests':'Go 단위 검사','Python syntax checks':'Python 문법 검사',
    'Core seed profile validation':'기초 패키지 프로필 검사','Security audit':'보안 설정 검사',
    'Write package repository index':'패키지 저장소 인덱스 생성','Publish build artifacts':'빌드 산출물 배포',
    'KIKI management console unit tests':'KIKI 관리 콘솔 단위 검사',
    'KIKI OS build orchestrator unit tests':'OS 빌드 실행기 단위 검사',
    'ki2ci queue and execution tests':'빌드 대기열·실행 검사',
    'Go TUI containerd install plan render':'Go 설치기 containerd 설치 계획 확인',
    'Native GNOME 50 desktop dependency':'GNOME 50 데스크톱 의존 패키지',
    'Generate Stage 2 repository signing key':'Stage 2 저장소 서명키 생성',
    'Generate signed Stage 2 repository metadata':'Stage 2 서명 메타데이터 생성',
    'Summarize Stage 2 repository':'Stage 2 저장소 요약',
    'Verify Go TUI Stage 2 install plan contract':'Go 설치기 Stage 2 설치 계획 검사',
    'Verify Stage 2 Kubernetes readiness':'Stage 2 Kubernetes 준비 상태 검사',
    'Verify Stage 2 network userspace package status':'Stage 2 네트워크 패키지 상태 검사',
    'Verify Stage 2 package manager repository flows':'Stage 2 패키지 관리자 저장소 동작 검사',
    'Verify Stage 2 runtime and Kubernetes binary smoke':'Stage 2 런타임·Kubernetes 바이너리 기초 검사',
    'Verify installed Stage 2 CRI-O Kubernetes rootfs':'Stage 2 CRI-O Kubernetes 시스템 파일 트리 검사',
    'Verify installed Stage 2 containerd Kubernetes rootfs':'Stage 2 containerd Kubernetes 시스템 파일 트리 검사',
    'Verify signed Stage 2 repository metadata':'Stage 2 저장소 메타데이터 서명 검사',
    'Write Go TUI Stage 2 containerd install plan':'Go 설치기 Stage 2 containerd 설치 계획 저장',
}

catalog = Path(__file__).with_name('ki2ci_catalog_ko.json')
if catalog.exists():
    TEXT.update(json.loads(catalog.read_text(encoding='utf-8')))
TEXT.update({'base':'기본 시스템','desktop':'데스크톱','kernel':'커널','kiki':'KIKI 전용',
             'system':'시스템','network':'네트워크','containers':'컨테이너','toolchain':'빌드 도구',
             'kubernetes':'Kubernetes','ai':'AI','development':'개발 도구'})
TEXT.update({'Present:':'설치됨:', 'Missing:':'누락됨:'})
TEXT.update({'Loading plan…':'실행 계획을 불러오는 중…'})
TEXT.update({'archive':'압축·보관 도구','build':'빌드 도구','library':'라이브러리',
             'runtime':'실행 환경','server':'서버','shell':'셸','storage':'저장 장치'})


def translate(value):
    if re.fullmatch(r'\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)',value):
        return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S (한국시간)')
    if value in TEXT:
        return TEXT[value]
    result = value
    result = re.sub(r'(\d[\d,]*) bytes',r'\1바이트',result)
    for a, b in TEXT.items():
        if a.endswith(': ') or a.startswith('. Select'):
            result = result.replace(a, b)
    result = re.sub(r'^(\S+) unit tests$', r'\1 단위 검사', result)
    result = re.sub(r'^Build (.+) and required dependencies$', r'\1 및 필수 의존 패키지 빌드', result)
    result = re.sub(r'^Build (.+) packages$', r'\1 패키지 빌드', result)
    result = re.sub(r'^Assemble (.+) rootfs$', r'\1 시스템 파일 트리 구성', result)
    result = re.sub(r'^Create (.+) bootable ISO$', r'\1 부팅 ISO 생성', result)
    result = re.sub(r'^Create (.+) installer ISO$', r'\1 설치 ISO 생성', result)
    result = re.sub(r'^Create (.+) ISO$', r'\1 ISO 생성', result)
    result = re.sub(r'^(.+) runtime plan$', r'\1 실행 의존성 구성', result)
    return result


class KoreanHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag == 'html':
            raw = raw.replace("lang='en'", "lang='ko'").replace('lang="en"', 'lang="ko"')
        for label in ['Follow output', 'Completed build steps']:
            raw = raw.replace(label, {'Follow output':'최신 출력 따라가기','Completed build steps':'완료된 빌드 단계'}[label])
        raw = re.sub(r'\b(aria-label|title|placeholder|alt)=([\'\"])(.*?)\2',
                     lambda m:m[1]+'='+m[2]+html.escape(translate(html.unescape(m[3])),quote=True)+m[2],raw)
        self.parts.append(raw)
        if tag in {'pre', 'code', 'script', 'style'}:
            self.skip.append(tag)

    def handle_endtag(self, tag):
        self.parts.append('</'+tag+'>')
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()

    def handle_data(self, data):
        if self.skip:
            self.parts.append(data)
        else:
            stripped = data.strip()
            self.parts.append(data.replace(stripped, translate(stripped), 1) if stripped else data)

    def handle_entityref(self, name): self.parts.append('&'+name+';')
    def handle_charref(self, name): self.parts.append('&#'+name+';')
    def handle_decl(self, decl): self.parts.append('<!'+decl+'>')
    def handle_comment(self, data): self.parts.append('<!--'+data+'-->')


def localize_html(text, route=None):
    p = KoreanHTML(); p.feed(text); p.close()
    text = ''.join(p.parts)
    if '/versions' not in text:
        text = text.replace('</nav>', "<a href='/versions'>소스·바이너리 버전</a><a href='/iso-build'>ISO 생성</a></nav>", 1)
    if '/cpu-profiles' not in text:
        text=text.replace('</nav>',"<a href='/cpu-profiles'>CPU 대상 관리</a></nav>",1)
    if "href='/releases'" not in text and 'href="/releases"' not in text:
        text=text.replace('</nav>',"<a href='/releases'>릴리즈 관리</a></nav>",1)
    if route in {'/', '/jobs'}:
        text = re.sub(r"<option value=['\"](?:iso|bootiso|installer-iso)['\"][^>]*>.*?</option>", '', text)
    if route in {'/', '/artifacts'}:
        notice = ("<section class='panel'><h2>후보 버전 보관소</h2>"
                  "<p id='release-overview'>보관 버전 현황을 불러오는 중…</p>"
                  "<p><a href='/versions'>후보 소스·바이너리 열기</a> · <a href='/iso-build'>후보 ISO 작업 열기</a></p>"
                  "<p class='muted'>아래 집계는 기존 빌드 경로 기준입니다. 보관한 후보 패키지·ISO는 위 링크에서 관리합니다.</p></section>")
        text = text.replace('</nav>', '</nav>'+notice, 1)
    if route == '/deploy':
        text = text.replace('</nav>', "</nav><section class='panel'><h2>현재 후보 서버 구성</h2>"
            "<p>인증 게이트웨이 127.0.0.1:8092 · 패키지 컴파일러 127.0.0.1:8091 · 버전·ISO 작업자 127.0.0.1:8094</p>"
            "<p>kiki-build-auth.service · kiki-candidate-buildd.service · kiki-release-worker.service</p>"
            "<p>후보 보관 경로: /build-kikios/kiki-build/candidates/mesa-native-20261023/release-store</p>"
            "<p>기존 /home/lab/kiki-os와 원래 8090 서비스는 보존합니다. 아래는 기존 배포 설정입니다.</p></section>", 1)
    return text


def localize_json(value):
    if isinstance(value, list):
        return [localize_json(x) for x in value]
    if isinstance(value, dict):
        result = {k: localize_json(v) for k,v in value.items()}
        if 'name' in value and ('command' in value or 'status' in value):
            result['display_name'] = translate(value['name'])
        if 'status' in value:
            result['status_label'] = translate(value['status'])
        return result
    return value
