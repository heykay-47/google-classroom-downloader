import unittest
from unittest import mock

from gcr_downloader.catalog import (
    list_course_files,
    list_courses,
    select_course_files,
)


def response(payload):
    request = mock.Mock()
    request.execute.return_value = payload
    return request


class CatalogTests(unittest.TestCase):
    def test_file_metadata_comes_from_first_post_and_attachment_hint(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value
        def attachment(file_id, title):
            return {"driveFile": {"driveFile": {"id": file_id, "title": title}}}

        courses.courseWork.return_value.list.return_value = response({"courseWork": [{
            "id": "p1", "title": "Week 1", "creationTime": "2026-10-01T12:00:00Z",
            "materials": [attachment("a", "Notes.PDF")],
        }]})
        courses.courseWorkMaterials.return_value.list.return_value = response({"courseWorkMaterial": [{
            "id": "p2", "title": "", "materials": [attachment("a", "duplicate.docx"), attachment("b", "slides.pptx")],
        }]})
        courses.announcements.return_value.list.return_value = response({"announcements": [{
            "id": "p3", "materials": [attachment("c", "No extension")],
        }]})

        files = list_course_files(classroom, "course-1")

        self.assertEqual([(f.source_kind, f.post_id, f.post_title, f.post_date, f.file_type) for f in files], [
            ("assignment", "p1", "Week 1", "2026-10-01T12:00:00Z", "pdf"),
            ("material", "p2", "Material", None, "pptx"),
            ("announcement", "p3", "Announcement", None, None),
        ])
        self.assertEqual([f.id for f in files], ["a", "b", "c"])

    def test_missing_filename_does_not_infer_type_from_post_title(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value
        courses.courseWork.return_value.list.return_value = response({"courseWork": [{
            "title": "Post named notes.pdf", "materials": [{"driveFile": {"driveFile": {"id": "a"}}}],
        }]})
        courses.courseWorkMaterials.return_value.list.return_value = response({})
        courses.announcements.return_value.list.return_value = response({})

        item, = list_course_files(classroom, "course-1")

        self.assertEqual(item.title_hint, "Post named notes.pdf")
        self.assertIsNone(item.file_type)
        self.assertIsNone(item.post_id)
        self.assertIsNone(item.post_date)

    def test_courses_paginate_and_filter_archived(self):
        classroom = mock.Mock()
        resource = classroom.courses.return_value
        resource.list.side_effect = [
            response({"courses": [{"id": "1", "name": "Active", "courseState": "ACTIVE"}], "nextPageToken": "next"}),
            response({"courses": [{"id": "2", "name": "Archive", "courseState": "ARCHIVED"}]}),
        ]

        courses = list_courses(classroom, state="archived")

        self.assertEqual([course.id for course in courses], ["2"])
        first_call = resource.list.call_args_list[0].kwargs
        self.assertEqual(first_call["courseStates"], ["ACTIVE", "ARCHIVED"])

    def test_course_files_deduplicate_in_first_seen_order(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value
        coursework = courses.courseWork.return_value
        materials = courses.courseWorkMaterials.return_value
        coursework.list.return_value = response({
            "courseWork": [{"title": "Week 1", "materials": [{"driveFile": {"driveFile": {"id": "a", "title": "A"}}}]}]
        })
        materials.list.return_value = response({
            "courseWorkMaterial": [{"title": "Files", "materials": [
                {"driveFile": {"driveFile": {"id": "a", "title": "A duplicate"}}},
                {"driveFile": {"driveFile": {"id": "b", "title": "B"}}},
            ]}]
        })
        courses.announcements.return_value.list.return_value = response({})

        files = list_course_files(classroom, "course-1")

        self.assertEqual([(item.id, item.title_hint) for item in files], [("a", "A"), ("b", "B")])

    def test_course_files_include_paginated_announcement_attachments(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value
        courses.courseWork.return_value.list.return_value = response({})
        courses.courseWorkMaterials.return_value.list.return_value = response({})
        courses.announcements.return_value.list.side_effect = [
            response({
                "announcements": [{"materials": [
                    {"driveFile": {"driveFile": {"id": "a", "title": "Notice A"}}},
                ]}],
                "nextPageToken": "next",
            }),
            response({
                "announcements": [{"materials": [
                    {"driveFile": {"driveFile": {"id": "b", "title": "Notice B"}}},
                ]}],
            }),
        ]

        files = list_course_files(classroom, "course-1")

        self.assertEqual([(item.id, item.title_hint) for item in files], [("a", "Notice A"), ("b", "Notice B")])
        self.assertEqual(
            courses.announcements.return_value.list.call_args_list[1].kwargs["pageToken"],
            "next",
        )

    def test_selection_rejects_file_not_in_course(self):
        available = list_course_files_from_pairs([("a", "A"), ("b", "B")])
        with self.assertRaisesRegex(ValueError, "not attached"):
            select_course_files(available, ["a", "forged"])


def list_course_files_from_pairs(pairs):
    from gcr_downloader.models import CourseFile
    return [CourseFile(file_id, title) for file_id, title in pairs]


if __name__ == "__main__":
    unittest.main()
