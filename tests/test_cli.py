import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_support import install_dependency_stubs


install_dependency_stubs()

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import classroom_downloader as downloader

from gcr_downloader.catalog import CatalogError
from gcr_downloader.models import (
    Course,
    CourseFile,
    DownloadOptions,
    DownloadReport,
    ItemResult,
)


class FakeFiles:
    def get_media(self, *, fileId):
        return fileId


class FakeDrive:
    def files(self):
        return FakeFiles()


class FailingDownloader:
    def __init__(self, file_handle, _request):
        self.file_handle = file_handle

    def next_chunk(self):
        self.file_handle.write(b"partial")
        raise RuntimeError("download failed")


class SuccessfulDownloader:
    def __init__(self, file_handle, _request):
        self.file_handle = file_handle

    def next_chunk(self):
        self.file_handle.write(b"complete")
        return None, True


class CliDownloaderTests(unittest.TestCase):
    def test_safe_filename_rejects_dot_path_components(self):
        self.assertEqual(downloader.safe_filename("."), "file")
        self.assertEqual(downloader.safe_filename(".."), "file")
        self.assertEqual(downloader.safe_filename("..."), "file")

    def test_missing_mime_type_is_not_a_video(self):
        try:
            result = downloader.is_video_file("notes.txt", None)
        except Exception as exc:
            self.fail(f"is_video_file raised {exc!r}")
        self.assertFalse(result)

    def test_course_state_defaults_to_all(self):
        with mock.patch.object(sys, "argv", ["classroom_downloader.py"]):
            args = downloader.parse_args()
        self.assertEqual(args.course_state, "all")

    def test_course_state_accepts_archived(self):
        with mock.patch.object(
            sys,
            "argv",
            ["classroom_downloader.py", "--course-state", "archived"],
        ):
            args = downloader.parse_args()
        self.assertEqual(args.course_state, "archived")

    def test_course_selection_accepts_shared_course_records(self):
        courses = [Course("1", "Active", "ACTIVE"), Course("2", "Archive", "ARCHIVED")]
        with mock.patch("builtins.input", side_effect=["2", "y"]):
            selected = downloader.select_courses(courses)
        self.assertEqual(selected, [courses[1]])

    def test_main_returns_nonzero_when_catalog_fails(self):
        args = types.SimpleNamespace(
            base_dir="downloads",
            course_name_contains=None,
            course_state="all",
            dry_run=False,
        )
        with mock.patch.object(downloader, "parse_args", return_value=args), \
             mock.patch.object(downloader, "get_credentials", return_value=object()), \
             mock.patch.object(downloader, "build", side_effect=[object(), object()]), \
             mock.patch.object(downloader, "load_index", return_value={}), \
             mock.patch.object(downloader, "list_courses", side_effect=CatalogError("Failed to fetch courses")):
            self.assertEqual(downloader.main(), 1)

    def test_failed_download_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "report.pdf"
            with mock.patch.object(
                downloader, "MediaIoBaseDownload", FailingDownloader
            ):
                result = downloader.download_drive_file(
                    FakeDrive(),
                    "file-id",
                    destination,
                    "application/pdf",
                    max_retries=1,
                )

            self.assertFalse(result)
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_successful_download_atomically_replaces_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "report.pdf"
            with mock.patch.object(
                downloader, "MediaIoBaseDownload", SuccessfulDownloader
            ):
                result = downloader.download_drive_file(
                    FakeDrive(),
                    "file-id",
                    destination,
                    "application/pdf",
                    max_retries=1,
                )

            self.assertTrue(result)
            self.assertEqual(destination.read_bytes(), b"complete")
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_existing_pdf_does_not_delete_original_document(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "report.docx"
            existing_pdf = source.with_suffix(".pdf")
            source.write_bytes(b"source")
            existing_pdf.write_bytes(b"existing")

            result_path, message = downloader.convert_to_pdf(source, "soffice")

            self.assertIsNone(result_path)
            self.assertIn("already exists", message)
            self.assertTrue(source.exists())
            self.assertEqual(existing_pdf.read_bytes(), b"existing")

    def test_empty_pdf_is_conversion_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "report.docx"
            source.write_bytes(b"source")

            def create_empty_pdf(*_args, **_kwargs):
                source.with_suffix(".pdf").write_bytes(b"")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(downloader.subprocess, "run", side_effect=create_empty_pdf):
                pdf, message = downloader.convert_to_pdf(source, "soffice")

            self.assertIsNone(pdf)
            self.assertIn("non-empty PDF", message)
            self.assertTrue(source.exists())

    def test_report_renderer_shows_status_counts(self):
        report = DownloadReport([
            ItemResult("Course", "notes.pdf", "downloaded", ("Course/notes.pdf",)),
            ItemResult("Course", "video.mp4", "skipped_video", message="Video excluded"),
        ])
        with mock.patch("builtins.print") as output:
            downloader.render_report(report)
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn("downloaded: 1", rendered)
        self.assertIn("skipped_video: 1", rendered)

    def test_replace_conversion_updates_index_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            downloaded_ids = {}
            report = DownloadReport()

            class MetadataRequest:
                def execute(self):
                    return {"name": "slides.pptx", "mimeType": "application/vnd.ms-powerpoint"}

            class MetadataFiles:
                def get(self, **_kwargs):
                    return MetadataRequest()

            class MetadataDrive:
                def files(self):
                    return MetadataFiles()

            def download(_drive, _file_id, destination, _mime_type, **_kwargs):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"slides")
                return True

            def convert(source, _command):
                pdf = source.with_suffix(".pdf")
                pdf.write_bytes(b"%PDF-converted")
                return pdf, ""

            with mock.patch.object(
                downloader,
                "list_course_files",
                return_value=[CourseFile("file-id", "slides.pptx")],
            ), mock.patch.object(
                downloader,
                "download_drive_file",
                side_effect=download,
            ), mock.patch.object(
                downloader,
                "convert_to_pdf",
                side_effect=convert,
            ):
                downloader.download_all_for_course(
                    object(),
                    MetadataDrive(),
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(convert_powerpoint=True, keep_originals=False),
                    report,
                    libreoffice_cmd="soffice",
                )

            self.assertFalse((base_dir / "Course" / "slides.pptx").exists())
            self.assertEqual(downloaded_ids["file-id"], "Course/slides.pdf")
            self.assertEqual(report.items[0].status, "converted")
            self.assertEqual(report.items[0].output_paths, ("Course/slides.pdf",))

    def test_metadata_request_retries_transient_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            request = mock.Mock()
            request.execute.side_effect = [RuntimeError("transient"), {
                "name": "report.pdf",
                "mimeType": "application/pdf",
            }]
            files = mock.Mock()
            files.get.return_value = request
            drive = mock.Mock()
            drive.files.return_value = files
            report = DownloadReport()

            with mock.patch.object(
                downloader, "list_course_files", return_value=[CourseFile("file-id", "report.pdf")]
            ), mock.patch.object(downloader.time, "sleep") as sleep:
                downloader.download_all_for_course(
                    object(), drive, Course("course-id", "Course", "ACTIVE"),
                    pathlib.Path(directory), {}, DownloadOptions(), report, dry_run=True,
                )

            self.assertEqual(request.execute.call_count, 2)
            sleep.assert_called_once_with(1)
            self.assertEqual(report.items[0].status, "dry_run")

    def test_metadata_request_stops_after_three_failures(self):
        request = mock.Mock()
        request.execute.side_effect = RuntimeError("transient")
        files = mock.Mock()
        files.get.return_value = request
        drive = mock.Mock()
        drive.files.return_value = files
        report = DownloadReport()

        with mock.patch.object(
            downloader, "list_course_files", return_value=[CourseFile("file-id", "report.pdf")]
        ), mock.patch.object(downloader.time, "sleep") as sleep:
            downloader.download_all_for_course(
                object(), drive, Course("course-id", "Course", "ACTIVE"),
                pathlib.Path("downloads"), {}, DownloadOptions(), report,
            )

        self.assertEqual(request.execute.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(report.items[0].status, "download_failed")

    def test_missing_duplicate_uses_recorded_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            (course_dir / "report.pdf").write_bytes(b"first file")
            downloaded_ids = {"second-id": "Course/report_1.pdf"}

            class MetadataRequest:
                def execute(self):
                    return {"name": "report.pdf", "mimeType": "application/pdf"}

            class MetadataFiles:
                def get(self, **kwargs):
                    return MetadataRequest()

            class MetadataDrive:
                def files(self):
                    return MetadataFiles()

            with mock.patch.object(
                downloader, "list_course_files", return_value=[CourseFile("second-id", "report.pdf")]
            ), mock.patch.object(
                downloader, "download_drive_file", return_value=True
            ) as download:
                downloader.download_all_for_course(
                    object(),
                    MetadataDrive(),
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(),
                    DownloadReport(),
                )

            download.assert_called_once()
            self.assertEqual(download.call_args.args[2], course_dir / "report_1.pdf")
            self.assertEqual(downloaded_ids["second-id"], "Course/report_1.pdf")

    def test_legacy_pathless_duplicate_is_redownloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            (course_dir / "report.pdf").write_bytes(b"first file")
            downloaded_ids = {"second-id": ""}

            class MetadataRequest:
                def execute(self):
                    return {"name": "report.pdf", "mimeType": "application/pdf"}

            class MetadataFiles:
                def get(self, **kwargs):
                    return MetadataRequest()

            class MetadataDrive:
                def files(self):
                    return MetadataFiles()

            with mock.patch.object(
                downloader, "list_course_files", return_value=[CourseFile("second-id", "report.pdf")]
            ), mock.patch.object(
                downloader, "download_drive_file", return_value=True
            ) as download:
                downloader.download_all_for_course(
                    object(),
                    MetadataDrive(),
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(),
                    DownloadReport(),
                )

            download.assert_called_once()
            self.assertEqual(download.call_args.args[2], course_dir / "report_1.pdf")
            self.assertEqual(downloaded_ids["second-id"], "Course/report_1.pdf")

    def test_legacy_index_is_loaded_without_losing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = pathlib.Path(directory) / "download_index.json"
            index_path.write_text(
                json.dumps({"downloaded_ids": ["first-id", "second-id"]}),
                encoding="utf-8",
            )

            with mock.patch.object(downloader, "INDEX_FILE", str(index_path)):
                result = downloader.load_index()

            self.assertEqual(result, {"first-id": "", "second-id": ""})

    def test_indexed_path_must_stay_inside_download_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory) / "downloads"
            base_dir.mkdir()

            result = downloader.get_indexed_path(base_dir, "../outside.pdf")

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
