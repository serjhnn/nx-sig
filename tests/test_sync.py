# tests of scripts/sync.py
#
#   python tests/test_sync.py

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from sync import (
    IGNORE,
    SyncError,
    _split_id,
    check_device_id,
    stignore_text,
)

ID = (
    "ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23-"
    "4567ABC-DEFGHIJ-KLMNOPQ-RSTUVWX"
)


class SyncTests(unittest.TestCase):
    def test_device_id(self):
        self.assertEqual(check_device_id(ID), ID)
        # pasted lower case, with spaces or a newline
        low = ID.lower()
        messy = " " + low[:20] + "\n" + low[20:]
        self.assertEqual(check_device_id(messy), ID)
        for bad in ("", "ABC", ID[:-1], ID + "-A"):
            with self.assertRaises(SyncError):
                check_device_id(bad)
        # 0, 1, 8, 9 aren't base32
        with self.assertRaises(SyncError):
            check_device_id(ID.replace("2", "0"))

    def test_stignore_new(self):
        text = stignore_text("")
        self.assertEqual(text.splitlines(), IGNORE)

    def test_stignore_keeps_own(self):
        old = "my.csv\n.lock"
        text = stignore_text(old)
        lines = text.splitlines()
        self.assertEqual(lines[:2], ["my.csv", ".lock"])
        self.assertEqual(lines.count(".lock"), 1)
        self.assertTrue(set(IGNORE) <= set(lines))
        # nothing more to add the second time
        self.assertEqual(stignore_text(text), text)

    def test_split_id(self):
        lines = _split_id(ID)
        joined = lines[0] + "-" + lines[1]
        self.assertEqual(joined.replace(" ", ""), ID)
        for line in lines:
            self.assertLessEqual(len(line), 48)


if __name__ == "__main__":
    unittest.main()
