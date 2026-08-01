import tempfile
import time
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseDownload

from gcr_downloader.files import GOOGLE_EXPORTS, ensure_extension, safe_filename, validate_file_id


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
