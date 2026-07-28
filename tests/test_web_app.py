import unittest
from unittest import mock

from test_support import install_dependency_stubs


install_dependency_stubs()

from app import drive, main


class WebAppTests(unittest.TestCase):
    def test_safe_filename_rejects_dot_path_components(self):
        self.assertEqual(drive.safe_filename("."), "file")
        self.assertEqual(drive.safe_filename(".."), "file")
        self.assertEqual(drive.safe_filename("..."), "file")

    def test_progress_does_not_use_process_local_state(self):
        self.assertFalse(hasattr(main, "DOWNLOAD_PROGRESS"))
        paths = {route.path for route in main.app.routes}
        self.assertNotIn("/api/download/progress", paths)

    def test_file_mode_rejects_empty_file_selection(self):
        request = type("Request", (), {"session": {"token": {}}})()
        try:
            with mock.patch.object(
                main.Credentials,
                "from_authorized_user_info",
                return_value=object(),
                create=True,
            ), mock.patch.object(main, "build", return_value=object()):
                main.download(
                    request,
                    course_ids=["course-id"],
                    file_ids=None,
                    download_scope="files",
                )
        except main.HTTPException as exc:
            self.assertEqual(exc.status_code, 400)
        except Exception as exc:
            self.fail(f"empty file selection raised unexpected {exc!r}")
        else:
            self.fail("empty file selection was accepted")

    def test_course_listing_failure_aborts_download(self):
        request = type("Request", (), {"session": {"token": {}}})()
        classroom = object()
        drive_service = object()
        with mock.patch.object(
            main.Credentials,
            "from_authorized_user_info",
            return_value=object(),
            create=True,
        ), mock.patch.object(
            main, "build", side_effect=[classroom, drive_service]
        ), mock.patch.object(
            main,
            "list_course_files",
            side_effect=main.HTTPException(status_code=502, detail="failed"),
        ), mock.patch.object(main, "stream_zip", side_effect=lambda items: list(items)):
            with self.assertRaises(main.HTTPException):
                main.download(
                    request,
                    course_ids=["course-id"],
                    file_ids=None,
                    download_scope="courses",
                )


if __name__ == "__main__":
    unittest.main()
