import io
import logging
import tempfile
import time
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseDownload

from gcr_downloader.files import GOOGLE_EXPORTS, ensure_extension, safe_filename, validate_file_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DriveMetadata:
    name: str
    mime_type: str | None


class DriveDownloadError(RuntimeError):
    """Drive metadata or content transfer failed."""


def get_metadata(
    drive,
    file_id: str,
    title_hint: str,
    max_attempts: int = 3,
) -> DriveMetadata:
    if not validate_file_id(file_id):
        raise DriveDownloadError("Invalid Drive file ID")
    for attempt in range(max_attempts):
        try:
            payload = drive.files().get(fileId=file_id, fields="name,mimeType").execute()
            name = ensure_extension(
                safe_filename(payload.get("name") or title_hint or file_id),
                payload.get("mimeType"),
            )
            return DriveMetadata(name, payload.get("mimeType"))
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise DriveDownloadError("Failed to fetch Drive metadata") from exc
            time.sleep(2**attempt)


def download_to_spool(
    drive,
    file_id: str,
    mime_type: str | None,
    max_attempts: int = 3,
) -> tempfile.SpooledTemporaryFile:
    if not validate_file_id(file_id):
        raise DriveDownloadError("Invalid Drive file ID")
    for attempt in range(max_attempts):
        stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            export = GOOGLE_EXPORTS.get(mime_type)
            request = (
                drive.files().export_media(fileId=file_id, mimeType=export[0])
                if export
                else drive.files().get_media(fileId=file_id)
            )
            downloader = MediaIoBaseDownload(stream, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            stream.seek(0)
            return stream
        except Exception as exc:
            stream.close()
            if attempt == max_attempts - 1:
                raise DriveDownloadError("Drive download failed after three attempts") from exc
            time.sleep(2**attempt)


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
                time.sleep(wait_time)
            else:
                logger.error(
                    f"SKIPPED: ID {file_id} failed after {max_retries} attempts. Error: {e}"
                )
                return None, None
    return None, None
