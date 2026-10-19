# paths: puts scripts/ and scripts/mtsig/ on sys.path,
# so a test imports the modules as the scripts do
#
# every tests/test_*.py imports it first; python puts
# the folder of the test on sys.path, so it is found
# both by python tests/test_x.py and by
# python -m unittest discover tests

import os
import sys

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
SCRIPTS = os.path.join(ROOT_DIR, "scripts")

for folder in (os.path.join(SCRIPTS, "mtsig"), SCRIPTS):
    if folder not in sys.path:
        sys.path.insert(0, folder)
