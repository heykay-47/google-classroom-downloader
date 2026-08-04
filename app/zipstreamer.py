import json
from dataclasses import dataclass
from typing import BinaryIO

import zipstream
from fastapi.responses import StreamingResponse

from gcr_downloader.models import DownloadReport


@dataclass
class ArchiveEntry:
    path: str
    stream: BinaryIO


def stream_zip(entries: list[ArchiveEntry], report: DownloadReport):
    def read_chunks(stream: BinaryIO):
        stream.seek(0)
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            yield chunk

    def archive_body():
        archive = zipstream.ZipFile(
            mode="w",
            compression=zipstream.ZIP_DEFLATED,
            allowZip64=True,
        )
        try:
            for entry in entries:
                archive.write_iter(entry.path, read_chunks(entry.stream))
            report_bytes = json.dumps(
                report.to_dict(),
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            archive.write_iter("_download_report.json", [report_bytes])
            yield from archive
        finally:
            for entry in entries:
                entry.stream.close()

    return StreamingResponse(
        archive_body(),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=classroom_download.zip",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
