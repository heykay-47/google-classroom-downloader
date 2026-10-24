import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from google.auth.exceptions import RefreshError, TransportError

from test_cli import downloader


class CliAuthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.token = pathlib.Path(directory.name) / "token.json"
        self.token.write_text("saved-token")
        self.saved = self.credentials()
        self.renewed = self.credentials()
        for patcher in (
            mock.patch.object(downloader, "TOKEN_FILE", str(self.token)),
            mock.patch.object(downloader, "Credentials", self.loader()),
            mock.patch.object(downloader, "InstalledAppFlow", self.flow_factory()),
            mock.patch.object(downloader.os.path, "exists", return_value=True),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def credentials(self, **overrides):
        creds = mock.Mock(valid=True, expired=False, refresh_token="refresh", scopes=downloader.SCOPES,
                          granted_scopes=None)
        creds.has_scopes.side_effect = lambda scopes: set(scopes).issubset(creds.scopes)
        creds.to_json.return_value = "renewed-token"
        for key, value in overrides.items():
            setattr(creds, key, value)
        return creds

    def loader(self):
        self.load = mock.Mock(return_value=self.saved)
        return mock.Mock(from_authorized_user_file=self.load)

    def flow_factory(self):
        self.authorize = mock.Mock(return_value=self.renewed)
        self.flow = mock.Mock(run_local_server=self.authorize)
        return mock.Mock(from_client_secrets_file=mock.Mock(return_value=self.flow))

    def test_reuses_valid_saved_grant_without_overriding_its_scopes(self):
        self.assertIs(downloader.get_credentials(), self.saved)
        self.load.assert_called_once_with(str(self.token))
        self.authorize.assert_not_called()
        self.saved.refresh.assert_not_called()
        self.assertEqual(self.token.read_text(), "saved-token")

    def test_refreshes_expired_grant_and_saves_it_without_browser(self):
        self.saved.valid = False
        self.saved.expired = True
        self.saved.refresh.side_effect = lambda _request: setattr(self.saved, "valid", True)
        self.assertIs(downloader.get_credentials(), self.saved)
        self.saved.refresh.assert_called_once()
        self.authorize.assert_not_called()
        self.assertEqual(self.token.read_text(), "renewed-token")

    def test_revoked_refresh_grant_reauthorizes_once_and_saves(self):
        self.saved.valid = False
        self.saved.expired = True
        self.saved.refresh.side_effect = RefreshError("secret", {"error": "invalid_grant"})
        self.assertIs(downloader.get_credentials(), self.renewed)
        self.authorize.assert_called_once()
        self.assertEqual(self.token.read_text(), "renewed-token")

    def test_saved_grant_missing_announcements_requires_browser_sign_in(self):
        self.saved.scopes = [scope for scope in downloader.SCOPES if "announcements" not in scope]
        self.assertIs(downloader.get_credentials(), self.renewed)
        self.authorize.assert_called_once()
        self.saved.refresh.assert_not_called()
        self.assertEqual(self.token.read_text(), "renewed-token")

    def test_partial_browser_grant_is_rejected_without_retry_or_overwrite(self):
        self.saved.scopes = []
        self.renewed.granted_scopes = downloader.SCOPES[:1]
        with self.assertRaisesRegex(ValueError, "required permissions.*run.*again"):
            downloader.get_credentials()
        self.authorize.assert_called_once()
        self.assertEqual(self.token.read_text(), "saved-token")

    def test_refresh_network_and_service_failures_keep_token_without_browser(self):
        self.saved.valid = False
        self.saved.expired = True
        for error in (
            TransportError("secret"),
            RefreshError("secret", {"error": "temporarily_unavailable"}, retryable=True),
            RefreshError("secret", {"error": "server_error"}),
            RefreshError("secret", {"error": "invalid_client"}),
            RefreshError("secret"),
        ):
            with self.subTest(error=error):
                self.saved.refresh.side_effect = error
                with self.assertRaisesRegex(ValueError, "refresh.*saved token unchanged") as caught:
                    downloader.get_credentials()
                self.assertNotIn("secret", str(caught.exception))
                self.authorize.assert_not_called()
                self.assertEqual(self.token.read_text(), "saved-token")

    def test_failed_or_cancelled_browser_sign_in_is_actionable_and_preserves_token(self):
        self.saved.scopes = []
        for error in (RuntimeError("secret"), TimeoutError("secret"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.authorize.reset_mock()
                self.authorize.side_effect = error
                with self.assertRaisesRegex(ValueError, "sign-in.*run.*again") as caught:
                    downloader.get_credentials()
                self.assertNotIn("secret", str(caught.exception))
                self.authorize.assert_called_once()
                self.assertEqual(self.token.read_text(), "saved-token")

    def test_refresh_with_reduced_grant_requires_verified_browser_authorization(self):
        self.saved.valid = False
        self.saved.expired = True

        def refresh(_request):
            self.saved.valid = True
            self.saved.granted_scopes = downloader.SCOPES[:1]

        self.saved.refresh.side_effect = refresh
        self.assertIs(downloader.get_credentials(), self.renewed)
        self.authorize.assert_called_once()

    def test_invalid_or_empty_browser_result_is_not_saved(self):
        self.saved.scopes = []
        for result in (None, self.credentials(valid=False), self.credentials(scopes=[])):
            with self.subTest(result=result):
                self.authorize.reset_mock()
                self.authorize.return_value = result
                with self.assertRaisesRegex(ValueError, "required permissions"):
                    downloader.get_credentials()
                self.authorize.assert_called_once()
                self.assertEqual(self.token.read_text(), "saved-token")

    def test_missing_refresh_token_uses_browser(self):
        self.saved.valid = False
        self.saved.expired = True
        self.saved.refresh_token = None
        self.assertIs(downloader.get_credentials(), self.renewed)
        self.saved.refresh.assert_not_called()
        self.authorize.assert_called_once()

    def test_cli_reports_failed_recovery_without_traceback_or_secrets(self):
        self.saved.valid = False
        self.saved.expired = True
        self.saved.refresh.side_effect = RefreshError("secret", {"error": "invalid_grant"})
        self.authorize.side_effect = RuntimeError("secret")
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["gcr"]), \
             mock.patch.object(downloader, "load_index", return_value={}), \
             mock.patch.object(downloader, "build") as build, \
             mock.patch("sys.stdout", output):
            self.assertEqual(downloader.main(), 1)
        self.assertIn("sign-in failed", output.getvalue())
        self.assertIn("run the command again", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.saved.refresh.assert_called_once()
        self.authorize.assert_called_once()
        build.assert_not_called()
        self.assertEqual(self.token.read_text(), "saved-token")
