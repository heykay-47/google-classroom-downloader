import unittest

from gcr_downloader.files import (
    GOOGLE_EXPORTS,
    allocate_unique_name,
    conversion_kind,
    ensure_extension,
    is_video_file,
    safe_filename,
    validate_course_id,
    validate_file_id,
)
from gcr_downloader.models import DownloadOptions


class FilePolicyTests(unittest.TestCase):
    def test_filename_and_id_safety(self):
        self.assertEqual(safe_filename("../week/notes?.pdf"), "week_notes_.pdf")
        self.assertEqual(safe_filename("..."), "file")
        self.assertTrue(validate_course_id("course-1"))
        self.assertTrue(validate_file_id("drive_file-1"))
        self.assertFalse(validate_file_id("../secret"))

    def test_workspace_exports_have_expected_extensions(self):
        self.assertEqual(
            GOOGLE_EXPORTS["application/vnd.google-apps.presentation"][1],
            ".pptx",
        )
        self.assertEqual(
            ensure_extension("deck", "application/vnd.google-apps.presentation"),
            "deck.pptx",
        )

    def test_video_and_conversion_policy(self):
        self.assertTrue(is_video_file("lecture.bin", "video/mp4"))
        self.assertFalse(is_video_file("notes.txt", None))
        options = DownloadOptions(convert_word=True, convert_powerpoint=True)
        self.assertEqual(conversion_kind("notes.docx", options), "word")
        self.assertEqual(conversion_kind("deck.pptx", options), "powerpoint")
        self.assertIsNone(conversion_kind("sheet.xlsx", options))

    def test_duplicate_names_are_stable(self):
        used = {"Course/report.pdf", "Course/report_1.pdf"}
        self.assertEqual(
            allocate_unique_name("Course/report.pdf", used),
            "Course/report_2.pdf",
        )


if __name__ == "__main__":
    unittest.main()
