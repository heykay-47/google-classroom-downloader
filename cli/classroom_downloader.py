import os
import io
import json
import pathlib
import filecmp
import argparse
import sys
import time
import shutil
import subprocess
import tempfile
from typing import Dict, List, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gcr_downloader.catalog import CatalogError, list_course_files, list_courses
from gcr_downloader.files import (
    GOOGLE_EXPORTS,
    SCOPES,
    allocate_unique_name,
    conversion_kind,
    ensure_extension,
    is_video_file,
    safe_filename,
)
from gcr_downloader.models import (
    Course,
    DownloadOptions,
    DownloadReport,
    ItemResult,
)

TOKEN_FILE = "token.json"
INDEX_FILE = "download_index.json"
DEFAULT_DOWNLOAD_DIR = "downloads"

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# ---------- AUTH HELPERS ----------


def has_required_scopes(creds: Credentials) -> bool:
    # has_scopes() checks requested scopes, not a server's partial grant.
    scopes = creds.granted_scopes if creds.granted_scopes is not None else creds.scopes
    return set(SCOPES).issubset(scopes or ())


def get_credentials() -> Credentials:
    """
    Load credentials from token.json, or start OAuth flow from credentials.json.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE)
        if not has_required_scopes(creds):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                details = exc.args[1] if len(exc.args) > 1 else None
                if exc.retryable or not isinstance(details, dict) or details.get("error") != "invalid_grant":
                    raise ValueError(
                        "Could not refresh Google credentials; saved token unchanged. "
                        "Check your connection and Google service status, then retry. "
                        "If this persists, check the OAuth client configuration in credentials.json."
                    ) from None
                creds = None
            except TransportError:
                raise ValueError(
                    "Network failure during Google credential refresh; saved token unchanged. "
                    "Check your connection and retry."
                ) from None
        if not creds or not creds.valid or not has_required_scopes(creds):
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "credentials.json not found. "
                    "Download it from Google Cloud Console and place it next to this script."
                )
            print("Opening Google sign-in. Allow all requested permissions; press Ctrl+C to cancel.")
            try:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0, timeout_seconds=180, prompt="consent")
            except KeyboardInterrupt:
                raise ValueError(
                    "Google sign-in cancelled; run the command again when ready. Saved token unchanged."
                ) from None
            except Exception:
                # OAuth exceptions can contain token endpoint responses or callback URLs.
                raise ValueError(
                    "Google sign-in failed or timed out; check your connection and credentials.json, "
                    "then run the command again. Saved token unchanged."
                ) from None
            if not creds or not creds.valid or not has_required_scopes(creds):
                raise ValueError(
                    "Google sign-in did not grant all required permissions; "
                    "run the command again and allow every requested permission. Saved token unchanged."
                )
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


# ---------- UTILS ----------


def load_index() -> Dict[str, str]:
    """
    Load previously downloaded file IDs from INDEX_FILE.
    """
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "downloaded_ids" not in data:
            raise ValueError("Expected a downloaded_ids mapping or legacy list")
        downloaded_ids = data["downloaded_ids"]
        if isinstance(downloaded_ids, dict) and all(isinstance(path, str) for path in downloaded_ids.values()):
            return dict(downloaded_ids)
        if isinstance(downloaded_ids, list) and all(isinstance(file_id, (str, int)) for file_id in downloaded_ids):
            return {str(file_id): "" for file_id in downloaded_ids}
        raise ValueError("Invalid downloaded_ids entries")
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise ValueError(
            f"Invalid download index '{INDEX_FILE}': {exc}. Original left unchanged. "
            "Back up and repair it, or move it aside before restarting with an empty index."
        ) from exc


def save_index(downloaded_ids: Dict[str, str]) -> None:
    """
    Save downloaded file IDs to INDEX_FILE.
    """
    index_path = pathlib.Path(INDEX_FILE).resolve()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=index_path.parent,
            prefix=f".{index_path.name}.", suffix=".tmp", delete=False,
        ) as f:
            temp_path = pathlib.Path(f.name)
            json.dump(
                {"downloaded_ids": dict(sorted(downloaded_ids.items()))},
                f,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())
        # Close the temporary file before replacement for Windows compatibility.
        temp_path.replace(index_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def get_indexed_path(base_dir: pathlib.Path, stored_path: str) -> pathlib.Path | None:
    if not stored_path:
        return None

    base_path = base_dir.resolve()
    candidate = (base_path / stored_path).resolve()
    try:
        candidate.relative_to(base_path)
    except ValueError:
        return None
    return candidate


# ---------- CLASSROOM HELPERS ----------


# ---------- DRIVE DOWNLOAD HELPERS ----------


def download_drive_file(
    drive_service,
    file_id: str,
    dest_path: pathlib.Path,
    mime_type: str | None,
    dry_run: bool = False,
    max_retries: int = 3,
) -> bool:
    """
    Download a Drive file to dest_path with retry logic.
    Handles Google Docs / Sheets / Slides export via files.export.
    Returns True if successful, False otherwise.
    """
    if dry_run:
        print(f"[DRY RUN] Would download: {file_id} -> {dest_path}")
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(max_retries):
        temp_path = None
        try:
            if mime_type in GOOGLE_EXPORTS:
                export_mime, _ext = GOOGLE_EXPORTS[mime_type]
                request = drive_service.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
            else:
                request = drive_service.files().get_media(fileId=file_id)

            descriptor, temp_name = tempfile.mkstemp(
                dir=dest_path.parent,
                prefix=f".{dest_path.name}.",
                suffix=".part",
            )
            os.close(descriptor)
            temp_path = pathlib.Path(temp_name)

            with io.FileIO(temp_path, "wb") as file_handle:
                downloader = MediaIoBaseDownload(file_handle, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            temp_path.replace(dest_path)

            print(f"Downloaded: {dest_path}")
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                print(
                    f"Error downloading {file_id}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            else:
                print(f"Failed to download {file_id} after {max_retries} attempts: {e}")
                return False
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def get_unique_path(dest_path: pathlib.Path) -> pathlib.Path:
    """
    If dest_path already exists, append a numeric suffix to make it unique.
    e.g., report.pdf -> report_1.pdf -> report_2.pdf
    """
    used_names = {path.name for path in dest_path.parent.iterdir()} if dest_path.parent.exists() else set()
    while True:
        candidate = dest_path.with_name(allocate_unique_name(dest_path.name, used_names))
        if not candidate.exists():
            return candidate


def collapse_identical_duplicate(candidate: pathlib.Path, canonical: pathlib.Path) -> pathlib.Path:
    if candidate == canonical or not candidate.is_file() or not canonical.is_file():
        return candidate
    try:
        if filecmp.cmp(candidate, canonical, shallow=False):
            candidate.unlink()
            return canonical
    except OSError:
        pass
    return candidate


# ---------- CONVERSION HELPERS ----------


def prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")


def get_conversion_preferences() -> Dict[str, bool]:
    print("\nConversion options:")
    convert_ppt = prompt_yes_no(
        "Convert PowerPoint files (.ppt, .pptx) to PDF after download? (y/n): "
    )
    convert_docx = prompt_yes_no(
        "Convert Word documents (.doc, .docx) to PDF after download? (y/n): "
    )
    delete_originals = False
    if convert_ppt or convert_docx:
        delete_originals = prompt_yes_no(
            "Delete original files after successful conversion? (y/n): "
        )
    return {
        "convert_ppt": convert_ppt,
        "convert_docx": convert_docx,
        "delete_originals": delete_originals,
    }


def get_video_preference() -> bool:
    print("\nVideo download option:")
    return prompt_yes_no(
        "Download video files (.mp4, .mov, .avi, etc.)? (y/n): "
    )


def check_libreoffice_available() -> Tuple[bool, str]:
    for command in ("libreoffice", "soffice", "soffice.exe"):
        if shutil.which(command):
            return True, command

    common_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for path in common_paths:
        if pathlib.Path(path).exists():
            return True, path

    return False, ""


def convert_to_pdf(file_path: pathlib.Path, libreoffice_cmd: str) -> tuple[pathlib.Path | None, str]:
    pdf_path = file_path.with_suffix(".pdf")
    if pdf_path.exists():
        return None, "PDF destination already exists"
    try:
        subprocess.run(
            [libreoffice_cmd, "--headless", "--convert-to", "pdf", "--outdir", str(file_path.parent), str(file_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return None, "LibreOffice not found"
    except subprocess.CalledProcessError:
        return None, "LibreOffice conversion failed"
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return None, "Conversion did not produce a non-empty PDF"
    return pdf_path, ""


def render_report(report: DownloadReport) -> None:
    print("\nDownload summary:")
    for status, count in sorted(report.summary().items()):
        print(f"  {status}: {count}")
    for item in report.items:
        if item.status.startswith("skipped_") or item.status.endswith("_failed"):
            print(f"  {item.source_name}: {item.message}")


# ---------- CORE LOGIC ----------


def download_all_for_course(
    classroom_service,
    drive_service,
    course: Course,
    base_dir: pathlib.Path,
    downloaded_ids: Dict[str, str],
    options: DownloadOptions,
    report: DownloadReport,
    libreoffice_cmd: str = "",
    dry_run: bool = False,
) -> None:
    base_path = base_dir.resolve()
    course_dir = base_path / safe_filename(course.name)

    def record(result: ItemResult) -> None:
        report.add(result)
        if not dry_run:
            save_index(downloaded_ids)

    for course_file in list_course_files(classroom_service, course.id):
        metadata = None
        for attempt in range(3):
            try:
                metadata = drive_service.files().get(
                    fileId=course_file.id,
                    fields="name,mimeType",
                ).execute()
                break
            except Exception:
                if attempt < 2:
                    time.sleep(2**attempt)
        if metadata is None:
            record(ItemResult(course.name, course_file.title_hint, "download_failed", message="Failed to fetch file metadata"))
            continue

        source_name = ensure_extension(
            safe_filename(metadata.get("name") or course_file.title_hint),
            metadata.get("mimeType"),
        )
        if not options.include_videos and is_video_file(source_name, metadata.get("mimeType")):
            record(ItemResult(course.name, source_name, "skipped_video", message="Video excluded"))
            continue

        indexed_path = get_indexed_path(base_path, downloaded_ids.get(course_file.id, ""))
        if indexed_path is not None and indexed_path.exists():
            if not dry_run:
                indexed_path = collapse_identical_duplicate(
                    indexed_path,
                    course_dir / source_name,
                )
            relative = indexed_path.relative_to(base_path).as_posix()
            if not dry_run:
                downloaded_ids[course_file.id] = relative
            if (
                dry_run
                or conversion_kind(source_name, options) is None
                or indexed_path.suffix.lower() == ".pdf"
            ):
                record(ItemResult(course.name, source_name, "skipped_existing", (relative,), "File already exists"))
                continue
            destination = indexed_path
            relative_destination = relative
        else:
            if not dry_run:
                downloaded_ids.pop(course_file.id, None)
            destination = get_unique_path(course_dir / source_name)
            relative_destination = destination.relative_to(base_path).as_posix()
            if dry_run:
                download_drive_file(
                    drive_service,
                    course_file.id,
                    destination,
                    metadata.get("mimeType"),
                    dry_run=True,
                )
                record(ItemResult(course.name, source_name, "dry_run", (relative_destination,)))
                continue

            if not download_drive_file(
                drive_service,
                course_file.id,
                destination,
                metadata.get("mimeType"),
            ):
                record(ItemResult(course.name, source_name, "download_failed", message="Download failed after three attempts"))
                continue
            destination = collapse_identical_duplicate(
                destination,
                course_dir / source_name,
            )
            relative_destination = destination.relative_to(base_path).as_posix()

        downloaded_ids[course_file.id] = relative_destination
        if conversion_kind(source_name, options) is None:
            record(ItemResult(course.name, source_name, "downloaded", (relative_destination,)))
            continue

        existing_pdf = destination.with_suffix(".pdf")
        if existing_pdf.exists() and existing_pdf.stat().st_size > 0:
            pdf_path, error = existing_pdf, ""
        else:
            pdf_path, error = convert_to_pdf(destination, libreoffice_cmd)
        if pdf_path is None:
            record(ItemResult(course.name, source_name, "conversion_failed", (relative_destination,), error))
            continue

        relative_pdf = pdf_path.relative_to(base_path).as_posix()
        outputs = (relative_destination, relative_pdf)
        if not options.keep_originals:
            try:
                destination.unlink()
            except OSError:
                record(ItemResult(course.name, source_name, "conversion_failed", outputs, "Converted PDF created but original could not be removed"))
                continue
            downloaded_ids[course_file.id] = relative_pdf
            outputs = (relative_pdf,)
        record(ItemResult(course.name, source_name, "converted", outputs))


# ---------- MAIN / CLI ----------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Google Classroom auto-downloader (Classroom + Drive APIs)."
    )
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help=f"Base directory where files will be saved (default: {DEFAULT_DOWNLOAD_DIR})",
    )
    parser.add_argument(
        "--course-name-contains",
        default=None,
        help="If set, only download from courses whose name contains this substring (case-insensitive).",
    )
    parser.add_argument(
        "--course-state",
        choices=("active", "archived", "all"),
        default="all",
        help="Filter courses by state (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded, but do not actually download.",
    )
    return parser.parse_args()


def select_courses(courses: List[Course]) -> List[Course]:
    """
    Display list of courses and let user select which ones to download from.
    """
    if not courses:
        return []

    print("\n" + "=" * 50)
    print("Available Courses:")
    print("=" * 50)

    for idx, course in enumerate(courses, 1):
        print(f"  {idx}. {course.name}")

    print("=" * 50)
    print("\nSelection options:")
    print("  - Enter course numbers separated by commas (e.g., '1,3,5')")
    print("  - Enter a range (e.g., '1-4')")
    print("  - Type 'all' to select all courses")
    print("  - Type 'cancel' to exit without downloading")
    print()

    while True:
        selection = input("Select courses to download from: ").strip().lower()

        if selection == "cancel":
            return []

        if selection == "all":
            return courses

        selected_indices = set()

        # Parse comma-separated values and ranges
        parts = [p.strip() for p in selection.split(",")]

        for part in parts:
            if "-" in part:
                # Handle range (e.g., "1-4")
                try:
                    start, end = part.split("-", 1)
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())
                    if 1 <= start_idx <= len(courses) and 1 <= end_idx <= len(courses):
                        selected_indices.update(range(start_idx, end_idx + 1))
                    else:
                        print(f"  Invalid range: {part} (valid: 1-{len(courses)})")
                        break
                except ValueError:
                    print(f"  Invalid input: {part}")
                    break
            else:
                # Handle single number
                try:
                    idx = int(part)
                    if 1 <= idx <= len(courses):
                        selected_indices.add(idx)
                    else:
                        print(
                            f"  Invalid course number: {idx} (valid: 1-{len(courses)})"
                        )
                        break
                except ValueError:
                    print(f"  Invalid input: {part}")
                    break
        else:
            # All parts parsed successfully
            if selected_indices:
                selected_courses = [courses[i - 1] for i in sorted(selected_indices)]
                print(f"\nSelected {len(selected_courses)} course(s):")
                for c in selected_courses:
                    print(f"  - {c.name}")
                confirm = input("\nProceed with download? (y/n): ").strip().lower()
                if confirm in ("y", "yes"):
                    return selected_courses
                else:
                    print("Selection cancelled. Please choose again.")
            else:
                print("  No valid courses selected. Please try again.")


def main() -> int:
    args = parse_args()
    downloaded_ids = None
    report = DownloadReport()
    try:
        print("Loading download index...")
        downloaded_ids = load_index()
        return run_downloads(args, downloaded_ids, report)
    except KeyboardInterrupt:
        print("\nDownload interrupted. Showing partial results.")
        if downloaded_ids is not None and not args.dry_run:
            try:
                save_index(downloaded_ids)
            except OSError as exc:
                print(f"Could not checkpoint index: {exc}. Previous checkpoint retained.")
        render_report(report)
        return 130
    except (CatalogError, OSError, ValueError) as exc:
        print(f"Download stopped: {exc}")
        render_report(report)
        return 1


def run_downloads(args, downloaded_ids: Dict[str, str], report: DownloadReport) -> int:
    base_dir = pathlib.Path(args.base_dir)

    print("Authenticating with Google...")
    creds = get_credentials()
    classroom_service = build("classroom", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    print("Fetching courses...")
    courses = list_courses(
        classroom_service,
        state=args.course_state,
        name_contains=args.course_name_contains,
    )

    if not courses:
        print("No courses found that match your filter.")
        return 0

    print(f"Found {len(courses)} course(s).")

    # Let user select which courses to download
    selected_courses = select_courses(courses)

    if not selected_courses:
        print("No courses selected. Exiting.")
        return 0

    conversion_prefs = get_conversion_preferences()
    libreoffice_cmd = ""
    if conversion_prefs["convert_ppt"] or conversion_prefs["convert_docx"]:
        available, libreoffice_cmd = check_libreoffice_available()
        if not available:
            print("LibreOffice CLI not found. Conversion will be skipped.")
            conversion_prefs["convert_ppt"] = False
            conversion_prefs["convert_docx"] = False
            conversion_prefs["delete_originals"] = False

    options = DownloadOptions(
        include_videos=get_video_preference(),
        convert_word=conversion_prefs["convert_docx"],
        convert_powerpoint=conversion_prefs["convert_ppt"],
        keep_originals=not conversion_prefs["delete_originals"],
    )
    for course in selected_courses:
        download_all_for_course(
            classroom_service,
            drive_service,
            course,
            base_dir,
            downloaded_ids,
            options,
            report,
            libreoffice_cmd=libreoffice_cmd,
            dry_run=args.dry_run,
        )
    render_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
