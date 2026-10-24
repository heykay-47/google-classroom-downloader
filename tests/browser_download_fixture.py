"""Synthetic local-only browser fixture; never connects to Google.

Run from the repository: python -m uvicorn tests.browser_download_fixture:app --port 8768
Open /fixture/login, then exercise the real courses page and attachment endpoint.
"""
import io
import random
import time

from fastapi import Request
from starlette.responses import RedirectResponse

from app import main
from app.zipstreamer import ArchiveEntry
from gcr_downloader.models import Course, CourseFile, DownloadReport


main.Credentials.from_authorized_user_info = staticmethod(lambda *args: object())
main.build = lambda *args, **kwargs: object()
main.list_courses = lambda *args, **kwargs: [
    Course("success", "Synthetic success", "ACTIVE"),
    Course("failure", "Synthetic preparation failure", "ACTIVE"),
    Course("slow", "Synthetic slow transfer", "ACTIVE"),
]
main.get_course = lambda _, course_id: Course(course_id, "Synthetic course", "ACTIVE")
main.list_course_files = lambda *args: [CourseFile("notes", "Synthetic notes.txt")]


def prepare_download(_drive, course, _selected, _options):
    time.sleep(1.5)
    if course.id == "failure":
        raise RuntimeError("Synthetic preparation failure")
    if course.id == "slow":
        class SlowStream(io.BytesIO):
            def read(self, size=-1):
                time.sleep(0.2)
                return super().read(size)

        payload = random.Random(8).randbytes(1024 * 1024)
        return [ArchiveEntry("Synthetic/slow.bin", SlowStream(payload))], DownloadReport()
    return [ArchiveEntry("Synthetic/notes.txt", io.BytesIO(b"synthetic browser verification\n"))], DownloadReport()


main.prepare_download = prepare_download
app = main.app


@app.get("/fixture/login")
def fixture_login(request: Request):
    request.session["token"] = {}
    return RedirectResponse("/courses")


@app.get("/fixture/expire")
def fixture_expire(request: Request):
    request.session.clear()
    return {"expired": True}
