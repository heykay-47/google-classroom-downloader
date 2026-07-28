import zipstream
import logging
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


def stream_zip(generator):
    z = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_DEFLATED)

    for path, data in generator:
        try:
            if path and data:
                z.write_iter(path, [data])
                logger.info(f"ADDED TO ZIP: {path}")
        except Exception:
            logger.exception("Failed to add %s to zip", path)

    return StreamingResponse(
        z,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=classroom_download.zip",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
