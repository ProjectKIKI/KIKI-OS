import importlib.machinery
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest

import ki2pixelcandidate as pixel


class PixelBoundaryTests(unittest.TestCase):
    def test_dconf_database_name_is_valid_in_writer_dbus_path(self):
        repo=Path(__file__).resolve().parents[1]
        profile=repo/'distro/sources/kiki-session-gnome-ops/usr/share/kiki-paper-pixel/dconf-profile'
        databases=[line.partition(':')[2] for line in profile.read_text().splitlines() if line.startswith('user-db:')]
        self.assertEqual(len(databases),1)
        self.assertRegex(databases[0],re.compile(r'^[A-Za-z0-9_]+$'))

    def test_original_file_preservation_rejects_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); original=root/'original'; original.write_bytes(b'original')
            pixel.save(root/'preservation-before.json',{str(original):pixel.ki2repo.file_sha256(original)})
            original.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Original files changed'):
                pixel.preserve(type('Args',(),{'output':root})(),root)

    def test_thin_overlay_rejects_wrong_ga_index_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); ga=root/'ga.json';ga.write_text('{}'); pin=root/'pin.json'
            pin.write_text(json.dumps({'snapshot':{'index_sha256':'0'*64}}))
            args=type('Args',(),dict(ga_index=ga,ga_input=pin,candidate=root/'candidate',
                sign_key=root/'key',overlay=root/'new-overlay'))()
            with self.assertRaisesRegex(ValueError,'GA index SHA mismatch'):pixel.overlay(args,root)
            self.assertFalse(args.overlay.exists())

    def test_incident_link_rejects_credential_query_and_non_https_urls(self):
        source=Path(__file__).resolve().parents[1]/'distro/sources/kiki-session-gnome-ops/usr/libexec/kiki-ops-link'
        loader=importlib.machinery.SourceFileLoader('pixel_link',str(source))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        link=importlib.util.module_from_spec(spec);loader.exec_module(link)
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'link.json'
            for url in ['file:///etc/passwd','http://example.com','https://name:password@example.com',
                        'https://example.com/?token=secret','https://example.com/#token','https://example.com/\n']:
                config.write_text(json.dumps({'url':url}))
                with self.assertRaises(ValueError,msg=url):link.configured_url(config)
            config.write_text(json.dumps({'url':'https://incident-ai.lab.terminal-lab.kr/'}))
            self.assertEqual(link.configured_url(config),'https://incident-ai.lab.terminal-lab.kr/')


if __name__=='__main__':unittest.main()
