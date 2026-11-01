import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ki2assistant as ai


class AssistantTests(unittest.TestCase):
    def test_redacts_secrets_and_keeps_compiler_diagnostics(self):
        raw='password=secret123\nAuthorization: Bearer test-token\n-----BEGIN PRIVATE KEY-----\nprivate-bytes\n-----END PRIVATE KEY-----\nerror: missing libfoo.so'
        clean,count=ai.redact(raw)
        self.assertGreaterEqual(count,3)
        for secret in ['secret123','test-token','private-bytes']:self.assertNotIn(secret,clean)
        self.assertIn('missing libfoo.so',clean)

    def test_partial_key_and_complete_cookie_header_are_redacted(self):
        for raw,secret in [('truncated-key-material\n-----END PRIVATE KEY-----\nerror: missing library','truncated-key-material'),('Cookie: session=one; other=two\nerror: missing library','other=two'),('[DEBUG] Authorization: Bearer prefixed-secret\nerror: missing library','prefixed-secret'),('{"Authorization":"Bearer json-secret"}\nerror: missing library','json-secret'),('https://user:first@second@host/path\nerror: missing library','second')]:
            clean,count=ai.redact(raw);self.assertNotIn(secret,clean);self.assertIn('missing library',clean)

    def test_rejects_external_and_redirect_endpoints(self):
        for url in ['https://external.example/v1','http://127.0.0.1:8080/admin','http://user:pass@localhost:8080/v1','http://169.254.169.254/v1']:
            with self.subTest(url=url),self.assertRaises(ValueError):ai.Assistant.endpoint(url)

    def test_real_http_transport_never_applies_answer_or_leaks_secret(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));raw=json.dumps({'choices':[{'message':{'content':'확인할 라이브러리 경로를 제안합니다.'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        self.addCleanup(httpd.server_close);self.addCleanup(httpd.shutdown)
        with tempfile.TemporaryDirectory() as temp:
            assistant=ai.Assistant(Path(temp));assistant.configure(dict(endpoint=f'http://127.0.0.1:{httpd.server_port}/v1',model='test-model',enabled='yes'))
            result=assistant.complete('analyze','token=private-value\nerror: missing libfoo.so','job1')
            self.assertFalse(result['applied']);self.assertEqual(result['job_id'],'job1');self.assertNotIn('private-value',json.dumps(requests));self.assertEqual(len(list((Path(temp)/'reports').glob('*.json'))),1)


if __name__=='__main__':unittest.main()
