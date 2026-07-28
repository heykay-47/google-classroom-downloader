"""
Shared constants for Google Classroom Downloader.
"""

# Google OAuth2 Scopes required for the application
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Google Workspace export formats
# Maps Google mime types to (export_mime_type, file_extension)
GOOGLE_DOC_EXPORTS = {
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

# File constants
TOKEN_FILE = "token.json"
INDEX_FILE = "download_index.json"
DEFAULT_DOWNLOAD_DIR = "downloads"

# Video file extensions and MIME types
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
VIDEO_MIME_PREFIXES = (
    "video/",
    "application/x-mpegURL",
    "application/dash+xml",
)
