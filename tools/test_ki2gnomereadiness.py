import unittest

import ki2gnomereadiness


class GnomeReadinessTests(unittest.TestCase):
    def test_missing_core_blocks_install_menu(self):
        result = ki2gnomereadiness.check({"gnome-shell"}, {"gnome-shell"})
        self.assertFalse(result["minimum_core_available"])
        self.assertFalse(result["install_menu_enabled"])
        self.assertIn("gdm", result["missing_recipes"])
        self.assertIn("gdm", result["missing_packages"])

    def test_minimum_core_only_passes_first_gate(self):
        complete = set(ki2gnomereadiness.SESSION_CORE)
        result = ki2gnomereadiness.check(complete, complete)
        self.assertTrue(result["minimum_core_available"])
        self.assertFalse(result["install_menu_enabled"])
        self.assertIn("GDM and GNOME Wayland session boot in an isolated VM",
                      result["next_checks"])


if __name__ == "__main__":
    unittest.main()
