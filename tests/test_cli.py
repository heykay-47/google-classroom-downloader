import io
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
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.index_path = pathlib.Path(directory.name) / "download_index.json"
        patcher = mock.patch.object(downloader, "INDEX_FILE", str(self.index_path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, drive, files, directory, answers=None, extra_args=()):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["gcr", "--base-dir", directory, *extra_args]), \
             mock.patch.object(downloader, "get_credentials", return_value=object()), \
             mock.patch.object(downloader, "build", side_effect=[object(), drive]), \
             mock.patch.object(downloader, "list_courses", return_value=[Course("course-id", "Course", "ACTIVE")]), \
             mock.patch.object(downloader, "list_course_files", return_value=files), \
             mock.patch.object(downloader, "MediaIoBaseDownload", SuccessfulDownloader), \
             mock.patch("builtins.input", side_effect=answers or ["all", "n", "n", "y"]), \
             mock.patch("sys.stdout", output):
            code = downloader.main()
        return code, output.getvalue()

    def test_progress_shows_selected_course_positions_and_empty_counts(self):
        courses = [Course("empty", "Empty", "ACTIVE"), Course("full", "Full", "ACTIVE")]
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "name": "notes.pdf", "mimeType": "application/pdf",
            }
            with mock.patch.object(downloader, "list_courses", return_value=courses), \
                 mock.patch.object(downloader, "list_course_files", side_effect=[[], [CourseFile("id", "notes.pdf")]]) as catalog:
                output = io.StringIO()
                with mock.patch.object(sys, "argv", ["gcr", "--base-dir", directory]), \
                     mock.patch.object(downloader, "get_credentials", return_value=object()), \
                     mock.patch.object(downloader, "build", side_effect=[object(), drive]), \
                     mock.patch.object(downloader, "MediaIoBaseDownload", SuccessfulDownloader), \
                     mock.patch("builtins.input", side_effect=["all", "n", "n", "y"]), \
                     mock.patch("sys.stdout", output):
                    self.assertEqual(downloader.main(), 0)
            self.assertEqual([call.args[1] for call in catalog.call_args_list], ["empty", "full"])
            text = output.getvalue()
            self.assertIn("Course [1/2] Empty: 0 discovered files", text)
            self.assertIn("No files to process.", text)
            self.assertIn("Course [2/2] Full: 1 discovered files", text)
            self.assertIn("[1/1] Downloaded: notes.pdf", text)
            self.assertIn("Download summary:", text)

    def test_progress_reports_each_mixed_outcome_with_reason(self):
        names = ["notes.pdf", "slides.pptx", "broken.pptx", "video.mp4", "existing.pdf", "failed.pdf", "unknown.pdf"]
        files = [CourseFile(name, name) for name in names]
        drive = mock.Mock()

        def metadata(*, fileId, **_kwargs):
            if fileId == "unknown.pdf":
                raise RuntimeError("metadata unavailable")
            request = mock.Mock()
            request.execute.return_value = {"name": fileId, "mimeType": "application/octet-stream"}
            return request

        def download(_drive, file_id, destination, _mime_type):
            if file_id == "failed.pdf":
                return False
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"source")
            return True

        def convert(source, _command):
            if source.name == "broken.pptx":
                return None, "LibreOffice conversion failed"
            pdf = source.with_suffix(".pdf")
            pdf.write_bytes(b"%PDF")
            return pdf, ""

        drive.files.return_value.get.side_effect = metadata
        with tempfile.TemporaryDirectory() as directory:
            course_dir = pathlib.Path(directory) / "Course"
            course_dir.mkdir()
            (course_dir / "existing.pdf").write_bytes(b"existing")
            downloader.save_index({"existing.pdf": "Course/existing.pdf"})
            with mock.patch.object(downloader, "check_libreoffice_available", return_value=(True, "soffice")), \
                 mock.patch.object(downloader, "download_drive_file", side_effect=download), \
                 mock.patch.object(downloader, "convert_to_pdf", side_effect=convert), \
                 mock.patch.object(downloader.time, "sleep"):
                code, output = self.run_cli(drive, files, directory, answers=["all", "y", "n", "n", "n"])
        self.assertEqual(code, 0)
        for position, (outcome, name) in enumerate(zip([
            "Downloaded", "Converted", "Conversion failed", "Skipped video",
            "Skipped existing", "Download failed", "Download failed",
        ], names), 1):
            self.assertIn(f"[{position}/7] {outcome}: {name}", output)
        self.assertIn("[3/7] Conversion failed: broken.pptx - LibreOffice conversion failed", output)
        self.assertIn("[7/7] Download failed: unknown.pdf - Failed to fetch file metadata", output)
        self.assertNotIn("[6/7] Downloaded", output)
        self.assertEqual(downloader.load_index(), {
            "existing.pdf": "Course/existing.pdf", "notes.pdf": "Course/notes.pdf",
            "slides.pptx": "Course/slides.pptx", "broken.pptx": "Course/broken.pptx",
        })

    def test_progress_labels_dry_run_as_planned_not_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "name": "slides.pptx", "mimeType": "application/vnd.ms-powerpoint",
            }
            with mock.patch.object(downloader, "check_libreoffice_available", return_value=(True, "soffice")), \
                 mock.patch.object(downloader, "convert_to_pdf") as convert:
                code, output = self.run_cli(
                    drive, [CourseFile("id", "slides.pptx")], directory,
                    answers=["all", "y", "n", "y", "y"], extra_args=["--dry-run"],
                )
            self.assertEqual(code, 0)
            self.assertIn("Course [1/1] Course: 1 discovered files", output)
            self.assertIn("[1/1] Dry run (planned, not downloaded): slides.pptx", output)
            self.assertNotIn("[1/1] Downloaded:", output)
            self.assertNotIn("[1/1] Converted:", output)
            self.assertIn("dry_run: 1", output)
            convert.assert_not_called()
            self.assertFalse(self.index_path.exists())
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])

    def test_interrupted_conversion_retains_completed_source_in_index(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "name": "slides.pptx", "mimeType": "application/vnd.ms-powerpoint",
            }
            with mock.patch.object(downloader, "check_libreoffice_available", return_value=(True, "soffice")), \
                 mock.patch.object(downloader, "convert_to_pdf", side_effect=KeyboardInterrupt):
                code, output = self.run_cli(
                    drive, [CourseFile("file-id", "slides.pptx")], directory,
                    answers=["all", "y", "n", "y", "y"],
                )
            self.assertEqual(code, 130)
            self.assertIn("Download summary", output)
            self.assertIn("[1/1] Processing: slides.pptx", output)
            self.assertNotIn("[1/1] Converted:", output)
            self.assertEqual(downloader.load_index(), {"file-id": "Course/slides.pptx"})
            self.assertTrue((pathlib.Path(directory) / "Course/slides.pptx").is_file())

    def test_checkpoint_failure_stops_before_downloading_the_next_file(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "name": "first.pdf", "mimeType": "application/pdf",
            }
            with mock.patch.object(pathlib.Path, "replace", side_effect=PermissionError("locked")):
                # Use an already indexed file so the injected replace failure targets the index.
                course_dir = pathlib.Path(directory) / "Course"
                course_dir.mkdir()
                (course_dir / "first.pdf").write_bytes(b"complete")
                self.index_path.write_text(json.dumps({"downloaded_ids": {"first-id": "Course/first.pdf"}}))
                previous = self.index_path.read_bytes()
                code, output = self.run_cli(drive, [CourseFile("first-id", "first.pdf"), CourseFile("second-id", "second.pdf")], directory)
            self.assertEqual(code, 1)
            self.assertIn("locked", output)
            self.assertIn("skipped_existing: 1", output)
            self.assertEqual(drive.files.return_value.get.call_count, 1)
        self.assertEqual(self.index_path.read_bytes(), previous)
        self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])

    def test_failed_index_flush_preserves_previous_index(self):
        downloader.save_index({"old-id": "Course/old.pdf"})
        previous = self.index_path.read_bytes()
        for error in (OSError("disk full"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(downloader.os, "fsync", side_effect=error):
                    with self.assertRaises(type(error)):
                        downloader.save_index({"new-id": "Course/new.pdf"})
                self.assertEqual(self.index_path.read_bytes(), previous)
                self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])

    def test_conversion_failure_checkpoints_the_original_and_keeps_it_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.return_value = {
                "name": "slides.pptx", "mimeType": "application/vnd.ms-powerpoint",
            }
            with mock.patch.object(downloader, "check_libreoffice_available", return_value=(True, "soffice")), \
                 mock.patch.object(downloader, "convert_to_pdf", return_value=(None, "conversion failed")):
                code, output = self.run_cli(drive, [CourseFile("file-id", "slides.pptx")], directory, answers=["all", "y", "n", "y", "y"])
            self.assertEqual(code, 0)
            self.assertIn("conversion_failed: 1", output)
            self.assertEqual(downloader.load_index(), {"file-id": "Course/slides.pptx"})
            self.assertTrue((pathlib.Path(directory) / "Course/slides.pptx").is_file())

    def test_failed_index_replace_preserves_previous_index_and_cleans_temp(self):
        downloader.save_index({"old-id": "Course/old.pdf"})
        previous = self.index_path.read_bytes()
        with mock.patch.object(pathlib.Path, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                downloader.save_index({"new-id": "Course/new.pdf"})
        self.assertEqual(self.index_path.read_bytes(), previous)
        self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])

    def test_completed_file_is_checkpointed_before_the_next_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            drive = mock.Mock()
            checkpoints = []

            def metadata(*, fileId, **_kwargs):
                if fileId == "second-id":
                    checkpoints.append(downloader.load_index())
                    raise KeyboardInterrupt
                request = mock.Mock()
                request.execute.return_value = {"name": "first.pdf", "mimeType": "application/pdf"}
                return request

            drive.files.return_value.get.side_effect = metadata
            files = [CourseFile("first-id", "first.pdf"), CourseFile("second-id", "second.pdf")]
            report = DownloadReport()
            with mock.patch.object(downloader, "list_course_files", return_value=files), \
                 mock.patch.object(downloader, "MediaIoBaseDownload", SuccessfulDownloader):
                with self.assertRaises(KeyboardInterrupt):
                    downloader.download_all_for_course(
                        object(), drive, Course("course-id", "Course", "ACTIVE"),
                        base_dir, {}, DownloadOptions(), report,
                    )
            self.assertEqual(len(report.items), 1)
            self.assertEqual(checkpoints, [{"first-id": "Course/first.pdf"}])
            self.assertEqual((base_dir / "Course/first.pdf").read_bytes(), b"complete")
            self.assertEqual(downloader.load_index(), {"first-id": "Course/first.pdf"})

    def test_ctrl_c_preserves_completed_files_and_prints_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            request = drive.files.return_value.get.return_value
            request.execute.side_effect = [
                {"name": "first.pdf", "mimeType": "application/pdf"}, KeyboardInterrupt,
            ]
            files = [CourseFile("first-id", "first.pdf"), CourseFile("second-id", "second.pdf")]
            code, output = self.run_cli(drive, files, directory)
            self.assertEqual(code, 130)
            self.assertEqual(downloader.load_index(), {"first-id": "Course/first.pdf"})
            self.assertIn("interrupted", output.lower())
            self.assertIn("downloaded: 1", output)
            self.assertIn("[1/2] Downloaded: first.pdf", output)
            self.assertIn("[2/2] Processing: second.pdf", output)
            self.assertNotIn("[2/2] Downloaded:", output)

    def test_ctrl_c_before_the_first_download_does_not_mark_a_file_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.side_effect = KeyboardInterrupt
            code, output = self.run_cli(drive, [CourseFile("file-id", "notes.pdf")], directory)
            self.assertEqual(code, 130)
            self.assertEqual(downloader.load_index(), {})
            self.assertNotIn("downloaded:", output)
            self.assertIn("[1/1] Processing: notes.pdf", output)
            self.assertNotIn("[1/1] Downloaded:", output)

    def test_ctrl_c_dry_run_does_not_write_the_index(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.side_effect = [
                {"name": "first.pdf", "mimeType": "application/pdf"}, KeyboardInterrupt,
            ]
            code, output = self.run_cli(
                drive, [CourseFile("first-id", "first.pdf"), CourseFile("second-id", "second.pdf")],
                directory, extra_args=["--dry-run"],
            )
            self.assertEqual(code, 130)
            self.assertIn("dry_run: 1", output)
            self.assertIn("[1/2] Dry run (planned, not downloaded): first.pdf", output)
            self.assertIn("[2/2] Processing: second.pdf", output)
            self.assertNotIn("[2/2] Dry run", output)
            self.assertFalse(self.index_path.exists())
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])

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

    def test_interrupted_download_removes_partial_file(self):
        class InterruptedDownloader(FailingDownloader):
            def next_chunk(self):
                self.file_handle.write(b"partial")
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "report.pdf"
            with mock.patch.object(downloader, "MediaIoBaseDownload", InterruptedDownloader):
                with self.assertRaises(KeyboardInterrupt):
                    downloader.download_drive_file(FakeDrive(), "file-id", destination, "application/pdf")
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
            self.assertEqual(downloader.load_index(), {"file-id": "Course/slides.pdf"})

    def test_replace_conversion_removes_indexed_source_when_pdf_already_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            source = course_dir / "slides.pptx"
            pdf = course_dir / "slides.pdf"
            source.write_bytes(b"slides")
            pdf.write_bytes(b"%PDF-converted")
            downloaded_ids = {"file-id": "Course/slides.pptx"}
            report = DownloadReport()

            request = mock.Mock()
            request.execute.return_value = {
                "name": "slides.pptx",
                "mimeType": "application/vnd.ms-powerpoint",
            }
            files = mock.Mock()
            files.get.return_value = request
            drive = mock.Mock()
            drive.files.return_value = files

            with mock.patch.object(
                downloader,
                "list_course_files",
                return_value=[CourseFile("file-id", "slides.pptx")],
            ), mock.patch.object(downloader, "download_drive_file") as download:
                downloader.download_all_for_course(
                    object(),
                    drive,
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(convert_powerpoint=True, keep_originals=False),
                    report,
                    libreoffice_cmd="soffice",
                )

            download.assert_not_called()
            self.assertFalse(source.exists())
            self.assertEqual(downloaded_ids["file-id"], "Course/slides.pdf")
            self.assertEqual(report.items[0].status, "converted")
            self.assertEqual(report.items[0].output_paths, ("Course/slides.pdf",))
            self.assertEqual(downloader.load_index(), {"file-id": "Course/slides.pdf"})

    def test_replace_conversion_removes_redownloaded_source_when_pdf_already_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            source = course_dir / "slides.pptx"
            pdf = course_dir / "slides.pdf"
            pdf.write_bytes(b"%PDF-converted")
            downloaded_ids = {"file-id": "Course/slides.pptx"}
            report = DownloadReport()

            request = mock.Mock()
            request.execute.return_value = {
                "name": "slides.pptx",
                "mimeType": "application/vnd.ms-powerpoint",
            }
            files = mock.Mock()
            files.get.return_value = request
            drive = mock.Mock()
            drive.files.return_value = files

            def download(_drive, _file_id, destination, _mime_type):
                destination.write_bytes(b"slides")
                return True

            with mock.patch.object(
                downloader,
                "list_course_files",
                return_value=[CourseFile("file-id", "slides.pptx")],
            ), mock.patch.object(
                downloader,
                "download_drive_file",
                side_effect=download,
            ) as download_file:
                downloader.download_all_for_course(
                    object(),
                    drive,
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(convert_powerpoint=True, keep_originals=False),
                    report,
                    libreoffice_cmd="soffice",
                )

            download_file.assert_called_once()
            self.assertFalse(source.exists())
            self.assertEqual(downloaded_ids["file-id"], "Course/slides.pdf")
            self.assertEqual(report.items[0].status, "converted")
            self.assertEqual(report.items[0].output_paths, ("Course/slides.pdf",))
            self.assertEqual(downloader.load_index(), {"file-id": "Course/slides.pdf"})

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

    def test_indexed_duplicate_collapses_to_identical_canonical_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            canonical = course_dir / "report.pdf"
            duplicate = course_dir / "report_1.pdf"
            canonical.write_bytes(b"same file")
            duplicate.write_bytes(b"same file")
            downloaded_ids = {"file-id": "Course/report_1.pdf"}
            report = DownloadReport()

            request = mock.Mock()
            request.execute.return_value = {
                "name": "report.pdf",
                "mimeType": "application/pdf",
            }
            files = mock.Mock()
            files.get.return_value = request
            drive = mock.Mock()
            drive.files.return_value = files

            with mock.patch.object(
                downloader,
                "list_course_files",
                return_value=[CourseFile("file-id", "report.pdf")],
            ), mock.patch.object(downloader, "download_drive_file") as download:
                downloader.download_all_for_course(
                    object(),
                    drive,
                    Course("course-id", "Course", "ACTIVE"),
                    base_dir,
                    downloaded_ids,
                    DownloadOptions(),
                    report,
                )

            download.assert_not_called()
            self.assertTrue(canonical.exists())
            self.assertFalse(duplicate.exists())
            self.assertEqual(downloaded_ids["file-id"], "Course/report.pdf")
            self.assertEqual(report.items[0].status, "skipped_existing")
            self.assertEqual(report.items[0].output_paths, ("Course/report.pdf",))
            self.assertEqual(downloader.load_index(), {"file-id": "Course/report.pdf"})

    def test_dry_run_preserves_duplicates_index_and_directory_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory)
            course_dir = base_dir / "Course"
            course_dir.mkdir()
            (course_dir / "report.pdf").write_bytes(b"same")
            (course_dir / "report_1.pdf").write_bytes(b"same")
            ids = {"file-id": "Course/report_1.pdf", "missing-id": "Course/missing.pdf"}
            downloader.save_index(ids)
            previous_index = self.index_path.read_bytes()
            previous_tree = {p.relative_to(base_dir): p.read_bytes() for p in base_dir.rglob("*") if p.is_file()}
            drive = mock.Mock()
            drive.files.return_value.get.return_value.execute.side_effect = [
                {"name": "report.pdf", "mimeType": "application/pdf"},
                {"name": "missing.pdf", "mimeType": "application/pdf"},
            ]
            with mock.patch.object(downloader, "list_course_files", return_value=[
                CourseFile("file-id", "report.pdf"), CourseFile("missing-id", "missing.pdf"),
            ]):
                downloader.download_all_for_course(
                    object(), drive, Course("course-id", "Course", "ACTIVE"),
                    base_dir, ids, DownloadOptions(), DownloadReport(), dry_run=True,
                )
            self.assertEqual(ids, {"file-id": "Course/report_1.pdf", "missing-id": "Course/missing.pdf"})
            self.assertEqual(self.index_path.read_bytes(), previous_index)
            self.assertEqual({p.relative_to(base_dir): p.read_bytes() for p in base_dir.rglob("*") if p.is_file()}, previous_tree)
            destination = base_dir / "uncreated" / "file.pdf"
            downloader.download_drive_file(FakeDrive(), "new-id", destination, "application/pdf", dry_run=True)
            self.assertFalse(destination.parent.exists())

    def test_different_content_collision_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            canonical = pathlib.Path(directory) / "report.pdf"
            candidate = pathlib.Path(directory) / "report_1.pdf"
            canonical.write_bytes(b"first file")
            candidate.write_bytes(b"second file")

            result = downloader.collapse_identical_duplicate(candidate, canonical)

            self.assertEqual(result, candidate)
            self.assertTrue(canonical.exists())
            self.assertTrue(candidate.exists())

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

    def test_corrupt_index_can_continue_only_after_confirmed_private_backup(self):
        contents = b'{"downloaded_ids":\xff'
        self.index_path.write_bytes(contents)
        old_backup = self.index_path.with_name(".download_index.json.previous.corrupt.bak")
        old_backup.write_bytes(b"older evidence")

        def proceed(_args, ids, _report):
            backups = list(self.index_path.parent.glob("*.corrupt.bak"))
            self.assertEqual(len(backups), 2)
            backup = next(path for path in backups if path != old_backup)
            self.assertEqual(backup.read_bytes(), contents)
            self.assertEqual(self.index_path.read_bytes(), contents)
            if sys.platform != "win32":
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(ids, {})
            downloader.save_index({"new": "Course/new.pdf"})
            return 0

        with mock.patch.object(sys, "argv", ["gcr"]), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="yes") as confirm, \
             mock.patch.object(downloader, "run_downloads", side_effect=proceed):
            self.assertEqual(downloader.main(), 0)
        confirm.assert_called_once()
        self.assertEqual(old_backup.read_bytes(), b"older evidence")
        self.assertEqual(downloader.load_index(), {"new": "Course/new.pdf"})

    def test_corrupt_index_stops_run_without_overwriting_evidence(self):
        for contents in (b"{", b"[]", b"{}", b'{"downloaded_ids":"bad"}', b'{"downloaded_ids":{"id":null}}', b"\xff"):
            with self.subTest(contents=contents):
                self.index_path.write_bytes(contents)
                output = io.StringIO()
                with mock.patch.object(sys, "argv", ["gcr"]), \
                     mock.patch.object(sys.stdin, "isatty", return_value=False), \
                     mock.patch.object(downloader, "get_credentials") as auth, \
                     mock.patch("sys.stdout", output):
                    self.assertEqual(downloader.main(), 1)
                auth.assert_not_called()
                self.assertEqual(self.index_path.read_bytes(), contents)
                self.assertIn("index", output.getvalue().lower())
                self.assertIn("back up", output.getvalue().lower())

    def test_corrupt_index_decline_noninteractive_and_dry_run_have_no_side_effects(self):
        for interactive, dry_run, answer in ((True, False, "n"), (False, False, "y"), (True, True, "y"), (True, False, EOFError())):
            with self.subTest(interactive=interactive, dry_run=dry_run, answer=answer):
                self.index_path.write_bytes(b"corrupt evidence")
                with mock.patch.object(sys, "argv", ["gcr", *(["--dry-run"] if dry_run else [])]), \
                     mock.patch.object(sys.stdin, "isatty", return_value=interactive), \
                     mock.patch("builtins.input", side_effect=[answer]) as confirm, \
                     mock.patch.object(downloader, "get_credentials") as auth:
                    self.assertEqual(downloader.main(), 1)
                auth.assert_not_called()
                self.assertEqual(confirm.call_count, int(interactive and not dry_run))
                self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])
                self.assertEqual(self.index_path.read_bytes(), b"corrupt evidence")

    def test_corrupt_index_backup_failure_stops_before_auth_and_preserves_evidence(self):
        existing = self.index_path.with_name(".download_index.json.previous.corrupt.bak")
        existing.write_bytes(b"older evidence")
        for operation, error in (("fsync", OSError("disk full")), ("link", FileExistsError("backup exists")), ("link", PermissionError("no hard links")), ("fsync", KeyboardInterrupt())):
            with self.subTest(operation=operation, error=error):
                self.index_path.write_bytes(b"corrupt evidence")
                with mock.patch.object(sys, "argv", ["gcr"]), \
                     mock.patch.object(sys.stdin, "isatty", return_value=True), \
                     mock.patch("builtins.input", return_value="yes"), \
                     mock.patch.object(downloader.os, operation, side_effect=error), \
                     mock.patch.object(downloader, "get_credentials") as auth:
                    self.assertEqual(downloader.main(), 130 if isinstance(error, KeyboardInterrupt) else 1)
                auth.assert_not_called()
                self.assertEqual(set(self.index_path.parent.iterdir()), {self.index_path, existing})
                self.assertEqual(self.index_path.read_bytes(), b"corrupt evidence")
                self.assertEqual(existing.read_bytes(), b"older evidence")

    def test_corrupt_index_load_itself_still_raises_without_writes(self):
        self.index_path.write_bytes(b"corrupt evidence")
        with self.assertRaises(ValueError):
            downloader.load_index()
        self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])
        self.assertEqual(self.index_path.read_bytes(), b"corrupt evidence")

    def test_missing_index_starts_empty(self):
        self.assertEqual(downloader.load_index(), {})

    def test_indexed_path_must_stay_inside_download_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = pathlib.Path(directory) / "downloads"
            base_dir.mkdir()

            result = downloader.get_indexed_path(base_dir, "../outside.pdf")

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
