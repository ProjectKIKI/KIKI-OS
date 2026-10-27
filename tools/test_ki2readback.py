import gzip
import hashlib
import io
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest

import ki2bootiso
import ki2readback


class ReadbackTests(unittest.TestCase):
    def test_tui_reference_requires_regular_non_symlink_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tui'
            with self.assertRaises(ki2readback.ReadbackError):
                ki2readback.tui_reference(path)
            path.write_bytes(b'TUI fixture')
            expected = {'usr/bin/kiki-installer-tui':hashlib.sha256(b'TUI fixture').hexdigest()}
            self.assertEqual(ki2readback.tui_reference(path),expected)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(ki2readback.ReadbackError):
                ki2readback.tui_reference(link)

    def archive(self, duplicate=False, trailer=True):
        data = bytearray()
        for i in range(2 if duplicate else 1):
            ki2bootiso._add_newc_entry(data, i+1, "a", b"hello", stat.S_IFREG | 0o644, 0, 1)
        if trailer:
            ki2bootiso._add_newc_entry(data, 3, "TRAILER!!!", b"", 0, 0, 1)
        return bytes(data)

    def expected(self):
        return {"a": hashlib.sha256(b"hello").hexdigest()}

    def test_newc_valid_and_corrupt(self):
        self.assertEqual(ki2readback.verify_newc(io.BytesIO(self.archive()), self.expected()), 1)
        for data in (self.archive(duplicate=True), self.archive(trailer=False),
                     self.archive()[:-1], self.archive()+b"unexpected", b"garbage",
                     self.archive().replace(b"hello", b"other")):
            with self.subTest(data=data[:20]):
                with self.assertRaises(ValueError):
                    ki2readback.verify_newc(io.BytesIO(data), self.expected())
        with self.assertRaisesRegex(ValueError, "missing"):
            ki2readback.verify_newc(io.BytesIO(self.archive()), {"absent":"x"})

    def test_gzip_crc_is_checked(self):
        data = bytearray(gzip.compress(self.archive()))
        data[-8] ^= 1
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            with self.assertRaises((OSError, EOFError)):
                ki2readback.verify_newc(stream, self.expected())

    def test_tar_selected_file_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "root.tar.gz"
            for duplicate in (False, True):
                with tarfile.open(path, "w:gz") as archive:
                    for _ in range(2 if duplicate else 1):
                        member = tarfile.TarInfo("a")
                        member.size = 5
                        archive.addfile(member, io.BytesIO(b"hello"))
                if duplicate:
                    with self.assertRaisesRegex(ValueError, "duplicate"):
                        ki2readback.verify_tar(path, self.expected())
                else:
                    self.assertEqual(ki2readback.verify_tar(path, self.expected()), 1)
                    with self.assertRaisesRegex(ValueError, "mismatch"):
                        ki2readback.verify_tar(path, {"a":"invalid"})
                    with self.assertRaisesRegex(ValueError, "missing"):
                        ki2readback.verify_tar(path, {"absent":"x"})


if __name__ == "__main__":
    unittest.main()
