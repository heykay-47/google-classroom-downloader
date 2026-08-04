import unittest

from gcr_downloader.models import DownloadOptions, DownloadReport, ItemResult


class DownloadModelTests(unittest.TestCase):
    def test_download_option_defaults_are_non_destructive(self):
        self.assertEqual(
            DownloadOptions(),
            DownloadOptions(
                include_videos=True,
                convert_word=False,
                convert_powerpoint=False,
                keep_originals=True,
            ),
        )

    def test_report_serializes_schema_and_status_counts(self):
        report = DownloadReport()
        report.add(ItemResult("Course", "notes.docx", "downloaded", ("Course/notes.docx",)))
        report.add(ItemResult("Course", "lecture.mp4", "skipped_video", message="Video excluded"))

        self.assertEqual(report.summary(), {"downloaded": 1, "skipped_video": 1})
        payload = report.to_dict()
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["items"][0]["output_paths"], ["Course/notes.docx"])
        self.assertNotIn("traceback", str(payload).lower())


if __name__ == "__main__":
    unittest.main()
