import tempfile
import unittest
from unittest import mock

from test_support import install_dependency_stubs


install_dependency_stubs()

from app import downloads, main
from app.drive import DriveMetadata
from cli import classroom_downloader as cli
from gcr_downloader.models import Course, CourseFile, DownloadOptions, DownloadReport


class MetadataRequest:
    def execute(self):
        return {"name": "lecture.mp4", "mimeType": "video/mp4"}


class MetadataFiles:
    def get(self, **_kwargs):
        return MetadataRequest()


class MetadataDrive:
    def files(self):
        return MetadataFiles()


class ParityContractTests(unittest.TestCase):
    def test_enriched_catalog_keeps_web_cli_first_seen_file_identity(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value

        def response(key, title, ids):
            request = mock.Mock()
            request.execute.return_value = {key: [{
                "id": "post-1", "title": title,
                "materials": [{"driveFile": {"driveFile": {"id": file_id, "title": name}}} for file_id, name in ids],
            }]}
            return request

        courses.courseWork.return_value.list.return_value = response("courseWork", "Assignment", [("a", "first.pdf")])
        courses.courseWorkMaterials.return_value.list.return_value = response("courseWorkMaterial", "Material", [("a", "duplicate.pdf"), ("b", "second.pdf")])
        courses.announcements.return_value.list.return_value = response("announcements", None, [("c", "third.pdf")])
        request = type("Request", (), {"session": {"token": {}}})()
        with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
             mock.patch.object(main, "build", return_value=classroom):
            web_files = main.get_course_files(request, "course-1")

        drive = mock.Mock()
        drive.files.return_value.get.return_value.execute.return_value = {"mimeType": "application/pdf"}
        report = DownloadReport()
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(cli, "download_drive_file") as download:
            cli.download_all_for_course(
                classroom, drive, Course("course-1", "Course", "ACTIVE"), cli.pathlib.Path(directory),
                {}, DownloadOptions(), report, dry_run=True,
            )
        self.assertEqual([f["id"] for f in web_files], [call.args[1] for call in download.call_args_list])
        self.assertEqual([f["name"] for f in web_files], [item.source_name for item in report.items])
        self.assertEqual([f["source_kind"] for f in web_files], ["assignment", "material", "announcement"])
        self.assertEqual([f["name"] for f in web_files], ["first.pdf", "second.pdf", "third.pdf"])

    def test_video_exclusion_has_same_status_in_both_adapters(self):
        course = Course("course-1", "Course", "ACTIVE")
        course_file = CourseFile("file-1", "lecture.mp4")
        options = DownloadOptions(include_videos=False)

        with mock.patch.object(
            downloads,
            "get_metadata",
            return_value=DriveMetadata("lecture.mp4", "video/mp4"),
        ), mock.patch.object(downloads, "download_to_spool") as web_download:
            _entries, web_report = downloads.prepare_download(
                MetadataDrive(),
                course,
                [course_file],
                options,
            )

        cli_report = DownloadReport()
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(cli, "INDEX_FILE", str(cli.pathlib.Path(directory) / "download_index.json")), \
             mock.patch.object(cli, "list_course_files", return_value=[course_file]), \
             mock.patch.object(cli, "download_drive_file") as cli_download:
            cli.download_all_for_course(
                object(),
                MetadataDrive(),
                course,
                cli.pathlib.Path("downloads"),
                {},
                options,
                cli_report,
            )

        self.assertEqual(web_report.items[0].status, "skipped_video")
        self.assertEqual(cli_report.items[0].status, "skipped_video")
        web_download.assert_not_called()
        cli_download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
