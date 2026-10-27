import json
import os
import stat
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import ki2disk


class GPTTests(unittest.TestCase):
    def test_unused_disk_guard_rejects_active_uses(self):
        # Model sysfs/procfs in a temporary tree; never create a block device.
        for use in ('unused', 'partition', 'disk-holder', 'partition-holder',
                    'disk-mount', 'partition-mount', 'block-swap', 'file-swap'):
            with self.subTest(use=use), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                disk = base / 'sysdisk'
                part = disk / 'sda1'
                part.mkdir(parents=True)
                (disk / 'dev').write_text('8:0\n')
                (part / 'dev').write_text('8:1\n')
                (part / 'partition').write_text('1\n')
                (disk / 'holders').mkdir()
                (part / 'holders').mkdir()
                mounts = base / 'mountinfo'
                mounts.write_text('')
                swaps = base / 'swaps'
                swaps.write_text('Filename Type Size Used Priority\n')
                if use == 'partition':
                    (disk / 'partition').write_text('1\n')
                if use in ('disk-holder', 'partition-holder'):
                    owner = disk if use == 'disk-holder' else part
                    (owner / 'holders/dm-0').touch()
                if use in ('disk-mount', 'partition-mount'):
                    identity = '8:0' if use == 'disk-mount' else '8:1'
                    mounts.write_text(f'22 1 {identity} / /target rw - ext4 /dev/test rw\n')
                swap = mock.Mock()
                swap.stat.return_value = SimpleNamespace(
                    st_mode=stat.S_IFBLK if use == 'block-swap' else stat.S_IFREG,
                    st_rdev=os.makedev(8,1), st_dev=os.makedev(8,1))
                if use in ('block-swap', 'file-swap'):
                    swaps.write_text('Filename Type Size Used Priority\n/test-swap file 1024 0 -2\n')
                target = mock.Mock()
                target.stat.return_value = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8,0))
                locations = {'/sys/dev/block/8:0': disk, '/proc/self/mountinfo': mounts,
                             '/proc/swaps': swaps, '/test-swap': swap}
                with mock.patch.object(ki2disk, 'Path', side_effect=lambda p: locations[str(p)]):
                    if use == 'unused':
                        self.assertEqual(ki2disk.require_unused_disk(target),os.makedev(8,0))
                    else:
                        with self.assertRaises(ValueError):
                            ki2disk.require_unused_disk(target)

    def test_unused_disk_guard_fails_closed_when_sysfs_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = mock.Mock()
            target.stat.return_value = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8,0))
            with mock.patch.object(ki2disk, 'Path', return_value=Path(tmp)/'missing'), \
                 self.assertRaises(FileNotFoundError):
                ki2disk.require_unused_disk(target)

    def test_sector_geometry_and_swap_policy(self):
        for sector in (512, 4096):
            for swap in (0, 1024):
                with self.subTest(sector=sector, swap=swap):
                    text = ki2disk.partition_script(8 * 1024**3, sector, 768, swap)
                    self.assertIn("label: gpt", text)
                    self.assertIn(f"start={1024**2 // sector},", text)
                    self.assertEqual("KIKI_SWAP" in text, swap != 0)
                    self.assertEqual(text.count("type="), 3 if swap else 2)
        for args in ((8*1024**3, 513, 768, 0), (2*1024**3, 512, 512, 0),
                     (8*1024**3, 512, 0, 0), (8*1024**3, 512, 768, -1)):
            with self.assertRaises(ValueError):
                ki2disk.partition_script(*args)

    def test_writer_refuses_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-a-device"
            path.write_bytes(b"untouched")
            with self.assertRaises(ValueError):
                ki2disk.require_unused_disk(path)
            self.assertEqual(path.read_bytes(), b"untouched")

    @unittest.skipUnless(shutil.which("sfdisk"), "sfdisk required")
    def test_gpt_on_sparse_images_including_over_2tib(self):
        for size in (8 * 1024**3, 3 * 1024**4):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as tmp:
                disk = Path(tmp) / "test-only.img"
                with disk.open("wb") as stream:
                    stream.truncate(size)
                script = ki2disk.partition_script(size, 512, 768, 1024)
                subprocess.run(["sfdisk", str(disk)], input=script, text=True,
                               capture_output=True, check=True, timeout=30)
                subprocess.run(["sfdisk", "--verify", str(disk)],
                               capture_output=True, check=True, timeout=30)
                table = json.loads(subprocess.check_output(["sfdisk", "--json", str(disk)]))["partitiontable"]
                self.assertEqual(table["label"], "gpt")
                parts = table["partitions"]
                self.assertEqual([p["name"] for p in parts], ["KIKI_EFI", "KIKI_SWAP", "KIKI_ROOT"])
                self.assertEqual(parts[0]["type"].upper(), ki2disk.ESP)
                self.assertLess(parts[-1]["start"] + parts[-1]["size"], size // 512 - 33)
                with disk.open("rb") as stream:
                    stream.seek(512)
                    self.assertEqual(stream.read(8), b"EFI PART")
                    stream.seek(size - 512)
                    self.assertEqual(stream.read(8), b"EFI PART")


if __name__ == "__main__":
    unittest.main()
