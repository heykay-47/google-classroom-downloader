import os
import io
import json
import pathlib
import argparse
import sys
import time
import shutil
import subprocess
import tempfile
from typing import Dict, Set, List, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gcr_downloader.catalog import CatalogError, list_course_files, list_courses
from gcr_downloader.files import (
    GOOGLE_EXPORTS,
    SCOPES,
    ensure_extension,
    is_video_file,
    safe_filename,
    validate_course_id,
    validate_file_id,
)
from gcr_downloader.models import Course, CourseFile

TOKEN_FILE = "token.json"
INDEX_FILE = "download_index.json"
DEFAULT_DOWNLOAD_DIR = "downloads"

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# ---------- AUTH HELPERS ----------


def get_credentials() -> Credentials:
    """
    Load credentials from token.json, or start OAuth flow from credentials.json.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "credentials.json not found. "
                    "Download it from Google Cloud Console and place it next to this script."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


# ---------- UTILS ----------


def load_index() -> Dict[str, str]:
    """
    Load previously downloaded file IDs from INDEX_FILE.
    """
    if not os.path.exists(INDEX_FILE):
        return {}
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        downloaded_ids = data.get("downloaded_ids", {})
        if isinstance(downloaded_ids, dict):
            return {str(file_id): str(path) for file_id, path in downloaded_ids.items()}
        return {str(file_id): "" for file_id in downloaded_ids}
    except Exception:
        # If corrupted, ignore
        return {}


def save_index(downloaded_ids: Dict[str, str]) -> None:
    """
    Save downloaded file IDs to INDEX_FILE.
    """
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"downloaded_ids": dict(sorted(downloaded_ids.items()))},
            f,
            indent=2,
        )


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
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print(f"[DRY RUN] Would download: {file_id} -> {dest_path}")
        return True

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
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                print(
                    f"Error downloading {file_id}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            else:
                print(f"Failed to download {file_id} after {max_retries} attempts: {e}")
                return False


def get_unique_path(dest_path: pathlib.Path) -> pathlib.Path:
    """
    If dest_path already exists, append a numeric suffix to make it unique.
    e.g., report.pdf -> report_1.pdf -> report_2.pdf
    """
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    counter = 1

    while True:
        new_name = f"{stem}_{counter}{suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


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


def convert_to_pdf(
    file_path: pathlib.Path,
    libreoffice_cmd: str,
    delete_original: bool = False,
) -> bool:
    pdf_path = file_path.with_suffix(".pdf")
    if pdf_path.exists():
        print(f"PDF already exists, skipping conversion: {pdf_path}")
        return True

    try:
        subprocess.run(
            [
                libreoffice_cmd,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(file_path.parent),
                str(file_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print("LibreOffice not found. Skipping conversion.")
        return False
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() or str(exc)
        print(f"Failed to convert {file_path} to PDF: {error_msg}")
        return False

    if not pdf_path.exists():
        print(f"Conversion did not produce PDF for: {file_path}")
        return False

    print(f"Converted to PDF: {pdf_path}")

    if delete_original:
        try:
            file_path.unlink()
            print(f"Deleted original: {file_path}")
        except OSError as exc:
            print(f"Failed to delete original {file_path}: {exc}")

    return True


def convert_downloaded_files(
    base_dir: pathlib.Path,
    convert_ppt: bool,
    convert_docx: bool,
    delete_originals: bool,
    libreoffice_cmd: str,
    downloaded_ids: Dict[str, str],
) -> None:
    extensions: Set[str] = set()
    if convert_ppt:
        extensions.update({".ppt", ".pptx"})
    if convert_docx:
        extensions.update({".doc", ".docx"})

    if not extensions:
        return

    print("\nConverting documents to PDF...")
    files = [
        path
        for path in base_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ]

    if not files:
        print("No matching files found for conversion.")
        return

    for file_path in files:
        converted = convert_to_pdf(
            file_path,
            libreoffice_cmd,
            delete_original=delete_originals,
        )
        pdf_path = file_path.with_suffix(".pdf")
        if not converted or file_path.exists() or not pdf_path.exists():
            continue

        source_path = file_path.resolve()
        for file_id, stored_path in downloaded_ids.items():
            if get_indexed_path(base_dir, stored_path) == source_path:
                downloaded_ids[file_id] = str(pdf_path.resolve().relative_to(base_dir.resolve()))


# ---------- CORE LOGIC ----------


def download_all_for_course(
    classroom_service,
    drive_service,
    course: Course,
    base_dir: pathlib.Path,
    downloaded_ids: Dict[str, str],
    dry_run: bool = False,
    download_videos: bool = True,
) -> None:
    course_id = course.id

    # Validate course ID before processing
    if not validate_course_id(course_id):
        print(f"Warning: Invalid course ID format: {course_id}. Skipping.")
        return

    base_path = base_dir.resolve()
    course_name = course.name
    course_dir = base_path / safe_filename(course_name)

    print(f"\n=== Course: {course_name} (id={course_id}) ===")

    files = list_course_files(classroom_service, course_id)
    print(f"Found {len(files)} attached Drive files in this course.")

    for course_file in files:
        file_id = course_file.id
        name_hint = course_file.title_hint
        # Validate file ID before processing
        if not validate_file_id(file_id):
            print(f"Warning: Invalid file ID format: {file_id}. Skipping.")
            continue

        # Get metadata from Drive
        try:
            meta = (
                drive_service.files()
                .get(
                    fileId=file_id,
                    fields="name,mimeType",
                )
                .execute()
            )
        except Exception as e:
            print(f"Error fetching metadata for file {file_id}: {e}")
            continue

        fname = meta.get("name") or name_hint or file_id
        mime_type = meta.get("mimeType")

        fname = safe_filename(fname)
        fname = ensure_extension(fname, mime_type)

        if not download_videos and is_video_file(fname, mime_type):
            print(f"Skipping video file: {fname}")
            continue

        dest_path = course_dir / fname
        if file_id in downloaded_ids:
            indexed_path = get_indexed_path(base_path, downloaded_ids[file_id])
            if indexed_path is not None and indexed_path.exists():
                print(f"File already exists locally, skipping: {indexed_path}")
                downloaded_ids[file_id] = str(indexed_path.relative_to(base_path))
                continue
            downloaded_ids.pop(file_id)

        # Handle duplicate filenames from different files
        dest_path = get_unique_path(dest_path)

        success = download_drive_file(
            drive_service, file_id, dest_path, mime_type, dry_run=dry_run
        )
        if success or dry_run:
            downloaded_ids[file_id] = str(dest_path.relative_to(base_path))


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
    base_dir = pathlib.Path(args.base_dir)

    print("Authenticating with Google...")
    creds = get_credentials()
    classroom_service = build("classroom", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    print("Loading download index...")
    downloaded_ids = load_index()

    print("Fetching courses...")
    try:
        courses = list_courses(
            classroom_service,
            state=args.course_state,
            name_contains=args.course_name_contains,
        )
    except CatalogError as exc:
        print(str(exc))
        return 1

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
    download_videos = get_video_preference()
    libreoffice_cmd = ""
    if conversion_prefs["convert_ppt"] or conversion_prefs["convert_docx"]:
        available, libreoffice_cmd = check_libreoffice_available()
        if not available:
            print("LibreOffice CLI not found. Conversion will be skipped.")
            conversion_prefs["convert_ppt"] = False
            conversion_prefs["convert_docx"] = False
            conversion_prefs["delete_originals"] = False

    for c in selected_courses:
        download_all_for_course(
            classroom_service,
            drive_service,
            c,
            base_dir,
            downloaded_ids,
            dry_run=args.dry_run,
            download_videos=download_videos,
        )

    if not args.dry_run and (
        conversion_prefs["convert_ppt"] or conversion_prefs["convert_docx"]
    ):
        convert_downloaded_files(
            base_dir=base_dir,
            convert_ppt=conversion_prefs["convert_ppt"],
            convert_docx=conversion_prefs["convert_docx"],
            delete_originals=conversion_prefs["delete_originals"],
            libreoffice_cmd=libreoffice_cmd,
            downloaded_ids=downloaded_ids,
        )

    if not args.dry_run:
        print("\nSaving download index...")
        save_index(downloaded_ids)
        print("Done. All new files downloaded.")
    else:
        print("\nDry run completed. No files were actually downloaded.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
