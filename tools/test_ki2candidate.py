import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import ki2candidate


class CandidateTests(unittest.TestCase):
    def test_verified_snapshot_and_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)
            source=repo/'dist/ki2/packages/x86_64'
            source.mkdir(parents=True)
            (source/'sample.ki2').write_bytes(b'package fixture')
            baseline=repo/'index.json'
            baseline.write_text(json.dumps({'arch':'x86_64','packages':[{'name':'sample'}]}))
            destination=repo/'candidate'
            with mock.patch.object(ki2candidate.ki2build,'load_recipes',return_value={'sample':{}}), \
                 mock.patch.object(ki2candidate.ki2build,'load_profile',return_value={'packages':['sample']}), \
                 mock.patch.object(ki2candidate.ki2build,'dependency_closure',return_value=['sample']), \
                 mock.patch.object(ki2candidate.ki2build,'package_filename',return_value='sample.ki2'):
                ki2candidate.snapshot(repo,baseline,destination,repo/'profile')
                record=json.loads((destination/'snapshot.json').read_text())['packages'][0]
                self.assertEqual(record['sha256'],hashlib.sha256(b'package fixture').hexdigest())
                self.assertEqual(record['size'],len(b'package fixture'))
                copied=destination/'packages/x86_64/sample.ki2'
                self.assertEqual(copied.read_bytes(),b'package fixture')
                (source/'sample.ki2').write_bytes(b'changed source')
                with self.assertRaises(FileExistsError):
                    ki2candidate.snapshot(repo,baseline,destination,repo/'profile')
                self.assertEqual(copied.read_bytes(),b'package fixture')
                with self.assertRaises(FileNotFoundError):
                    (source/'sample.ki2').unlink()
                    ki2candidate.snapshot(repo,baseline,repo/'missing-candidate',repo/'profile')
                self.assertFalse((repo/'missing-candidate').exists())


if __name__=='__main__':
    unittest.main()
