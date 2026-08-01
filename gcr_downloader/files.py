"""
Shared download policy: OAuth scopes, Workspace export formats, and file
handling rules shared by the web app and the local CLI.
"""

import pathlib
import re

from gcr_downloader.models import DownloadOptions

RESOURCE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
WORD_EXTENSIONS = {".doc", ".docx"}
POWERPOINT_EXTENSIONS = {".ppt", ".pptx"}

# Google OAuth2 Scopes required for the application
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Google Workspace export formats
# Maps Google mime types to (export_mime_type, file_extension)
GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/pdf",
        ".pdf",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.drawing": (
        "image/png",
        ".png",
    ),
    "application/vnd.google-apps.jam": (
        "application/pdf",
        ".pdf",
    ),
}

# Video file extensions and MIME types
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
VIDEO_MIME_PREFIXES = (
    "video/",
    "application/x-mpegURL",
    "application/dash+xml",
)


def safe_filename(name: str | None) -> str:
    value = name or "file"
    value = value.replace("../", "").replace("..\\", "")
    value = value.replace("/", "_").replace("\\", "_")
    value = re.sub(r"[^\w.\- ]+", "_", value).strip()[:80]
    return value if value.strip(". ") else "file"


def validate_course_id(course_id: str) -> bool:
    return isinstance(course_id, str) and bool(RESOURCE_ID.fullmatch(course_id))


def validate_file_id(file_id: str) -> bool:
    return isinstance(file_id, str) and bool(RESOURCE_ID.fullmatch(file_id))


def ensure_extension(name: str, mime_type: str | None) -> str:
    export = GOOGLE_EXPORTS.get(mime_type)
    if export and not name.lower().endswith(export[1]):
        return name + export[1]
    return name


def is_video_file(name: str, mime_type: str | None) -> bool:
    return pathlib.Path(name).suffix.lower() in VIDEO_EXTENSIONS or bool(
        mime_type and mime_type.startswith(VIDEO_MIME_PREFIXES)
    )


def conversion_kind(name: str, options: DownloadOptions) -> str | None:
    suffix = pathlib.Path(name).suffix.lower()
    if options.convert_word and suffix in WORD_EXTENSIONS:
        return "word"
    if options.convert_powerpoint and suffix in POWERPOINT_EXTENSIONS:
        return "powerpoint"
    return None


def allocate_unique_name(path: str, used_paths: set[str]) -> str:
    candidate = pathlib.PurePosixPath(path)
    if path not in used_paths:
        used_paths.add(path)
        return path
    counter = 1
    while True:
        renamed = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}").as_posix()
        if renamed not in used_paths:
            used_paths.add(renamed)
            return renamed
        counter += 1
