"""
Classroom catalog: course listing, lookup, and file enumeration shared by
the web app and the local CLI.
"""

from gcr_downloader.files import validate_course_id, validate_file_id
from gcr_downloader.models import Course, CourseFile


class CatalogError(RuntimeError):
    """Google Classroom catalog operation failed."""


def list_courses(classroom, state: str = "all", name_contains: str | None = None) -> list[Course]:
    normalized_state = state.lower()
    if normalized_state not in {"active", "archived", "all"}:
        raise ValueError("Invalid course state")
    courses: list[Course] = []
    page_token = None
    try:
        while True:
            payload = classroom.courses().list(
                pageToken=page_token,
                courseStates=["ACTIVE", "ARCHIVED"],
            ).execute()
            for item in payload.get("courses", []):
                course = Course(
                    id=str(item.get("id", "")),
                    name=item.get("name") or "Unnamed Course",
                    state=(item.get("courseState") or "UNKNOWN").upper(),
                )
                state_matches = normalized_state == "all" or course.state.lower() == normalized_state
                name_matches = not name_contains or name_contains.lower() in course.name.lower()
                if validate_course_id(course.id) and state_matches and name_matches:
                    courses.append(course)
            page_token = payload.get("nextPageToken")
            if not page_token:
                return courses
    except Exception as exc:
        raise CatalogError("Failed to fetch courses") from exc


def get_course(classroom, course_id: str) -> Course:
    if not validate_course_id(course_id):
        raise ValueError("Invalid course ID")
    try:
        item = classroom.courses().get(
            courseId=course_id,
            fields="id,name,courseState",
        ).execute()
    except Exception as exc:
        raise CatalogError("Failed to fetch course") from exc
    return Course(
        id=str(item.get("id", course_id)),
        name=item.get("name") or "Unnamed Course",
        state=(item.get("courseState") or "UNKNOWN").upper(),
    )


def list_course_files(classroom, course_id: str) -> list[CourseFile]:
    if not validate_course_id(course_id):
        raise ValueError("Invalid course ID")
    files: list[CourseFile] = []
    seen: set[str] = set()

    def collect(payload: dict, key: str, fallback: str) -> None:
        for post in payload.get(key, []):
            title = post.get("title", fallback)
            for material in post.get("materials", []):
                drive_file = material.get("driveFile", {}).get("driveFile", {})
                file_id = drive_file.get("id")
                if validate_file_id(file_id) and file_id not in seen:
                    seen.add(file_id)
                    files.append(CourseFile(file_id, drive_file.get("title") or title))

    try:
        page_token = None
        while True:
            payload = classroom.courses().courseWork().list(
                courseId=course_id,
                pageToken=page_token,
            ).execute()
            collect(payload, "courseWork", "Assignment")
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        page_token = None
        while True:
            payload = classroom.courses().courseWorkMaterials().list(
                courseId=course_id,
                pageToken=page_token,
            ).execute()
            collect(payload, "courseWorkMaterial", "Material")
            page_token = payload.get("nextPageToken")
            if not page_token:
                return files
    except Exception as exc:
        raise CatalogError("Failed to fetch course files") from exc


def select_course_files(available: list[CourseFile], selected_ids: list[str]) -> list[CourseFile]:
    if not selected_ids:
        raise ValueError("Select at least one file")
    by_id = {item.id: item for item in available}
    selected: list[CourseFile] = []
    seen: set[str] = set()
    for file_id in selected_ids:
        if not validate_file_id(file_id) or file_id not in by_id:
            raise ValueError("Selected file is not attached to course")
        if file_id not in seen:
            seen.add(file_id)
            selected.append(by_id[file_id])
    return selected
