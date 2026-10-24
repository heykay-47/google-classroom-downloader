"""Run transport/browser-controller tests without polluting legacy dependency stubs."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class DownloadStatusTests(unittest.TestCase):
    def test_real_framework_download_transport(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, "tests/check_download_status.py"], cwd=root,
                       env={**os.environ, "PYTHONPATH": str(root)}, check=True)

    def test_browser_controller_behaviors(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run(["node", "tests/check_download_status.js"], cwd=root, check=True)
