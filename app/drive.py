import io
import re
import logging
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
    "application/vnd.google-apps.jam": ("application/pdf", ".pdf"),
}


def safe_filename(name: str | None) -> str:
    """
    Make a filesystem-safe filename, preventing path traversal.
    """
    if not name:
        name = "file"
    # Remove path separators to prevent directory traversal
    name = (
        name.replace("../", "").replace("..\\", "").replace("/", "_").replace("\\", "_")
    )
    # Replace other unsafe characters
    name = re.sub(r"[^\w.\- ]+", "_", name)
    name = name.strip()[:80]
    return "file" if not name.strip(". ") else name


def validate_file_id(file_id: str) -> bool:
    """
    Validate that file_id is a valid Google Drive file ID.
    File IDs are alphanumeric strings with hyphens and underscores.
    """
    if not file_id or not isinstance(file_id, str):
        return False
    # Allow alphanumeric, hyphens, and underscores only
    return bool(re.match(r"^[a-zA-Z0-9\-_]+$", file_id))


def download_file_bytes(drive, file_id: str, max_retries: int = 3):
    """
    Download a file from Google Drive with retry logic.
    """
    # Validate file ID before attempting download
    if not validate_file_id(file_id):
        logger.error(f"SKIPPED: Invalid file ID format: {file_id}")
        return None, None

    for attempt in range(max_retries):
        try:
            meta = drive.files().get(fileId=file_id, fields="name,mimeType").execute()
            name = safe_filename(meta.get("name"))
            mime = meta.get("mimeType")

            logger.info(f"FETCHING: {name} ({mime})")

            if mime in GOOGLE_EXPORTS:
                export_mime, ext = GOOGLE_EXPORTS[mime]
                request = drive.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
                if not name.lower().endswith(ext):
                    name += ext
            else:
                request = drive.files().get_media(fileId=file_id)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            fh.seek(0)
            logger.info(f"SUCCESS: {name}")
            return name, fh.read()
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"Attempt {attempt + 1} failed for {file_id}, retrying in {wait_time}s..."
                )
                import time

                time.sleep(wait_time)
            else:
                logger.error(
                    f"SKIPPED: ID {file_id} failed after {max_retries} attempts. Error: {e}"
                )
                return None, None
    return None, None
