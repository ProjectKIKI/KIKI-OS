from html.parser import HTMLParser
import unittest

import ki2ci_theme as theme


class Forms(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.forms=[]; self.fields=[]; self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag=='form':self.forms.append(dict(attrs))
        if tag=='input':self.fields.append(dict(attrs))


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.session={'name':'admin','csrf':'synthetic-csrf','role':'admin','must_change':0}

    def test_worker_controls_and_verbatim_logs_survive_shell_replacement(self):
        log='&lt;nav&gt;中文 &amp; 한글\n  $ echo &quot;ok&quot;'
        source=("<!doctype html><html><head><title>작업</title><meta http-equiv='refresh' content='5'><script src='/build-console.js' defer></script><style>.panel{color:red}</style></head>"
                "<body><header><h1>빌드 작업 상세</h1></header><nav><a href='/old'>old menu</a></nav><section id='outside'>보관소</section><main><section class='panel' data-job-id='123'>"
                "<form method='post' action='/jobs/123/retry'><input name='_csrf' value='synthetic-csrf' type='hidden'><input name='next' value='/jobs/123'><button>재시도</button></form>"
                "<pre id='live-log'>"+log+"</pre><progress id='job-progress' max='100' value='42'></progress></section></main></body></html>")
        result=theme.decorate(source,self.session,'/jobs/123')
        self.assertIn("<pre id='live-log'>"+log+"</pre>",result)
        self.assertIn("data-job-id='123'",result)
        self.assertIn("<progress id='job-progress' max='100' value='42'>",result)
        self.assertIn("<section id='outside'>보관소</section>",result)
        self.assertIn("<meta http-equiv='refresh' content='5'>",result)
        self.assertIn("<script src='/build-console.js' defer>",result)
        self.assertNotIn('old menu',result)
        parsed=Forms(result)
        self.assertIn({'method':'post','action':'/jobs/123/retry'},parsed.forms)
        self.assertIn({'name':'next','value':'/jobs/123'},parsed.fields)
        self.assertEqual(sum(f['name']=='_csrf' for f in parsed.fields),2)
        self.assertEqual(result.count('<main '),1)
        self.assertEqual(result.count('<h1>'),1)

    def test_navigation_permissions_and_untrusted_identity_are_escaped(self):
        for role in ['viewer','operator','admin']:
            session=dict(self.session,role=role,name='<script>alert(1)</script>')
            rendered=theme.document(session,'/library/files/source/abc','<unsafe>','<p>본문</p>')
            self.assertNotIn('<script>alert(1)</script>',rendered)
            self.assertIn('&lt;unsafe&gt;',rendered)
            self.assertIn('href="/versions" aria-current="page"',rendered)
            self.assertEqual('href="/users"' in rendered,role=='admin')
        self.assertNotIn('href="/users"',theme.document(dict(self.session,must_change=1),'/account','내 계정',''))

    def test_release_promotion_preserves_actions_fields_and_notice(self):
        content="<html><head><title>릴리즈 관리 · KIKI OS</title></head><body><header><h1>릴리즈 관리</h1></header><nav></nav><main><section class='panel'><h2>릴리즈별 패키지·ISO</h2><p>원본 설명</p><p><a href='/releases/new'>새 릴리즈 등록</a> · <a href='/iso-build'>전체 ISO 이력</a></p><form method='get' action='/releases'><input name='q' value='needle'></form><table><tr><td>후보</td></tr></table><p class='notice'>실제 설치 검증 필요</p></section></main></body></html>"
        rendered=theme.decorate(content,self.session,'/releases')
        self.assertEqual(rendered.count('원본 설명'),1)
        self.assertEqual(rendered.count('>새 릴리즈 등록</a>'),1)
        self.assertEqual(rendered.count('>전체 ISO 이력</a>'),1)
        self.assertIn('실제 설치 검증 필요',rendered)
        self.assertIn({'name':'q','value':'needle'},Forms(rendered).fields)

    def test_login_keeps_form_and_serves_no_external_dependencies(self):
        body=theme.public_page('로그인',"<form method='post' action='/login'><input name='_csrf' value='test'><button>로그인</button></form>").decode()
        self.assertIn({'method':'post','action':'/login'},Forms(body).forms)
        self.assertIn('TERMINAL LAB',body)
        self.assertNotIn('https://',body)
        self.assertNotIn('/users',body)


if __name__=='__main__':unittest.main()
