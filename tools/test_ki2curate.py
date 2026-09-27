import unittest

import ki2curate


class CurateTests(unittest.TestCase):
    def test_kernel_pin_beats_newer_unapproved_kernel(self):
        rows = [
            {"source": "main", "name": "linux", "version": "6.9.9", "release": "3", "file": "linux-6.9.9-3.x86_64.ki2", "arch": "x86_64"},
            {"source": "iso", "name": "linux", "version": "6.1.187", "release": "2", "file": "linux-6.1.187-2.x86_64.ki2", "arch": "x86_64"},
        ]
        selected, old = ki2curate.choose_latest(rows, {"linux": "6.1.187"})
        self.assertEqual(selected[0]["version"], "6.1.187")
        self.assertEqual(old, ["linux-6.9.9-3.x86_64.ki2"])

    def test_keeps_newest_release_and_archives_only_older_main_files(self):
        rows = [
            {"source": "main", "name": "demo", "version": "1.0", "release": "9", "file": "demo-1.0-9.x86_64.ki2", "arch": "x86_64"},
            {"source": "main", "name": "demo", "version": "1.0", "release": "10", "file": "demo-1.0-10.x86_64.ki2", "arch": "x86_64"},
            {"source": "iso", "name": "demo", "version": "1.0", "release": "10", "file": "demo-1.0-10.x86_64.ki2", "arch": "x86_64"},
            {"source": "addon", "name": "other", "version": "2.0", "release": "1", "file": "other-2.0-1.x86_64.ki2", "arch": "x86_64"},
        ]
        selected, old = ki2curate.choose_latest(rows)
        self.assertEqual([row["name"] for row in selected], ["demo", "other"])
        self.assertEqual(selected[0]["source"], "iso")
        self.assertEqual(old, ["demo-1.0-9.x86_64.ki2"])


if __name__ == "__main__":
    unittest.main()
