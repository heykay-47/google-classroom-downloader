import os
import tempfile
import time

import requests

GOTENBERG_URL = os.environ.get("GOTENBERG_URL", "http://localhost:3000").rstrip("/")
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 130
SPOOL_THRESHOLD = 8 * 1024 * 1024


class GotenbergError(RuntimeError):
    """Gotenberg health or conversion request failed."""


def check_health(session: requests.Session | None = None) -> bool:
    client = session or requests.Session()
    owns_client = session is None
    try:
        response = client.get(f"{GOTENBERG_URL}/health", timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        try:
            return response.status_code == 200
        finally:
            response.close()
    except requests.RequestException:
        return False
    finally:
        if owns_client:
            client.close()


def convert_to_pdf(
    source,
    filename: str,
    base_url: str = GOTENBERG_URL,
    session: requests.Session | None = None,
    max_attempts: int = 3,
):
    client = session or requests.Session()
    owns_client = session is None
    try:
        for attempt in range(max_attempts):
            source.seek(0)
            response = None
            output = None
            keep_output = False
            try:
                response = client.post(
                    f"{base_url.rstrip('/')}/forms/libreoffice/convert",
                    files=[("files", (filename, source, "application/octet-stream"))],
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    stream=True,
                )
                if 400 <= response.status_code < 500:
                    raise GotenbergError("Conversion request rejected")
                if response.status_code >= 500:
                    raise requests.RequestException("Transient Gotenberg failure")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type != "application/pdf":
                    raise GotenbergError("Conversion returned invalid content type")
                output = tempfile.SpooledTemporaryFile(max_size=SPOOL_THRESHOLD, mode="w+b")
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        output.write(chunk)
                output.seek(0)
                if output.read(5) != b"%PDF-":
                    raise GotenbergError("Conversion returned invalid PDF")
                output.seek(0)
                keep_output = True
                return output
            except GotenbergError:
                raise
            except requests.RequestException as exc:
                if attempt == max_attempts - 1:
                    raise GotenbergError("Conversion service unavailable") from exc
                time.sleep(2**attempt)
            finally:
                if response is not None:
                    response.close()
                if output is not None and not keep_output:
                    output.close()
        raise GotenbergError("Conversion service unavailable")
    finally:
        if owns_client:
            client.close()
