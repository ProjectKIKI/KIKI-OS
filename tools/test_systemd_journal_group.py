"""Guard the opt-in journal group against accidental service exposure."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SystemdJournalGroupTests(unittest.TestCase):
    def test_journal_group_is_opt_in_and_matches_candidate(self):
        catalog = json.loads((ROOT / "distro/sources/ki2ctl/usr/share/ki2/package-groups.json").read_text(encoding="utf-8"))
        groups = {group["id"]: group for group in catalog["groups"]}
        group = groups["systemd-journal-extensions"]
        self.assertEqual(group["requires"], ["minimal"])
        self.assertEqual(group["services"]["enable"], [])
        self.assertEqual(group["packages"]["default"], [])
        self.assertEqual(group["packages"]["optional"], [])
        wanted = set(group["packages"]["mandatory"])
        self.assertEqual(wanted, {"systemd-journal-gatewayd", "systemd-journal-transport"})

        index = json.loads((ROOT / "dist/ki2/systemd-journal-candidate-01/repo/index.x86_64.json").read_text(encoding="utf-8"))
        available = {package["name"] for package in index["packages"]}
        self.assertTrue(wanted <= available)
        self.assertIn("libmicrohttpd", available)


if __name__ == "__main__":
    unittest.main()
