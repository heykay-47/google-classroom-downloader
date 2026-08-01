import os
import pathlib
import unittest

from app.gotenberg import convert_to_pdf


@unittest.skipUnless(os.environ.get("GOTENBERG_INTEGRATION") == "1", "Gotenberg integration disabled")
class GotenbergIntegrationTests(unittest.TestCase):
    def test_docx_and_pptx_convert_to_pdf(self):
        base_url = os.environ.get("GOTENBERG_URL", "http://gotenberg:3000")
        for fixture in ("sample.docx", "sample.pptx"):
            path = pathlib.Path("tests/fixtures") / fixture
            with self.subTest(fixture=fixture), path.open("rb") as source:
                pdf = convert_to_pdf(source, fixture, base_url=base_url, max_attempts=1)
                self.assertEqual(pdf.read(5), b"%PDF-")
                pdf.close()


if __name__ == "__main__":
    unittest.main()
