"""Opt-in real Chromium checks: GCR_BROWSER_TESTS=1 python -m unittest discover -s tests -p test_web_drawer_browser.py."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@unittest.skipUnless(os.environ.get("GCR_BROWSER_TESTS") == "1", "opt-in agent-browser verification")
class DrawerBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        if not shutil.which("agent-browser"):
            raise unittest.SkipTest("agent-browser not installed")
        cls.session = subprocess.check_output(
            ["agent-browser", "session", "id", "--scope", "worktree", "--prefix", "issue-7"], text=True,
        ).strip()
        env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape())
        html = env.get_template("courses.html").render(courses=[{
            "id": "course-1", "name": "Browser fixture", "state": "ACTIVE",
        }]).encode()
        files = [
            {"id": "a", "name": "Notes.pdf", "source_kind": "assignment", "post_id": "1",
             "post_title": "Week 1", "post_date": "2026-10-01T12:00:00Z", "file_type": "pdf"},
            {"id": "b", "name": "Slides.pptx", "source_kind": "assignment", "post_id": "1",
             "post_title": "Week 1", "file_type": "pptx"},
            {"id": "c", "name": "Reading.pdf", "source_kind": "material", "post_id": "1",
             "post_title": "Reading", "file_type": "pdf"},
            {"id": "d", "name": "<img src=x onerror=alert(1)>", "source_kind": "announcement",
             "post_id": "1", "post_title": None, "file_type": None},
        ]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                api = self.path.endswith("/files")
                self.send_response(200)
                self.send_header("Content-Type", "application/json" if api else "text/html")
                self.end_headers()
                self.wfile.write(json.dumps(files).encode() if api else html)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.browser("close")
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    @classmethod
    def browser(cls, *args, stdin=None):
        result = subprocess.run(
            ["agent-browser", "--session", cls.session, *args], input=stdin,
            text=True, capture_output=True, timeout=60,
        )
        if result.returncode:
            raise AssertionError(f"agent-browser {args}: {result.stderr or result.stdout}")
        return result.stdout

    def evaluate(self, script):
        return json.loads(self.browser("eval", "--stdin", stdin=script))

    def click(self, selector):
        self.browser("scrollintoview", selector)
        self.browser("click", selector)

    def test_filter_group_selection_submission_keyboard_and_mobile(self):
        self.browser("open", f"http://127.0.0.1:{self.server.server_port}")
        self.browser("click", "[data-manage-files]")
        self.browser("wait", "[data-post-group]")
        self.assertEqual(self.evaluate("document.querySelectorAll('[data-post-group]').length"), 3)
        self.assertIn("4 selected", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.browser("select", "#fileTypeFilter", "extension:pdf")
        self.assertIn("2 hidden", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.click("[data-post-group]:first-child [data-group-clear]")
        self.assertEqual(self.evaluate("Array.from(new FormData(document.querySelector('form[action=\"/download\"]')).getAll('file_ids'))"), ["b", "c", "d"])
        self.click("[data-post-group]:first-child [data-group-select]")
        self.assertIn("4 selected", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.browser("select", "#fileTypeFilter", "unknown")
        self.assertIn("Unknown type", self.evaluate("document.getElementById('fileList').innerText"))
        self.assertIn("Announcement", self.evaluate("document.getElementById('fileList').innerText"))
        self.assertIn("Date unavailable", self.evaluate("document.getElementById('fileList').innerText"))
        self.assertEqual(self.evaluate("document.querySelectorAll('#fileList img').length"), 0)
        self.click("#clearCourseFiles")
        self.assertIn("0 selected", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.browser("select", "#fileTypeFilter", "extension:pdf")
        self.click("[data-post-group]:first-child [data-group-select]")
        self.assertEqual(self.evaluate("Array.from(new FormData(document.querySelector('form[action=\"/download\"]')).getAll('file_ids'))"), ["a"])
        self.click("#selectCourseFiles")
        self.assertIn("4 selected", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.browser("press", "Escape")
        self.assertTrue(self.evaluate("document.activeElement.matches('[data-manage-files]')"))
        self.browser("press", "Enter")
        self.browser("wait", "#fileList input")
        self.assertEqual(self.evaluate("document.activeElement.id"), "closeDrawerButton")
        self.browser("focus", "input[name='file_ids'][value='a']")
        self.browser("press", "Space")
        self.assertIn("3 selected", self.evaluate("document.getElementById('selectionCount').textContent"))
        self.browser("press", "Space")
        self.browser("focus", "#closeDrawerButton")
        self.browser("press", "Shift+Tab")
        self.assertEqual(self.evaluate("document.activeElement.type"), "submit")
        self.browser("press", "Tab")
        self.assertEqual(self.evaluate("document.activeElement.id"), "closeDrawerButton")
        self.browser("set", "viewport", "360", "740")
        self.browser("select", "#fileTypeFilter", "extension:pdf")
        self.assertTrue(self.evaluate("document.getElementById('drawer').getBoundingClientRect().right <= innerWidth"))
        self.assertTrue(self.evaluate("document.getElementById('drawer').scrollWidth <= innerWidth"))
        evidence = Path("/tmp/opencode/gcr-issue-7-mobile.png")
        self.browser("scrollintoview", "[data-post-group]:first-child [data-group-select]")
        self.browser("screenshot", str(evidence))
        self.browser("set", "viewport", "1280", "900")
        self.browser("scrollintoview", "#selectCourseFiles")
        self.browser("screenshot", "/tmp/opencode/gcr-issue-7-desktop.png")
        Path("/tmp/opencode/gcr-issue-7-browser.txt").write_text(self.browser("snapshot"), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
