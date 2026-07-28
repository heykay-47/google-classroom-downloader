import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def list_all_courses(classroom):
    courses = []
    page_token = None

    try:
        while True:
            resp = (
                classroom.courses()
                .list(
                    pageToken=page_token,
                    courseStates=["ACTIVE", "ARCHIVED"],
                )
                .execute()
            )

            courses.extend(resp.get("courses", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        logger.exception("Failed to fetch courses")
        raise HTTPException(status_code=502, detail="Failed to fetch courses") from exc

    return courses


def list_course_files(classroom, course_id):
    files = []

    try:
        # Coursework
        token = None
        while True:
            resp = (
                classroom.courses()
                .courseWork()
                .list(
                    courseId=course_id,
                    pageToken=token,
                )
                .execute()
            )

            for cw in resp.get("courseWork", []):
                title = cw.get("title", "Assignment")
                for mat in cw.get("materials", []):
                    df = mat.get("driveFile", {}).get("driveFile")
                    if df and df.get("id"):
                        files.append((df["id"], df.get("title", title)))

            token = resp.get("nextPageToken")
            if not token:
                break

        # Coursework materials
        token = None
        while True:
            resp = (
                classroom.courses()
                .courseWorkMaterials()
                .list(
                    courseId=course_id,
                    pageToken=token,
                )
                .execute()
            )

            for m in resp.get("courseWorkMaterial", []):
                title = m.get("title", "Material")
                for mat in m.get("materials", []):
                    df = mat.get("driveFile", {}).get("driveFile")
                    if df and df.get("id"):
                        files.append((df["id"], df.get("title", title)))

            token = resp.get("nextPageToken")
            if not token:
                break
    except Exception as exc:
        logger.exception("Failed to fetch files for course %s", course_id)
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch course files",
        ) from exc

    return files
