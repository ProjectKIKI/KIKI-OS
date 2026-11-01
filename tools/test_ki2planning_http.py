import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import ki2ci


class PlanningHTTPTests(unittest.TestCase):
    def test_metadata_route_pins_catalog_and_never_saves_it(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            server=ki2ci.BuildServer(ki2ci.CiConfig(root,Path(tmp),'x86_64',1,'test',Path(tmp)/'publish'))
            httpd=ThreadingHTTPServer(('127.0.0.1',0),ki2ci.make_handler(server))
            thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
            before=server.catalog.current()
            def answer(task,context):
                data=json.loads(context)
                self.assertEqual(data['package'],'base-files')
                self.assertEqual(data['revision'],before['revision'])
                return dict(id='a'*32,task=task,model='test',input_sha256='b'*64,
                            redactions=0,answer=json.dumps(dict(summary='설명',license='MIT',tier='base',evidence='기존 카탈로그')),
                            at='2026-11-01T00:00:00+00:00',applied=False)
            try:
                with patch.object(server.assistant,'complete',side_effect=answer):
                    req=urllib.request.Request(f'http://127.0.0.1:{httpd.server_port}/assistant/metadata',data=b'package=base-files')
                    with urllib.request.urlopen(req) as response:html=response.read().decode()
                    self.assertIn('검토한 메타정보 저장',html)
                self.assertEqual(server.catalog.current(),before)
                with urllib.request.urlopen(f'http://127.0.0.1:{httpd.server_port}/kernel-livepatch') as response:
                    self.assertIn('기반 커널 재빌드 필요',response.read().decode())
            finally:
                httpd.shutdown();httpd.server_close();server.close();thread.join()


if __name__=='__main__':unittest.main()
