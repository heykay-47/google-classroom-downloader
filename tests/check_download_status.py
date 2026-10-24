"""Real-framework HTTP checks, isolated from the legacy dependency stubs."""
import unittest
import asyncio
import base64
import json
from urllib.parse import urlencode
from unittest.mock import patch

from starlette.middleware.sessions import SessionMiddleware

from app import main
from gcr_downloader.models import DownloadReport


TOKEN = "a" * 32


class DownloadStatusHTTPTests(unittest.TestCase):
    def setUp(self):
        # A local-only signed session; no Google credentials or account involved.
        middleware = SessionMiddleware(main.app, secret_key=main.SESSION_SECRET)
        value = base64.b64encode(json.dumps({"token": {}}).encode())
        self.cookie = "classroom_session_v5=" + middleware.signer.sign(value).decode()

    def post(self, token=TOKEN, data=None):
        events = []
        body = urlencode(data or {"course_id": "c", "file_ids": "f"}).encode()

        async def receive():
            return {"type": "http.request", "body": body}

        async def send(event):
            events.append(event)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "method": "POST", "path": "/download", "raw_path": b"/download",
                 "query_string": f"download_token={token}".encode(), "scheme": "http",
                 "server": ("localhost", 80), "client": ("127.0.0.1", 1234),
                 "headers": [(b"host", b"localhost"), (b"content-type", b"application/x-www-form-urlencoded"),
                             (b"cookie", self.cookie.encode())]}
        asyncio.run(main.app(scope, receive, send))
        start = events[0]
        headers = [(k.decode(), v.decode()) for k, v in start["headers"]]
        return start["status"], headers, b"".join(e.get("body", b"") for e in events[1:]).decode(errors="replace")

    def test_ready_cookie_correlates_to_attachment_and_is_not_an_auth_cookie(self):
        with patch.object(main.Credentials, "from_authorized_user_info", return_value=object()), \
             patch.object(main, "build"), patch.object(main, "get_course"), \
             patch.object(main, "list_course_files"), \
             patch.object(main, "select_course_files", return_value=[]), \
             patch.object(main, "prepare_download", return_value=([], DownloadReport())):
            code, headers, _ = self.post()
        self.assertEqual(code, 200)
        self.assertIn("attachment", dict(headers)["content-disposition"])
        status = next(v for k, v in headers if k == "set-cookie" and v.startswith("download_status_"))
        self.assertIn(f"download_status_{TOKEN}=ready", status)
        self.assertIn("Max-Age=300", status)
        self.assertIn("SameSite=lax", status)
        self.assertNotIn("HttpOnly", status)
        self.assertNotIn("Secure", status)
        auth = next(v for k, v in headers if k == "set-cookie" and v.startswith("classroom_session"))
        self.assertIn("httponly", auth.lower())

    def test_expired_session_returns_correlated_actionable_error_not_login_redirect(self):
        self.cookie = ""
        code, headers, body = self.post()
        self.assertEqual(code, 401)
        self.assertIn(f'data-download-token="{TOKEN}"', body)
        self.assertIn("Sign in again", body)
        self.assertNotIn("location", dict(headers))
        self.assertNotIn("download_status_", str(headers))

    def test_invalid_selection_returns_correlated_error(self):
        code, _, body = self.post(data={"course_id": "c"})
        self.assertEqual(code, 400)
        self.assertIn("Select at least one file", body)
        self.assertIn(TOKEN, body)

    def test_preparation_exception_is_safe_and_actionable(self):
        with patch.object(main, "_download_response", side_effect=RuntimeError("SECRET <trace>")):
            code, _, body = self.post()
        self.assertEqual(code, 500)
        self.assertIn("Retry", body)
        self.assertIn(TOKEN, body)
        self.assertNotIn("SECRET", body)

    def test_catalog_error_preserves_status_and_escapes_markup(self):
        with patch.object(main, "_download_response", side_effect=main.HTTPException(502, "Unavailable <script>")):
            code, _, body = self.post()
        self.assertEqual(code, 502)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("sign in again", body)

    def test_malformed_token_is_rejected(self):
        code, _, _ = self.post(token="not-a-token")
        self.assertEqual(code, 400)

    def test_cloud_cookie_is_secure(self):
        from starlette.responses import Response
        with patch.object(main, "IS_LOCAL", False), \
             patch.object(main, "_download_response", return_value=Response()):
            _, headers, _ = self.post()
        cookie = next(v for k, v in headers if k == "set-cookie" and v.startswith("download_status_"))
        self.assertIn("Secure", cookie)
        self.assertNotIn("HttpOnly", cookie)


if __name__ == "__main__":
    unittest.main()
