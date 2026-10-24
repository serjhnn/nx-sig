# tests of scripts/engines/demo.py and the demo
# settings (demo/config.json, demo/seed/)
#
#   python tests/test_demo.py

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
from engines import alerts, basetrades, demo, ladder
from engines import rules, trades


class DemoTest(unittest.TestCase):
    def setUp(self):
        # the demo data in a temp dir
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        p = mock.patch.object(config, "DEMO", True)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_prepare_once(self):
        self.assertTrue(demo.prepare())
        names = set(os.listdir(self._tmp.name))
        seed = set(os.listdir(config.DEMO_SEED_DIR))
        self.assertTrue(seed <= names)
        self.assertIn("demo_prices.json", names)
        self.assertIn("demo_bars.json", names)
        # a change stays: the next start copies nothing
        rules.add("my rule")
        self.assertFalse(demo.prepare())
        self.assertEqual(
            rules.get_all()[-1]["Rule"], "my rule"
        )

    def test_reset(self):
        demo.prepare()
        rules.add("my rule")
        extra = os.path.join(self._tmp.name, "x.json")
        open(extra, "w").close()
        demo.reset()
        self.assertFalse(os.path.exists(extra))
        self.assertNotIn(
            "my rule",
            [r["Rule"] for r in rules.get_all()],
        )

    def test_seed_reads(self):
        # every sample file reads through the engines
        demo.prepare()
        for stock in storage.Stock:
            trades.get_all(stock)
        self.assertTrue(basetrades.get_all())
        self.assertTrue(rules.get_all())
        self.assertTrue(ladder.get_all())
        self.assertTrue(alerts.alerts_get_all())

    def test_not_outside_demo(self):
        config.DEMO = False
        with self.assertRaises(RuntimeError):
            demo.prepare()
        with self.assertRaises(RuntimeError):
            demo.reset()
        self.assertEqual(os.listdir(self._tmp.name), [])


class DemoConfigTest(unittest.TestCase):
    def test_file(self):
        path = os.path.join(config.DEMO_DIR, "config.json")
        with open(path) as f:
            data = json.load(f)
        with open(
            os.path.join(config.ROOT_DIR, "config.json")
        ) as f:
            real = json.load(f)
        self.assertNotEqual(
            data["storage_dir"], real["storage_dir"]
        )
        self.assertEqual(data["indices"], real["indices"])

    def test_env(self):
        # NX_DEMO=1 switches config.py to the demo
        code = (
            "import config; print(config.demo(), "
            "config.storage_dir())"
        )
        scripts = os.path.join(config.ROOT_DIR, "scripts")
        for value, demo_on, folder in (
            ("1", "True", "demo_data"),
            ("", "False", "data"),
        ):
            env = {**os.environ, "NX_DEMO": value}
            out = subprocess.run(
                [sys.executable, "-c", code],
                cwd=scripts,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            self.assertEqual(out[0], demo_on)
            self.assertEqual(
                out[1],
                os.path.join(config.ROOT_DIR, folder),
            )


if __name__ == "__main__":
    unittest.main()
