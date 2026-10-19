# tests of scripts/engines/rules.py
#
#   python tests/test_rules.py

import tempfile
import unittest

import paths  # noqa: F401, scripts/ on sys.path
import storage
from engines import rules


class RulesTest(unittest.TestCase):
    def setUp(self):
        # the rules file in a temp dir, real data is not
        # touched
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_add_get_delete(self):
        self.assertEqual(rules.get_all(), [])
        self.assertEqual(rules.add("no gap ups"), 1)
        self.assertEqual(rules.add("cut losses"), 2)

        self.assertEqual(
            rules.get(2), {"Id": 2, "Rule": "cut losses"}
        )
        self.assertIsNone(rules.get(3))

        self.assertEqual(rules.delete(1), "no gap ups")
        self.assertIsNone(rules.delete(5))
        # renumbered
        self.assertEqual(
            rules.get_all(),
            [{"Id": 1, "Rule": "cut losses"}],
        )


if __name__ == "__main__":
    unittest.main()
