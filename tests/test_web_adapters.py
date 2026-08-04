import io
import unittest
from unittest import mock

import requests

from app import drive, gotenberg


class WebAdapterTests(unittest.TestCase):
    def test_drive_failure_closes_partial_spool(self):
        spool = io.BytesIO()

        class FailingDownloader:
            def __init__(self, file_handle, _request):
                self.file_handle = file_handle

            def next_chunk(self):
                self.file_handle.write(b"partial")
                raise RuntimeError("failed")

        files = mock.Mock()
        files.get_media.return_value = object()
        service = mock.Mock()
        service.files.return_value = files
        with mock.patch.object(drive.tempfile, "SpooledTemporaryFile", return_value=spool), \
             mock.patch.object(drive, "MediaIoBaseDownload", FailingDownloader):
            with self.assertRaises(drive.DriveDownloadError):
                drive.download_to_spool(service, "file-id", "application/pdf", max_attempts=1)
        self.assertTrue(spool.closed)

    def test_gotenberg_posts_expected_multipart_and_accepts_pdf(self):
        response = mock.Mock(status_code=200, headers={"Content-Type": "application/pdf"})
        response.iter_content.return_value = [b"%PDF-", b"converted"]
        session = mock.Mock()
        session.post.return_value = response

        result = gotenberg.convert_to_pdf(
            io.BytesIO(b"document"),
            "notes.docx",
            session=session,
            max_attempts=1,
        )

        self.assertEqual(result.read(), b"%PDF-converted")
        call = session.post.call_args
        self.assertTrue(call.args[0].endswith("/forms/libreoffice/convert"))
        self.assertEqual(call.kwargs["timeout"], (5, 130))
        self.assertEqual(call.kwargs["files"][0][0], "files")

    def test_gotenberg_400_is_not_retried(self):
        response = mock.Mock(status_code=400, text="unsafe details")
        session = mock.Mock()
        session.post.return_value = response
        with self.assertRaisesRegex(gotenberg.GotenbergError, "Conversion request rejected"):
            gotenberg.convert_to_pdf(io.BytesIO(b"bad"), "bad.docx", session=session)
        self.assertEqual(session.post.call_count, 1)

    def test_gotenberg_503_retries_three_times(self):
        response = mock.Mock(status_code=503, text="overloaded")
        session = mock.Mock()
        session.post.return_value = response
        with mock.patch.object(gotenberg.time, "sleep") as sleep:
            with self.assertRaises(gotenberg.GotenbergError):
                gotenberg.convert_to_pdf(io.BytesIO(b"doc"), "notes.docx", session=session)
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_gotenberg_stream_failure_closes_partial_spool(self):
        spool = io.BytesIO()
        response = mock.Mock(status_code=200, headers={"Content-Type": "application/pdf"})
        response.iter_content.side_effect = requests.RequestException("stream failed")
        session = mock.Mock()
        session.post.return_value = response

        with mock.patch.object(gotenberg.tempfile, "SpooledTemporaryFile", return_value=spool):
            with self.assertRaises(gotenberg.GotenbergError):
                gotenberg.convert_to_pdf(
                    io.BytesIO(b"document"), "notes.docx", session=session, max_attempts=1
                )

        self.assertTrue(spool.closed)

    def test_gotenberg_io_failure_closes_partial_spool(self):
        spool = io.BytesIO()
        response = mock.Mock(status_code=200, headers={"Content-Type": "application/pdf"})
        response.iter_content.side_effect = OSError("read failed")
        session = mock.Mock()
        session.post.return_value = response

        with mock.patch.object(gotenberg.tempfile, "SpooledTemporaryFile", return_value=spool):
            with self.assertRaises(OSError):
                gotenberg.convert_to_pdf(
                    io.BytesIO(b"document"), "notes.docx", session=session, max_attempts=1
                )

        self.assertTrue(spool.closed)


if __name__ == "__main__":
    unittest.main()
