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
from gcr_downloader.models import Course, CourseFile


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
            pdf = source.with_suffix(".pdf")
            source.write_bytes(b"source")
            pdf.write_bytes(b"existing")

            result = downloader.convert_to_pdf(source, "soffice", delete_original=True)

            self.assertTrue(result)
            self.assertTrue(source.exists())
            self.assertEqual(pdf.read_bytes(), b"existing")

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

    def test_deleted_converted_source_updates_download_index(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            source = base_dir / "Course" / "slides.pptx"
            source.parent.mkdir()
            source.write_bytes(b"slides")
            downloaded_ids = {"file-id": "Course/slides.pptx"}

            def convert(file_path, _command, delete_original=False):
                file_path.with_suffix(".pdf").write_bytes(b"pdf")
                if delete_original:
                    file_path.unlink()
                return True

            with mock.patch.object(downloader, "convert_to_pdf", side_effect=convert):
                downloader.convert_downloaded_files(
                    base_dir,
                    convert_ppt=True,
                    convert_docx=False,
                    delete_originals=True,
                    libreoffice_cmd="soffice",
                    downloaded_ids=downloaded_ids,
                )

            self.assertEqual(downloaded_ids["file-id"], "Course/slides.pdf")


if __name__ == "__main__":
    unittest.main()
