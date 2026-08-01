import pathlib
import unittest


class WebTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = pathlib.Path("app/templates/courses.html").read_text(encoding="utf-8")

    def test_template_contains_parity_controls(self):
        for name in (
            'name="course_id"',
            'name="skip_videos"',
            'name="convert_word"',
            'name="convert_powerpoint"',
            'name="replace_originals"',
            'data-course-state=',
        ):
            self.assertIn(name, self.template)

    def test_template_removes_obsolete_course_scope(self):
        self.assertNotIn('name="download_scope"', self.template)
        self.assertNotIn('name="course_ids"', self.template)

    def test_api_file_names_are_rendered_with_dom_text_nodes(self):
        self.assertIn("document.createTextNode", self.template)
        self.assertNotIn("${x.name}", self.template)
        self.assertNotIn('onclick="openDrawer', self.template)


if __name__ == "__main__":
    unittest.main()
