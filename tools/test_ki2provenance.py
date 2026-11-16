import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2bootiso
import ki2provenance as origin


class ProvenanceTests(unittest.TestCase):
    def fixture(self, base):
        root = base / 'source';root.mkdir()
        (root / 'input.txt').write_text('candidate source\n')
        files = {'input.txt': origin.sha(root / 'input.txt')}
        archive = base / 'source.tar'
        with tarfile.open(archive, 'w') as tf:
            tf.add(root / 'input.txt', arcname='input.txt')
        data = dict(schema='kiki-build-inputs-v1', source_commit='b' * 40, source_state='modified-candidate',
                    source_archive=archive.name, source_archive_sha256=origin.sha(archive), files=files,
                    source_tree_sha256=hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        receipt = base / 'build-inputs.json';receipt.write_text(json.dumps(data))
        return root, receipt, data

    def test_archive_and_working_tree_are_both_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, receipt, data = self.fixture(Path(tmp))
            info = ki2bootiso.iso_build_info(root, receipt)
            self.assertEqual(info['commit'], 'b' * 40)
            self.assertTrue(info['dirty'])
            self.assertEqual(info['commit_role'], 'base-with-input-lock')
            self.assertEqual(info['input_manifest_sha256'], origin.sha(receipt))
            (root / 'input.txt').write_text('unrecorded edit')
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, 'source file SHA'):
                ki2bootiso.iso_build_info(root, receipt)
            (root / 'input.txt').write_text('candidate source\n')
            (receipt.parent / 'source.tar').write_bytes(b'tampered')
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, 'archive SHA'):
                ki2bootiso.iso_build_info(root, receipt)

    def test_actual_channel_receipt_and_descriptor_must_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);root, receipt, data = self.fixture(base)
            build = origin.load_build_inputs(root, receipt)
            media = base / 'media';repo = media / 'kiki/repo';repo.mkdir(parents=True)
            (repo / 'index.x86_64.json').write_text('{}')
            metadata = dict(channel='v13-metadata-test', index=dict(sha256=origin.sha(repo / 'index.x86_64.json')))
            (repo / 'metadata.x86_64.json').write_text(json.dumps(metadata))
            shutil.copyfile(receipt, media / 'kiki/build-inputs.json')
            descriptor = base / 'origin.json';descriptor.write_text(json.dumps(origin.media_origin(build, repo)))
            values = origin.verified_origin_values(media, descriptor)
            self.assertEqual(values['channel'], 'v13-metadata-test')
            self.assertEqual(values['source_commit'], data['source_commit'])
            self.assertIn('input_manifest_sha256=' + origin.sha(receipt), origin.origin_text(media, descriptor))
            saved = descriptor.read_bytes()
            for key in ['channel', 'metadata_sha256', 'repository_index_sha256', 'input_manifest_sha256', 'source_commit']:
                broken = json.loads(saved);broken[key] = 'wrong'
                descriptor.write_text(json.dumps(broken))
                with self.assertRaises(ValueError):origin.verified_origin_values(media, descriptor)
            descriptor.write_bytes(saved)
            (media / 'kiki/build-inputs.json').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):origin.verified_origin_values(media, descriptor)

    def test_unsafe_or_omitted_source_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, receipt, data = self.fixture(Path(tmp))
            data['source_archive'] = '../source.tar';receipt.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'archive must'):origin.load_build_inputs(root, receipt)
            data['source_archive'] = 'source.tar';receipt.write_text(json.dumps(data))
            (root / 'extra.txt').write_text('unexpected')
            with self.assertRaisesRegex(ValueError, 'inventory changed'):origin.load_build_inputs(root, receipt)

    def test_real_stage1_serializer_records_all_entry_paths(self):
        if sys.platform != 'linux' or not shutil.which('gcc'):
            self.skipTest('Linux GCC required for actual Stage-1 serializer')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);source = root / 'probe.c';binary = root / 'probe'
            harness = r'''
int main(int argc, char **argv) {
 if (argc != 3) return 9;
 struct install_plan p = {0}; struct account_setup a = {0}; struct network_setup n = {0};
 build_install_plan(&p, 0, kstrcmp(argv[1], "unattended") == 0, 1, 0,
                    "/media", "/media/kiki/repo/index.x86_64.json", "/dev/vda", "/dev/vda1", "", "/dev/vda2", "fixture", 32768, 2048, 768, 0, 32000, &a, &n);
 if (kstrcmp(argv[1], "gtk") == 0 || kstrcmp(argv[1], "tui") == 0) copy_string(p.frontend, sizeof(p.frontend), argv[1]);
 copy_string(p.channel, sizeof(p.channel), "v13-real-candidate");
 copy_string(p.source_commit, sizeof(p.source_commit), "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
 copy_string(p.input_manifest_sha256, sizeof(p.input_manifest_sha256), "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
 return write_install_plan_yaml(argv[2], &p) ? 0 : 8;
}
'''
            source.write_text('#define KIKI_ENABLE_INSTALLER 1\n#define _start kiki_embedded_start\n' + ki2bootiso.INIT_C + '\n' + harness)
            subprocess.run(['gcc', '-O1', '-fno-builtin', str(source), '-o', str(binary)], check=True, capture_output=True)
            for frontend in ['gtk', 'tui', 'cli', 'unattended']:
                output = root / (frontend + '.yaml')
                subprocess.run([str(binary), frontend, str(output)], check=True)
                plan = output.read_text()
                self.assertIn('generated_by: "kiki-stage1"', plan)
                self.assertIn('frontend: "' + frontend + '"', plan)
                self.assertIn('channel: "v13-real-candidate"', plan)
                self.assertIn('source_commit: "' + 'b' * 40 + '"', plan)
                self.assertIn('input_manifest_sha256: "' + 'a' * 64 + '"', plan)
                self.assertIn('planner: "' + ('kiki-installer-tui' if frontend in ['gtk', 'tui'] else 'kiki-stage1') + '"', plan)
                self.assertNotIn('stage2-v2', plan)

    def test_real_origin_loader_rejects_duplicate_or_truncated_fields(self):
        if sys.platform != 'linux' or not shutil.which('gcc'):
            self.skipTest('Linux GCC required for Stage-1 origin loader')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);receipt = root / 'verified-origin';source = root / 'probe.c';binary = root / 'probe'
            body = ki2bootiso.INIT_C.replace('/run/kiki/verified-origin', str(receipt))
            source.write_text('#define KIKI_ENABLE_INSTALLER 1\n#define _start kiki_embedded_start\n' + body + '\nint main(void) { struct install_plan p = {0}; return load_verified_plan_origin(&p) ? 0 : 7; }\n')
            subprocess.run(['gcc', '-O1', '-fno-builtin', str(source), '-o', str(binary)], check=True, capture_output=True)
            fields = dict(channel='candidate-channel', source_commit='b' * 40, source_state='modified-candidate',
                          source_archive_sha256='a' * 64, source_tree_sha256='c' * 64,
                          input_manifest_sha256='d' * 64, repository_index_sha256='e' * 64)
            valid = ''.join(k + '=' + v + '\n' for k, v in fields.items())
            receipt.write_text(valid)
            self.assertEqual(subprocess.run([str(binary)]).returncode, 0)
            for invalid in [valid + 'channel=duplicate\n', valid.replace('candidate-channel', 'c' * 96), valid.replace('source_commit=' + 'b' * 40 + '\n', '')]:
                receipt.write_text(invalid)
                self.assertEqual(subprocess.run([str(binary)]).returncode, 7)


if __name__ == '__main__':
    unittest.main()
