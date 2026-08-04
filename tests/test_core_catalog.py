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

        files = list_course_files(classroom, "course-1")

        self.assertEqual([(item.id, item.title_hint) for item in files], [("a", "A"), ("b", "B")])

    def test_selection_rejects_file_not_in_course(self):
        available = list_course_files_from_pairs([("a", "A"), ("b", "B")])
        with self.assertRaisesRegex(ValueError, "not attached"):
            select_course_files(available, ["a", "forged"])


def list_course_files_from_pairs(pairs):
    from gcr_downloader.models import CourseFile
    return [CourseFile(file_id, title) for file_id, title in pairs]


if __name__ == "__main__":
    unittest.main()
