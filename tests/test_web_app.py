import io
import unittest
from unittest import mock

from test_support import install_dependency_stubs


install_dependency_stubs()

from app import drive, downloads, main, zipstreamer
from app.drive import DriveMetadata
from app.gotenberg import GotenbergError
from app.zipstreamer import ArchiveEntry
from gcr_downloader.catalog import CatalogError
from gcr_downloader.models import (
    Course,
    CourseFile,
    DownloadOptions,
    DownloadReport,
    ItemResult,
)


class WebAppTests(unittest.TestCase):
    def test_file_api_preserves_ids_names_and_exposes_catalog_metadata_without_drive(self):
        request = type("Request", (), {"session": {"token": {}}})()
        files = [CourseFile("a", "Notes.pdf", "assignment", "post-1", "Week 1", None, "pdf")]
        with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
             mock.patch.object(main, "build", return_value=object()) as build, \
             mock.patch.object(main, "list_course_files", return_value=files):
            result = main.get_course_files(request, "course-1")
        self.assertEqual(result, [{
            "id": "a", "name": "Notes.pdf", "source_kind": "assignment", "post_id": "post-1",
            "post_title": "Week 1", "post_date": None, "file_type": "pdf",
            "file_type_source": "extension",
        }])
        self.assertEqual(build.call_count, 1)
        self.assertEqual(build.call_args.args[:2], ("classroom", "v1"))

    def test_safe_filename_rejects_dot_path_components(self):
        self.assertEqual(drive.safe_filename("."), "file")
        self.assertEqual(drive.safe_filename(".."), "file")
        self.assertEqual(drive.safe_filename("..."), "file")

    def test_progress_does_not_use_process_local_state(self):
        self.assertFalse(hasattr(main, "DOWNLOAD_PROGRESS"))
        paths = {route.path for route in main.app.routes}
        self.assertNotIn("/api/download/progress", paths)

    def test_download_rejects_empty_file_selection(self):
        request = type("Request", (), {"session": {"token": {}}})()
        with self.assertRaises(main.HTTPException) as error:
            main.download(request, course_id="course-1", file_ids=None)
        self.assertEqual(error.exception.status_code, 400)

    def test_download_rejects_file_not_attached_to_course(self):
        request = type("Request", (), {"session": {"token": {}}})()
        course = Course("course-1", "Course", "ACTIVE")
        available = [CourseFile("allowed", "Allowed")]
        with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
             mock.patch.object(main, "build", side_effect=[object(), object()]), \
             mock.patch.object(main, "get_course", return_value=course), \
             mock.patch.object(main, "list_course_files", return_value=available):
            with self.assertRaises(main.HTTPException) as error:
                main.download(request, course_id="course-1", file_ids=["forged"])
        self.assertEqual(error.exception.status_code, 400)

    def test_course_catalog_failure_returns_502_before_preparation(self):
        request = type("Request", (), {"session": {"token": {}}})()
        with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
             mock.patch.object(main, "build", side_effect=[object(), object()]), \
             mock.patch.object(main, "get_course", side_effect=CatalogError("Failed to fetch course")), \
             mock.patch.object(main, "prepare_download") as prepare:
            with self.assertRaises(main.HTTPException) as error:
                main.download(request, course_id="course-1", file_ids=["file-1"])
        self.assertEqual(error.exception.status_code, 502)
        prepare.assert_not_called()

    def test_download_builds_non_destructive_options(self):
        request = type("Request", (), {"session": {"token": {}}})()
        course = Course("course-1", "Course", "ACTIVE")
        selected = [CourseFile("file-1", "Notes")]
        response = object()
        with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
             mock.patch.object(main, "build", side_effect=[object(), object()]), \
             mock.patch.object(main, "get_course", return_value=course), \
             mock.patch.object(main, "list_course_files", return_value=selected), \
             mock.patch.object(main, "select_course_files", return_value=selected), \
             mock.patch.object(main, "prepare_download", return_value=([], DownloadReport())) as prepare, \
             mock.patch.object(main, "stream_zip", return_value=response):
            result = main.download(
                request,
                course_id="course-1",
                file_ids=["file-1"],
                convert_word=True,
                replace_originals=False,
            )
        self.assertIs(result, response)
        self.assertEqual(
            prepare.call_args.args[3],
            DownloadOptions(convert_word=True, keep_originals=True),
        )

    def test_conversion_failure_keeps_original_and_reports_failure(self):
        source = io.BytesIO(b"original")
        with mock.patch.object(
            downloads,
            "get_metadata",
            return_value=DriveMetadata("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ), mock.patch.object(
            downloads,
            "download_to_spool",
            return_value=source,
        ), mock.patch.object(
            downloads,
            "convert_to_pdf",
            side_effect=GotenbergError("Conversion service unavailable"),
        ):
            entries, report = downloads.prepare_download(
                object(),
                Course("course-1", "Course", "ACTIVE"),
                [CourseFile("file-1", "Notes")],
                DownloadOptions(convert_word=True, keep_originals=False),
            )
        self.assertEqual([entry.path for entry in entries], ["Course/notes.docx"])
        self.assertEqual(report.items[0].status, "conversion_failed")
        self.assertEqual(report.items[0].output_paths, ("Course/notes.docx",))

    def test_replace_success_emits_only_pdf(self):
        source = io.BytesIO(b"slides")
        pdf = io.BytesIO(b"%PDF-converted")
        with mock.patch.object(
            downloads,
            "get_metadata",
            return_value=DriveMetadata("slides.pptx", "application/vnd.ms-powerpoint"),
        ), mock.patch.object(downloads, "download_to_spool", return_value=source), \
             mock.patch.object(downloads, "convert_to_pdf", return_value=pdf):
            entries, report = downloads.prepare_download(
                object(),
                Course("course-1", "Course", "ACTIVE"),
                [CourseFile("file-1", "Slides")],
                DownloadOptions(convert_powerpoint=True, keep_originals=False),
            )
        self.assertEqual([entry.path for entry in entries], ["Course/slides.pdf"])
        self.assertTrue(source.closed)
        self.assertEqual(report.items[0].status, "converted")

    def test_stream_zip_appends_report_and_closes_streams(self):
        class FakeZip:
            instance = None

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.entries = []
                FakeZip.instance = self

            def write_iter(self, path, iterable):
                self.entries.append((path, iterable))

            def __iter__(self):
                for _path, iterable in self.entries:
                    yield from iterable

        source = io.BytesIO(b"notes")
        report = DownloadReport([ItemResult("Course", "notes.txt", "downloaded", ("Course/notes.txt",))])
        with mock.patch.object(zipstreamer.zipstream, "ZipFile", FakeZip):
            response = zipstreamer.stream_zip([ArchiveEntry("Course/notes.txt", source)], report)
            list(response.body_iterator)
        self.assertEqual(FakeZip.instance.entries[-1][0], "_download_report.json")
        self.assertTrue(FakeZip.instance.kwargs["allowZip64"])
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
