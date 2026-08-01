# App and CLI Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give web app and CLI one shared Google Classroom/Drive policy while preserving web ZIP delivery, CLI local QoL, and platform-specific conversion adapters.

**Architecture:** New `gcr_downloader/` package owns typed catalog records, filtering, export policy, validation, naming, video classification, options, and result reports. FastAPI and CLI remain adapters: web prepares spooled artifacts, converts through localhost Gotenberg, and streams ZIP; CLI writes atomically, tracks local history, and converts through LibreOffice.

**Tech Stack:** Python 3.12, `unittest`, FastAPI 0.128.1, Google API Python Client 2.189.0, Requests 2.34.2, zipstream-new 1.1.8, Docker Compose, Cloud Run multi-container services, Gotenberg 8.34.0 LibreOffice image.

## Global Constraints

- Preserve entry points `uvicorn app.main:app` and `python cli/classroom_downloader.py`.
- Fetch `ACTIVE` and `ARCHIVED` courses; default state filter is `all`.
- Include videos by default; explicit skip control only.
- Disable Word/PowerPoint conversion by default; keep originals by default.
- Conversion applies only to `.doc`, `.docx`, `.ppt`, and `.pptx`.
- Use three total Drive/Gotenberg attempts with `1s` then `2s` delays.
- Web must verify every submitted file ID belongs to submitted course.
- Web uses no persistent browser, database, or server download history.
- CLI retains `--base-dir`, `--course-name-contains`, `--dry-run`, local index recovery, atomic writes, and course-level selection.
- Web uses `8 MiB` `SpooledTemporaryFile` threshold and always emits `_download_report.json` schema version `1`.
- Conversion failure always preserves original, including replace mode.
- Gotenberg image is `gotenberg/gotenberg:8.34.0-libreoffice`, private on port `3000` in same Cloud Run instance.
- Cloud Run baseline is web `1 CPU / 2 GiB`, Gotenberg `1 CPU / 1 GiB`, concurrency `1`, request timeout `900s`.
- Gotenberg env is `LIBREOFFICE_AUTO_START=true`, `LIBREOFFICE_MAX_QUEUE_SIZE=1`, `LIBREOFFICE_START_TIMEOUT=60s`, `API_TIMEOUT=120s`.
- Never expose OAuth tokens, credentials, stack traces, or raw Gotenberg error bodies in report.
- Use containers for build, lint, unit, and integration verification; install no host system packages.

---

## File Structure

### Shared Package

- Create `gcr_downloader/__init__.py`: package exports only.
- Create `gcr_downloader/models.py`: `Course`, `CourseFile`, `DownloadOptions`, `ItemResult`, `DownloadReport`.
- Create `gcr_downloader/files.py`: scopes, export map, validation, filename, video, conversion, unique archive-name policy.
- Create `gcr_downloader/catalog.py`: Google Classroom pagination, filtering, deduplication, course lookup, selection ownership.

### Web Adapter

- Modify `app/main.py`: route orchestration and HTTP error mapping.
- Modify `app/drive.py`: Drive metadata and atomic spooled transfer only.
- Create `app/gotenberg.py`: synchronous Gotenberg health/conversion client.
- Create `app/downloads.py`: web item preparation and report outcomes.
- Modify `app/zipstreamer.py`: `ArchiveEntry`, ZIP64 streaming, final report, cleanup.
- Modify `app/templates/courses.html`: state, video, conversion, and replace controls.
- Delete `app/classroom.py`: catalog logic moves to shared package.
- Delete `app/classroom_downloader.py`: unused duplicate.

### CLI Adapter

- Modify `cli/classroom_downloader.py`: shared imports, state filter, typed records, immediate conversion outcomes, report renderer.
- Delete `cli/constants.py`: shared constants move to package; CLI path constants remain in script.

### Tests And Deployment

- Create `tests/test_core_models.py`.
- Create `tests/test_core_files.py`.
- Create `scripts/run-python-in-container.sh`: repeatable container-first Python runner.
- Create `tests/test_core_catalog.py`.
- Modify `tests/test_cli.py`.
- Create `tests/test_web_adapters.py`.
- Modify `tests/test_web_app.py`.
- Create `tests/test_parity_contract.py`.
- Modify `tests/test_support.py`.
- Create `tests/test_web_template.py`.
- Create `tests/test_deploy_config.py`.
- Create `tests/generate_office_fixtures.py`.
- Create generated `tests/fixtures/sample.docx` and `tests/fixtures/sample.pptx`.
- Create `tests/test_gotenberg_integration.py`.
- Modify `requirements.txt`.
- Create `compose.yaml`.
- Create `deploy/cloud-run-service.yaml`.
- Create `deploy/render_cloud_run.py`.
- Modify `.gitignore`: ignore rendered project-specific Cloud Run YAML.
- Modify `README.md`.
- Replace `cli/README.md` with canonical-root pointer and CLI quick start.

---

### Task 1: Shared Models And File Policy

**Files:**
- Create: `gcr_downloader/__init__.py`
- Create: `gcr_downloader/models.py`
- Create: `gcr_downloader/files.py`
- Create: `tests/test_core_models.py`
- Create: `tests/test_core_files.py`
- Create: `scripts/run-python-in-container.sh`

**Interfaces:**
- Produces: `Course(id: str, name: str, state: str)`.
- Produces: `CourseFile(id: str, title_hint: str)`.
- Produces: `DownloadOptions(include_videos=True, convert_word=False, convert_powerpoint=False, keep_originals=True)`.
- Produces: `ItemResult(course_name, source_name, status, output_paths=(), message="")`.
- Produces: `DownloadReport.add()`, `DownloadReport.summary()`, `DownloadReport.to_dict()`.
- Produces: `SCOPES`, `GOOGLE_EXPORTS`, `safe_filename()`, `validate_course_id()`, `validate_file_id()`, `ensure_extension()`, `is_video_file()`, `conversion_kind()`, `allocate_unique_name()`.

- [ ] **Step 1: Write failing model tests**

```python
# tests/test_core_models.py
import unittest

from gcr_downloader.models import DownloadOptions, DownloadReport, ItemResult


class DownloadModelTests(unittest.TestCase):
    def test_download_option_defaults_are_non_destructive(self):
        self.assertEqual(
            DownloadOptions(),
            DownloadOptions(
                include_videos=True,
                convert_word=False,
                convert_powerpoint=False,
                keep_originals=True,
            ),
        )

    def test_report_serializes_schema_and_status_counts(self):
        report = DownloadReport()
        report.add(ItemResult("Course", "notes.docx", "downloaded", ("Course/notes.docx",)))
        report.add(ItemResult("Course", "lecture.mp4", "skipped_video", message="Video excluded"))

        self.assertEqual(report.summary(), {"downloaded": 1, "skipped_video": 1})
        payload = report.to_dict()
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["items"][0]["output_paths"], ["Course/notes.docx"])
        self.assertNotIn("traceback", str(payload).lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write failing file-policy tests**

```python
# tests/test_core_files.py
import unittest

from gcr_downloader.files import (
    GOOGLE_EXPORTS,
    allocate_unique_name,
    conversion_kind,
    ensure_extension,
    is_video_file,
    safe_filename,
    validate_course_id,
    validate_file_id,
)
from gcr_downloader.models import DownloadOptions


class FilePolicyTests(unittest.TestCase):
    def test_filename_and_id_safety(self):
        self.assertEqual(safe_filename("../week/notes?.pdf"), "week_notes_.pdf")
        self.assertEqual(safe_filename("..."), "file")
        self.assertTrue(validate_course_id("course-1"))
        self.assertTrue(validate_file_id("drive_file-1"))
        self.assertFalse(validate_file_id("../secret"))

    def test_workspace_exports_have_expected_extensions(self):
        self.assertEqual(
            GOOGLE_EXPORTS["application/vnd.google-apps.presentation"][1],
            ".pptx",
        )
        self.assertEqual(
            ensure_extension("deck", "application/vnd.google-apps.presentation"),
            "deck.pptx",
        )

    def test_video_and_conversion_policy(self):
        self.assertTrue(is_video_file("lecture.bin", "video/mp4"))
        self.assertFalse(is_video_file("notes.txt", None))
        options = DownloadOptions(convert_word=True, convert_powerpoint=True)
        self.assertEqual(conversion_kind("notes.docx", options), "word")
        self.assertEqual(conversion_kind("deck.pptx", options), "powerpoint")
        self.assertIsNone(conversion_kind("sheet.xlsx", options))

    def test_duplicate_names_are_stable(self):
        used = {"Course/report.pdf", "Course/report_1.pdf"}
        self.assertEqual(
            allocate_unique_name("Course/report.pdf", used),
            "Course/report_2.pdf",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Add container-first Python runner**

```sh
#!/bin/sh
set -eu

image="classroom-downloader:test"
docker build -t "$image" .
exec docker run --rm \
  -e PYTHONPATH=/workspace/tests:/workspace \
  -v "$(pwd):/workspace" \
  -w /workspace \
  "$image" python "$@"
```

Run: `chmod +x scripts/run-python-in-container.sh`

- [ ] **Step 4: Run tests and verify missing-package failure**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_core_models tests.test_core_files -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'gcr_downloader'`.

- [ ] **Step 5: Implement shared models**

```python
# gcr_downloader/models.py
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

ItemStatus = Literal[
    "downloaded",
    "converted",
    "skipped_video",
    "skipped_existing",
    "dry_run",
    "download_failed",
    "conversion_failed",
]


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    state: str


@dataclass(frozen=True)
class CourseFile:
    id: str
    title_hint: str


@dataclass(frozen=True)
class DownloadOptions:
    include_videos: bool = True
    convert_word: bool = False
    convert_powerpoint: bool = False
    keep_originals: bool = True


@dataclass(frozen=True)
class ItemResult:
    course_name: str
    source_name: str
    status: ItemStatus
    output_paths: tuple[str, ...] = ()
    message: str = ""


@dataclass
class DownloadReport:
    items: list[ItemResult] = field(default_factory=list)

    def add(self, result: ItemResult) -> None:
        self.items.append(result)

    def summary(self) -> dict[str, int]:
        return dict(Counter(item.status for item in self.items))

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "summary": self.summary(),
            "items": [
                {
                    "course_name": item.course_name,
                    "source_name": item.source_name,
                    "status": item.status,
                    "output_paths": list(item.output_paths),
                    "message": item.message,
                }
                for item in self.items
            ],
        }
```

- [ ] **Step 6: Implement shared file policy**

Move exact OAuth scopes, Workspace exports, and video sets from `cli/constants.py` into `gcr_downloader/files.py`. Implement these signatures:

```python
import pathlib
import re

from gcr_downloader.models import DownloadOptions

RESOURCE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
WORD_EXTENSIONS = {".doc", ".docx"}
POWERPOINT_EXTENSIONS = {".ppt", ".pptx"}


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
```

Define `SCOPES`, `GOOGLE_EXPORTS`, `VIDEO_EXTENSIONS`, and `VIDEO_MIME_PREFIXES` above these functions using exact values from `cli/constants.py`.

- [ ] **Step 7: Run shared tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_core_models tests.test_core_files -v`

Expected: PASS, 6 tests.

- [ ] **Step 8: Commit shared policy**

```bash
git add gcr_downloader scripts/run-python-in-container.sh tests/test_core_models.py tests/test_core_files.py docs/superpowers/plans/2026-08-01-app-cli-feature-parity.md docs/superpowers/specs/2026-08-01-app-cli-feature-parity-design.md
git commit -m "feat(core): add shared download policy"
```

### Task 2: Shared Classroom Catalog

**Files:**
- Create: `gcr_downloader/catalog.py`
- Create: `tests/test_core_catalog.py`

**Interfaces:**
- Consumes: `Course`, `CourseFile`, `validate_course_id()`, `validate_file_id()` from Task 1.
- Produces: `CatalogError`.
- Produces: `list_courses(classroom, state="all", name_contains=None) -> list[Course]`.
- Produces: `get_course(classroom, course_id) -> Course`.
- Produces: `list_course_files(classroom, course_id) -> list[CourseFile]`.
- Produces: `select_course_files(available, selected_ids) -> list[CourseFile]`.

- [ ] **Step 1: Write failing catalog tests**

```python
# tests/test_core_catalog.py
import unittest
from unittest import mock

from gcr_downloader.catalog import (
    list_course_files,
    list_courses,
    select_course_files,
)


def response(payload):
    request = mock.Mock()
    request.execute.return_value = payload
    return request


class CatalogTests(unittest.TestCase):
    def test_courses_paginate_and_filter_archived(self):
        classroom = mock.Mock()
        resource = classroom.courses.return_value
        resource.list.side_effect = [
            response({"courses": [{"id": "1", "name": "Active", "courseState": "ACTIVE"}], "nextPageToken": "next"}),
            response({"courses": [{"id": "2", "name": "Archive", "courseState": "ARCHIVED"}]}),
        ]

        courses = list_courses(classroom, state="archived")

        self.assertEqual([course.id for course in courses], ["2"])
        first_call = resource.list.call_args_list[0].kwargs
        self.assertEqual(first_call["courseStates"], ["ACTIVE", "ARCHIVED"])

    def test_course_files_deduplicate_in_first_seen_order(self):
        classroom = mock.Mock()
        courses = classroom.courses.return_value
        coursework = courses.courseWork.return_value
        materials = courses.courseWorkMaterials.return_value
        coursework.list.return_value = response({
            "courseWork": [{"title": "Week 1", "materials": [{"driveFile": {"driveFile": {"id": "a", "title": "A"}}}]}]
        })
        materials.list.return_value = response({
            "courseWorkMaterial": [{"title": "Files", "materials": [
                {"driveFile": {"driveFile": {"id": "a", "title": "A duplicate"}}},
                {"driveFile": {"driveFile": {"id": "b", "title": "B"}}},
            ]}]
        })

        files = list_course_files(classroom, "course-1")

        self.assertEqual([(item.id, item.title_hint) for item in files], [("a", "A"), ("b", "B")])

    def test_selection_rejects_file_not_in_course(self):
        available = list_course_files_from_pairs([("a", "A"), ("b", "B")])
        with self.assertRaisesRegex(ValueError, "not attached"):
            select_course_files(available, ["a", "forged"])


def list_course_files_from_pairs(pairs):
    from gcr_downloader.models import CourseFile
    return [CourseFile(file_id, title) for file_id, title in pairs]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run catalog tests and verify failure**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_core_catalog -v`

Expected: FAIL because `gcr_downloader.catalog` does not exist.

- [ ] **Step 3: Implement catalog functions**

```python
# gcr_downloader/catalog.py public surface
from gcr_downloader.files import validate_course_id, validate_file_id
from gcr_downloader.models import Course, CourseFile


class CatalogError(RuntimeError):
    """Google Classroom catalog operation failed."""


def list_courses(classroom, state: str = "all", name_contains: str | None = None) -> list[Course]:
    normalized_state = state.lower()
    if normalized_state not in {"active", "archived", "all"}:
        raise ValueError("Invalid course state")
    courses: list[Course] = []
    page_token = None
    try:
        while True:
            payload = classroom.courses().list(
                pageToken=page_token,
                courseStates=["ACTIVE", "ARCHIVED"],
            ).execute()
            for item in payload.get("courses", []):
                course = Course(
                    id=str(item.get("id", "")),
                    name=item.get("name") or "Unnamed Course",
                    state=(item.get("courseState") or "UNKNOWN").upper(),
                )
                state_matches = normalized_state == "all" or course.state.lower() == normalized_state
                name_matches = not name_contains or name_contains.lower() in course.name.lower()
                if validate_course_id(course.id) and state_matches and name_matches:
                    courses.append(course)
            page_token = payload.get("nextPageToken")
            if not page_token:
                return courses
    except Exception as exc:
        raise CatalogError("Failed to fetch courses") from exc


def get_course(classroom, course_id: str) -> Course:
    if not validate_course_id(course_id):
        raise ValueError("Invalid course ID")
    try:
        item = classroom.courses().get(
            courseId=course_id,
            fields="id,name,courseState",
        ).execute()
    except Exception as exc:
        raise CatalogError("Failed to fetch course") from exc
    return Course(
        id=str(item.get("id", course_id)),
        name=item.get("name") or "Unnamed Course",
        state=(item.get("courseState") or "UNKNOWN").upper(),
    )


def list_course_files(classroom, course_id: str) -> list[CourseFile]:
    if not validate_course_id(course_id):
        raise ValueError("Invalid course ID")
    files: list[CourseFile] = []
    seen: set[str] = set()

    def collect(payload: dict, key: str, fallback: str) -> None:
        for post in payload.get(key, []):
            title = post.get("title", fallback)
            for material in post.get("materials", []):
                drive_file = material.get("driveFile", {}).get("driveFile", {})
                file_id = drive_file.get("id")
                if validate_file_id(file_id) and file_id not in seen:
                    seen.add(file_id)
                    files.append(CourseFile(file_id, drive_file.get("title") or title))

    try:
        page_token = None
        while True:
            payload = classroom.courses().courseWork().list(
                courseId=course_id,
                pageToken=page_token,
            ).execute()
            collect(payload, "courseWork", "Assignment")
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        page_token = None
        while True:
            payload = classroom.courses().courseWorkMaterials().list(
                courseId=course_id,
                pageToken=page_token,
            ).execute()
            collect(payload, "courseWorkMaterial", "Material")
            page_token = payload.get("nextPageToken")
            if not page_token:
                return files
    except Exception as exc:
        raise CatalogError("Failed to fetch course files") from exc


def select_course_files(available: list[CourseFile], selected_ids: list[str]) -> list[CourseFile]:
    if not selected_ids:
        raise ValueError("Select at least one file")
    by_id = {item.id: item for item in available}
    selected: list[CourseFile] = []
    seen: set[str] = set()
    for file_id in selected_ids:
        if not validate_file_id(file_id) or file_id not in by_id:
            raise ValueError("Selected file is not attached to course")
        if file_id not in seen:
            seen.add(file_id)
            selected.append(by_id[file_id])
    return selected
```

- [ ] **Step 4: Run catalog and shared tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_core_catalog tests.test_core_models tests.test_core_files -v`

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit catalog**

```bash
git add gcr_downloader/catalog.py tests/test_core_catalog.py
git commit -m "feat(core): add Classroom catalog"
```

### Task 3: Migrate CLI To Shared Catalog And Policy

**Files:**
- Modify: `cli/classroom_downloader.py:1-335,489-741`
- Delete: `cli/constants.py`
- Modify: `tests/test_cli.py:1-233`

**Interfaces:**
- Consumes: all Task 1 file-policy functions and Task 2 `list_courses()`, `list_course_files()`.
- Produces: CLI argument `--course-state {active,archived,all}` defaulting to `all`.
- Preserves: `download_drive_file()`, index functions, selection syntax, atomic destination replacement.

- [ ] **Step 1: Update CLI tests to use shared records and assert state argument**

Add these tests; import `types`, `CatalogError`, `Course`, and `CourseFile`:

```python
def test_course_state_defaults_to_all(self):
    with mock.patch.object(sys, "argv", ["classroom_downloader.py"]):
        args = downloader.parse_args()
    self.assertEqual(args.course_state, "all")

def test_course_state_accepts_archived(self):
    with mock.patch.object(
        sys,
        "argv",
        ["classroom_downloader.py", "--course-state", "archived"],
    ):
        args = downloader.parse_args()
    self.assertEqual(args.course_state, "archived")

def test_course_selection_accepts_shared_course_records(self):
    courses = [Course("1", "Active", "ACTIVE"), Course("2", "Archive", "ARCHIVED")]
    with mock.patch("builtins.input", side_effect=["2", "y"]):
        selected = downloader.select_courses(courses)
    self.assertEqual(selected, [courses[1]])

def test_main_returns_nonzero_when_catalog_fails(self):
    args = types.SimpleNamespace(
        base_dir="downloads",
        course_name_contains=None,
        course_state="all",
        dry_run=False,
    )
    with mock.patch.object(downloader, "parse_args", return_value=args), \
         mock.patch.object(downloader, "get_credentials", return_value=object()), \
         mock.patch.object(downloader, "build", side_effect=[object(), object()]), \
         mock.patch.object(downloader, "load_index", return_value={}), \
         mock.patch.object(downloader, "list_courses", side_effect=CatalogError("Failed to fetch courses")):
        self.assertEqual(downloader.main(), 1)
```

Change existing `download_all_for_course()` fixtures from course dictionaries and `(id, title)` tuples to `Course` and `CourseFile`.

- [ ] **Step 2: Run CLI tests and verify type/argument failures**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_cli -v`

Expected: FAIL because `--course-state` and dataclass access are not implemented.

- [ ] **Step 3: Add script-path bootstrap and shared imports**

At top of `cli/classroom_downloader.py`, before shared imports:

```python
import sys

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
```

Delete local `safe_filename()`, ID validators, course listing functions, video detection, extension mapping, and imports from `constants`.

- [ ] **Step 4: Adapt CLI course flow**

Add parser argument:

```python
parser.add_argument(
    "--course-state",
    choices=("active", "archived", "all"),
    default="all",
    help="Filter courses by state (default: all).",
)
```

Use `course.id`, `course.name`, `course.state`, `course_file.id`, and `course_file.title_hint`. Replace main catalog call with:

```python
try:
    courses = list_courses(
        classroom_service,
        state=args.course_state,
        name_contains=args.course_name_contains,
    )
except CatalogError as exc:
    print(str(exc))
    return 1
```

Change signature to `def main() -> int`, convert successful bare returns to `return 0`, end successful run with `return 0`, and invoke it with `raise SystemExit(main())`. Keep existing auth, index, selection, prompt, and download flow. Use `GOOGLE_EXPORTS` in `download_drive_file()` and preserve exact three-attempt `1s`, `2s` behavior.

- [ ] **Step 5: Delete old constants module and run tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_cli tests.test_core_catalog tests.test_core_files -v`

Expected: PASS. Existing atomic, index, filename, duplicate, and conversion regression tests remain green after import changes.

- [ ] **Step 6: Verify direct CLI entry point imports shared package**

Run: `scripts/run-python-in-container.sh cli/classroom_downloader.py --help`

Expected: exit `0`; output includes `--course-state {active,archived,all}` without starting OAuth.

- [ ] **Step 7: Commit CLI migration**

```bash
git add cli/classroom_downloader.py cli/constants.py tests/test_cli.py
git commit -m "refactor(cli): use shared catalog policy"
```

### Task 4: CLI Conversion Outcomes And Report

**Files:**
- Modify: `cli/classroom_downloader.py:336-560,670-737`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `DownloadOptions`, `DownloadReport`, `ItemResult`, `conversion_kind()`.
- Produces: `convert_to_pdf(file_path, libreoffice_cmd) -> tuple[pathlib.Path | None, str]`.
- Produces: `download_all_for_course(classroom_service, drive_service, course, base_dir, downloaded_ids, options, report, libreoffice_cmd="", dry_run=False) -> None`.
- Produces: `render_report(report) -> None`.
- Removes: directory-wide `convert_downloaded_files()` scan.

- [ ] **Step 1: Write failing CLI report and conversion tests**

Add `DownloadOptions`, `DownloadReport`, and `ItemResult` to existing `gcr_downloader.models` test imports.

```python
def test_empty_pdf_is_conversion_failure(self):
    with tempfile.TemporaryDirectory() as directory:
        source = pathlib.Path(directory) / "report.docx"
        source.write_bytes(b"source")

        def create_empty_pdf(*_args, **_kwargs):
            source.with_suffix(".pdf").write_bytes(b"")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(downloader.subprocess, "run", side_effect=create_empty_pdf):
            pdf, message = downloader.convert_to_pdf(source, "soffice")

        self.assertIsNone(pdf)
        self.assertIn("non-empty PDF", message)
        self.assertTrue(source.exists())

def test_report_renderer_shows_status_counts(self):
    report = DownloadReport([
        ItemResult("Course", "notes.pdf", "downloaded", ("Course/notes.pdf",)),
        ItemResult("Course", "video.mp4", "skipped_video", message="Video excluded"),
    ])
    with mock.patch("builtins.print") as output:
        downloader.render_report(report)
    rendered = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
    self.assertIn("downloaded: 1", rendered)
    self.assertIn("skipped_video: 1", rendered)

def test_replace_conversion_updates_index_only_after_success(self):
    with tempfile.TemporaryDirectory() as directory:
        base_dir = pathlib.Path(directory)
        downloaded_ids = {}
        report = DownloadReport()

        class MetadataRequest:
            def execute(self):
                return {"name": "slides.pptx", "mimeType": "application/vnd.ms-powerpoint"}

        class MetadataFiles:
            def get(self, **_kwargs):
                return MetadataRequest()

        class MetadataDrive:
            def files(self):
                return MetadataFiles()

        def download(_drive, _file_id, destination, _mime_type, **_kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"slides")
            return True

        def convert(source, _command):
            pdf = source.with_suffix(".pdf")
            pdf.write_bytes(b"%PDF-converted")
            return pdf, ""

        with mock.patch.object(
            downloader,
            "list_course_files",
            return_value=[CourseFile("file-id", "slides.pptx")],
        ), mock.patch.object(
            downloader,
            "download_drive_file",
            side_effect=download,
        ), mock.patch.object(
            downloader,
            "convert_to_pdf",
            side_effect=convert,
        ):
            downloader.download_all_for_course(
                object(),
                MetadataDrive(),
                Course("course-id", "Course", "ACTIVE"),
                base_dir,
                downloaded_ids,
                DownloadOptions(convert_powerpoint=True, keep_originals=False),
                report,
                libreoffice_cmd="soffice",
            )

        self.assertFalse((base_dir / "Course" / "slides.pptx").exists())
        self.assertEqual(downloaded_ids["file-id"], "Course/slides.pdf")
        self.assertEqual(report.items[0].status, "converted")
        self.assertEqual(report.items[0].output_paths, ("Course/slides.pdf",))
```

- [ ] **Step 2: Run focused CLI tests and verify failures**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_cli.CliDownloaderTests.test_empty_pdf_is_conversion_failure tests.test_cli.CliDownloaderTests.test_report_renderer_shows_status_counts tests.test_cli.CliDownloaderTests.test_replace_conversion_updates_index_only_after_success -v`

Expected: FAIL on old conversion return type and missing report renderer.

- [ ] **Step 3: Build one `DownloadOptions` in CLI main**

Keep existing prompts but map them once:

```python
options = DownloadOptions(
    include_videos=get_video_preference(),
    convert_word=conversion_prefs["convert_docx"],
    convert_powerpoint=conversion_prefs["convert_ppt"],
    keep_originals=not conversion_prefs["delete_originals"],
)
report = DownloadReport()
```

If LibreOffice is unavailable, replace options with conversion flags false while preserving video and keep-original values.

- [ ] **Step 4: Convert immediately after each selected artifact**

Refactor `download_all_for_course()` to emit exactly one final `ItemResult` per Classroom attachment:

```python
def download_all_for_course(
    classroom_service,
    drive_service,
    course: Course,
    base_dir: pathlib.Path,
    downloaded_ids: dict[str, str],
    options: DownloadOptions,
    report: DownloadReport,
    libreoffice_cmd: str = "",
    dry_run: bool = False,
) -> None:
    base_path = base_dir.resolve()
    course_dir = base_path / safe_filename(course.name)
    for course_file in list_course_files(classroom_service, course.id):
        try:
            metadata = drive_service.files().get(
                fileId=course_file.id,
                fields="name,mimeType",
            ).execute()
        except Exception:
            report.add(ItemResult(course.name, course_file.title_hint, "download_failed", message="Failed to fetch file metadata"))
            continue

        source_name = ensure_extension(
            safe_filename(metadata.get("name") or course_file.title_hint),
            metadata.get("mimeType"),
        )
        if not options.include_videos and is_video_file(source_name, metadata.get("mimeType")):
            report.add(ItemResult(course.name, source_name, "skipped_video", message="Video excluded"))
            continue

        indexed_path = get_indexed_path(base_path, downloaded_ids.get(course_file.id, ""))
        if indexed_path is not None and indexed_path.exists():
            relative = indexed_path.relative_to(base_path).as_posix()
            downloaded_ids[course_file.id] = relative
            report.add(ItemResult(course.name, source_name, "skipped_existing", (relative,), "File already exists"))
            continue
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
            report.add(ItemResult(course.name, source_name, "dry_run", (relative_destination,)))
            continue

        if not download_drive_file(
            drive_service,
            course_file.id,
            destination,
            metadata.get("mimeType"),
        ):
            report.add(ItemResult(course.name, source_name, "download_failed", message="Download failed after three attempts"))
            continue

        downloaded_ids[course_file.id] = relative_destination
        if conversion_kind(source_name, options) is None:
            report.add(ItemResult(course.name, source_name, "downloaded", (relative_destination,)))
            continue

        pdf_path, error = convert_to_pdf(destination, libreoffice_cmd)
        if pdf_path is None:
            report.add(ItemResult(course.name, source_name, "conversion_failed", (relative_destination,), error))
            continue

        relative_pdf = pdf_path.relative_to(base_path).as_posix()
        outputs = (relative_destination, relative_pdf)
        if not options.keep_originals:
            try:
                destination.unlink()
            except OSError:
                report.add(ItemResult(course.name, source_name, "conversion_failed", outputs, "Converted PDF created but original could not be removed"))
                continue
            downloaded_ids[course_file.id] = relative_pdf
            outputs = (relative_pdf,)
        report.add(ItemResult(course.name, source_name, "converted", outputs))
```

In `main()`, abort before index save when selected-course enumeration fails:

```python
try:
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
except CatalogError as exc:
    print(str(exc))
    return 1
```

Replace old post-loop directory conversion with final persistence/report block:

```python
if not args.dry_run:
    save_index(downloaded_ids)
render_report(report)
return 0
```

- [ ] **Step 5: Replace converter and add report renderer**

Implement exact converter and renderer behavior:

```python
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
```

- [ ] **Step 6: Run full CLI suite**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_cli -v`

Expected: PASS; old directory-wide conversion test is replaced by per-item conversion tests.

- [ ] **Step 7: Commit CLI reports**

```bash
git add cli/classroom_downloader.py tests/test_cli.py
git commit -m "feat(cli): report download outcomes"
```

### Task 5: Web Drive And Gotenberg Adapters

**Files:**
- Modify: `requirements.txt`
- Modify: `app/drive.py`
- Create: `app/gotenberg.py`
- Create: `tests/test_web_adapters.py`

**Interfaces:**
- Consumes: shared export, extension, validation, and filename policy.
- Produces: `DriveMetadata(name: str, mime_type: str | None)`.
- Produces: `DriveDownloadError` and `download_to_spool()`.
- Produces: `GotenbergError`, `check_health()`, `convert_to_pdf()`.

- [ ] **Step 1: Pin Requests and write failing adapter tests**

Add `requests==2.34.2` to `requirements.txt`.

```python
# tests/test_web_adapters.py
import io
import unittest
from unittest import mock

from app import drive, gotenberg


class WebAdapterTests(unittest.TestCase):
    def test_drive_failure_closes_partial_spool(self):
        spool = io.BytesIO()

        class FailingDownloader:
            def __init__(self, file_handle, _request):
                self.file_handle = file_handle

            def next_chunk(self):
                self.file_handle.write(b"partial")
                raise RuntimeError("failed")

        files = mock.Mock()
        files.get_media.return_value = object()
        service = mock.Mock()
        service.files.return_value = files
        with mock.patch.object(drive.tempfile, "SpooledTemporaryFile", return_value=spool), \
             mock.patch.object(drive, "MediaIoBaseDownload", FailingDownloader):
            with self.assertRaises(drive.DriveDownloadError):
                drive.download_to_spool(service, "file-id", "application/pdf", max_attempts=1)
        self.assertTrue(spool.closed)

    def test_gotenberg_posts_expected_multipart_and_accepts_pdf(self):
        response = mock.Mock(status_code=200, headers={"Content-Type": "application/pdf"})
        response.iter_content.return_value = [b"%PDF-", b"converted"]
        session = mock.Mock()
        session.post.return_value = response

        result = gotenberg.convert_to_pdf(
            io.BytesIO(b"document"),
            "notes.docx",
            session=session,
            max_attempts=1,
        )

        self.assertEqual(result.read(), b"%PDF-converted")
        call = session.post.call_args
        self.assertTrue(call.args[0].endswith("/forms/libreoffice/convert"))
        self.assertEqual(call.kwargs["timeout"], (5, 130))
        self.assertEqual(call.kwargs["files"][0][0], "files")

    def test_gotenberg_400_is_not_retried(self):
        response = mock.Mock(status_code=400, text="unsafe details")
        session = mock.Mock()
        session.post.return_value = response
        with self.assertRaisesRegex(gotenberg.GotenbergError, "Conversion request rejected"):
            gotenberg.convert_to_pdf(io.BytesIO(b"bad"), "bad.docx", session=session)
        self.assertEqual(session.post.call_count, 1)

    def test_gotenberg_503_retries_three_times(self):
        response = mock.Mock(status_code=503, text="overloaded")
        session = mock.Mock()
        session.post.return_value = response
        with mock.patch.object(gotenberg.time, "sleep") as sleep:
            with self.assertRaises(gotenberg.GotenbergError):
                gotenberg.convert_to_pdf(io.BytesIO(b"doc"), "notes.docx", session=session)
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run adapter tests and verify missing module/API failures**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_adapters -v`

Expected: FAIL because `app.gotenberg` and new Drive APIs do not exist.

- [ ] **Step 3: Refactor web Drive adapter**

Remove duplicate `GOOGLE_EXPORTS`, filename sanitizer, and ID validator from `app/drive.py`. Add:

```python
import time

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
```

- [ ] **Step 4: Implement Gotenberg client**

```python
# app/gotenberg.py constants and public surface
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
                    output.close()
                    raise GotenbergError("Conversion returned invalid PDF")
                output.seek(0)
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
        raise GotenbergError("Conversion service unavailable")
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 5: Run adapter tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_adapters -v`

Expected: PASS, including exact retry and sanitized error assertions.

- [ ] **Step 6: Commit web adapters**

```bash
git add requirements.txt app/drive.py app/gotenberg.py tests/test_web_adapters.py
git commit -m "feat(web): add Gotenberg conversion adapter"
```

### Task 6: Web Download Orchestration And ZIP Report

**Files:**
- Create: `app/downloads.py`
- Modify: `app/zipstreamer.py`
- Modify: `app/main.py:12-198`
- Delete: `app/classroom.py`
- Delete: `app/classroom_downloader.py`
- Modify: `tests/test_web_app.py`
- Create: `tests/test_parity_contract.py`
- Modify: `tests/test_support.py`

**Interfaces:**
- Consumes: shared catalog/models/files, Task 5 Drive and Gotenberg adapters.
- Produces: `ArchiveEntry(path: str, stream: BinaryIO)`.
- Produces: `prepare_download(drive, course, files, options) -> tuple[list[ArchiveEntry], DownloadReport]`.
- Produces: `stream_zip(entries, report)` with ZIP64 and cleanup.
- Changes `/download`: one `course_id`, selected `file_ids`, `skip_videos`, `convert_word`, `convert_powerpoint`, `replace_originals`.

- [ ] **Step 1: Replace old endpoint tests with ownership and option tests**

Add these imports after dependency stubs are installed:

```python
import io

from app import downloads, zipstreamer
from app.drive import DriveMetadata
from app.gotenberg import GotenbergError
from app.zipstreamer import ArchiveEntry
from gcr_downloader.catalog import CatalogError
from gcr_downloader.models import (
    Course,
    CourseFile,
    DownloadOptions,
    DownloadReport,
    ItemResult,
)
```

```python
def test_download_rejects_empty_file_selection(self):
    request = type("Request", (), {"session": {"token": {}}})()
    with self.assertRaises(main.HTTPException) as error:
        main.download(request, course_id="course-1", file_ids=None)
    self.assertEqual(error.exception.status_code, 400)

def test_download_rejects_file_not_attached_to_course(self):
    request = type("Request", (), {"session": {"token": {}}})()
    course = Course("course-1", "Course", "ACTIVE")
    available = [CourseFile("allowed", "Allowed")]
    with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
         mock.patch.object(main, "build", side_effect=[object(), object()]), \
         mock.patch.object(main, "get_course", return_value=course), \
         mock.patch.object(main, "list_course_files", return_value=available):
        with self.assertRaises(main.HTTPException) as error:
            main.download(request, course_id="course-1", file_ids=["forged"])
    self.assertEqual(error.exception.status_code, 400)

def test_course_catalog_failure_returns_502_before_preparation(self):
    request = type("Request", (), {"session": {"token": {}}})()
    with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
         mock.patch.object(main, "build", side_effect=[object(), object()]), \
         mock.patch.object(main, "get_course", side_effect=CatalogError("Failed to fetch course")), \
         mock.patch.object(main, "prepare_download") as prepare:
        with self.assertRaises(main.HTTPException) as error:
            main.download(request, course_id="course-1", file_ids=["file-1"])
    self.assertEqual(error.exception.status_code, 502)
    prepare.assert_not_called()

def test_download_builds_non_destructive_options(self):
    request = type("Request", (), {"session": {"token": {}}})()
    course = Course("course-1", "Course", "ACTIVE")
    selected = [CourseFile("file-1", "Notes")]
    response = object()
    with mock.patch.object(main.Credentials, "from_authorized_user_info", return_value=object(), create=True), \
         mock.patch.object(main, "build", side_effect=[object(), object()]), \
         mock.patch.object(main, "get_course", return_value=course), \
         mock.patch.object(main, "list_course_files", return_value=selected), \
         mock.patch.object(main, "select_course_files", return_value=selected), \
         mock.patch.object(main, "prepare_download", return_value=([], DownloadReport())) as prepare, \
         mock.patch.object(main, "stream_zip", return_value=response):
        result = main.download(
            request,
            course_id="course-1",
            file_ids=["file-1"],
            convert_word=True,
            replace_originals=False,
        )
    self.assertIs(result, response)
    self.assertEqual(
        prepare.call_args.args[3],
        DownloadOptions(convert_word=True, keep_originals=True),
    )
```

- [ ] **Step 2: Write failing orchestration and ZIP tests**

Add tests to `tests/test_web_app.py` that patch Task 5 adapters and assert:

```python
def test_conversion_failure_keeps_original_and_reports_failure(self):
    source = io.BytesIO(b"original")
    with mock.patch.object(
        downloads,
        "get_metadata",
        return_value=DriveMetadata("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ), mock.patch.object(
        downloads,
        "download_to_spool",
        return_value=source,
    ), mock.patch.object(
        downloads,
        "convert_to_pdf",
        side_effect=GotenbergError("Conversion service unavailable"),
    ):
        entries, report = downloads.prepare_download(
            object(),
            Course("course-1", "Course", "ACTIVE"),
            [CourseFile("file-1", "Notes")],
            DownloadOptions(convert_word=True, keep_originals=False),
        )
    self.assertEqual([entry.path for entry in entries], ["Course/notes.docx"])
    self.assertEqual(report.items[0].status, "conversion_failed")
    self.assertEqual(report.items[0].output_paths, ("Course/notes.docx",))

def test_replace_success_emits_only_pdf(self):
    source = io.BytesIO(b"slides")
    pdf = io.BytesIO(b"%PDF-converted")
    with mock.patch.object(
        downloads,
        "get_metadata",
        return_value=DriveMetadata("slides.pptx", "application/vnd.ms-powerpoint"),
    ), mock.patch.object(downloads, "download_to_spool", return_value=source), \
         mock.patch.object(downloads, "convert_to_pdf", return_value=pdf):
        entries, report = downloads.prepare_download(
            object(),
            Course("course-1", "Course", "ACTIVE"),
            [CourseFile("file-1", "Slides")],
            DownloadOptions(convert_powerpoint=True, keep_originals=False),
        )
    self.assertEqual([entry.path for entry in entries], ["Course/slides.pdf"])
    self.assertTrue(source.closed)
    self.assertEqual(report.items[0].status, "converted")

def test_stream_zip_appends_report_and_closes_streams(self):
    class FakeZip:
        instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.entries = []
            FakeZip.instance = self

        def write_iter(self, path, iterable):
            self.entries.append((path, iterable))

        def __iter__(self):
            for _path, iterable in self.entries:
                yield from iterable

    source = io.BytesIO(b"notes")
    report = DownloadReport([ItemResult("Course", "notes.txt", "downloaded", ("Course/notes.txt",))])
    with mock.patch.object(zipstreamer.zipstream, "ZipFile", FakeZip):
        response = zipstreamer.stream_zip([ArchiveEntry("Course/notes.txt", source)], report)
        list(response.body_iterator)
    self.assertEqual(FakeZip.instance.entries[-1][0], "_download_report.json")
    self.assertTrue(FakeZip.instance.kwargs["allowZip64"])
    self.assertTrue(source.closed)
```

- [ ] **Step 3: Run web tests and verify failures**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_app -v`

Expected: FAIL on old route signature and missing `app.downloads` orchestration.

- [ ] **Step 3a: Add cross-adapter parity contract test**

```python
# tests/test_parity_contract.py
import unittest
from unittest import mock

from app import downloads
from app.drive import DriveMetadata
from cli import classroom_downloader as cli
from gcr_downloader.models import Course, CourseFile, DownloadOptions, DownloadReport


class MetadataRequest:
    def execute(self):
        return {"name": "lecture.mp4", "mimeType": "video/mp4"}


class MetadataFiles:
    def get(self, **_kwargs):
        return MetadataRequest()


class MetadataDrive:
    def files(self):
        return MetadataFiles()


class ParityContractTests(unittest.TestCase):
    def test_video_exclusion_has_same_status_in_both_adapters(self):
        course = Course("course-1", "Course", "ACTIVE")
        course_file = CourseFile("file-1", "lecture.mp4")
        options = DownloadOptions(include_videos=False)

        with mock.patch.object(
            downloads,
            "get_metadata",
            return_value=DriveMetadata("lecture.mp4", "video/mp4"),
        ), mock.patch.object(downloads, "download_to_spool") as web_download:
            _entries, web_report = downloads.prepare_download(
                MetadataDrive(),
                course,
                [course_file],
                options,
            )

        cli_report = DownloadReport()
        with mock.patch.object(cli, "list_course_files", return_value=[course_file]), \
             mock.patch.object(cli, "download_drive_file") as cli_download:
            cli.download_all_for_course(
                object(),
                MetadataDrive(),
                course,
                cli.pathlib.Path("downloads"),
                {},
                options,
                cli_report,
            )

        self.assertEqual(web_report.items[0].status, "skipped_video")
        self.assertEqual(cli_report.items[0].status, "skipped_video")
        web_download.assert_not_called()
        cli_download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Implement web preparation service**

```python
# app/downloads.py
import pathlib

from app.drive import DriveDownloadError, download_to_spool, get_metadata
from app.gotenberg import GotenbergError, convert_to_pdf
from app.zipstreamer import ArchiveEntry
from gcr_downloader.files import allocate_unique_name, conversion_kind, is_video_file, safe_filename
from gcr_downloader.models import Course, CourseFile, DownloadOptions, DownloadReport, ItemResult


def prepare_download(
    drive,
    course: Course,
    files: list[CourseFile],
    options: DownloadOptions,
) -> tuple[list[ArchiveEntry], DownloadReport]:
    entries: list[ArchiveEntry] = []
    report = DownloadReport()
    used_paths: set[str] = set()
    course_directory = safe_filename(course.name)

    for course_file in files:
        try:
            metadata = get_metadata(drive, course_file.id, course_file.title_hint)
        except DriveDownloadError:
            report.add(ItemResult(course.name, course_file.title_hint, "download_failed", message="Failed to fetch file metadata"))
            continue

        source_name = metadata.name
        if not options.include_videos and is_video_file(source_name, metadata.mime_type):
            report.add(ItemResult(course.name, source_name, "skipped_video", message="Video excluded"))
            continue

        try:
            source = download_to_spool(drive, course_file.id, metadata.mime_type)
        except DriveDownloadError:
            report.add(ItemResult(course.name, source_name, "download_failed", message="Download failed after three attempts"))
            continue

        kind = conversion_kind(source_name, options)
        raw_source_path = f"{course_directory}/{source_name}"
        if kind is None:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            report.add(ItemResult(course.name, source_name, "downloaded", (source_path,)))
            continue

        try:
            pdf = convert_to_pdf(source, source_name)
        except GotenbergError:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            report.add(ItemResult(course.name, source_name, "conversion_failed", (source_path,), "Document conversion failed"))
            continue

        raw_pdf_path = pathlib.PurePosixPath(raw_source_path).with_suffix(".pdf").as_posix()
        pdf_path = allocate_unique_name(raw_pdf_path, used_paths)
        outputs: list[str] = []
        if options.keep_originals:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            outputs.append(source_path)
        else:
            source.close()
        entries.append(ArchiveEntry(pdf_path, pdf))
        outputs.append(pdf_path)
        report.add(ItemResult(course.name, source_name, "converted", tuple(outputs)))

    return entries, report
```

- [ ] **Step 5: Implement ZIP stream cleanup and final report**

```python
# app/zipstreamer.py
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
```

- [ ] **Step 6: Replace FastAPI catalog and download routes**

Import shared catalog directly. Map `CatalogError` to `502`, `ValueError` selection errors to `400`, and keep `401`/login behavior.

Replace course page and file API catalog calls with:

```python
try:
    courses = list_courses(classroom, state="all")
    error_message = None
except CatalogError as exc:
    logger.warning("Failed to load courses: %s", exc)
    courses = []
    error_message = str(exc)
```

```python
@app.get("/api/courses/{course_id}/files")
def get_course_files(request: Request, course_id: str):
    if "token" not in request.session:
        raise HTTPException(status_code=401)
    try:
        credentials = Credentials.from_authorized_user_info(request.session["token"], SCOPES)
        classroom = build("classroom", "v1", credentials=credentials)
        files = list_course_files(classroom, course_id)
        return [{"id": item.id, "name": item.title_hint} for item in files]
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except CatalogError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
```

Use exact form defaults:

```python
def download(
    request: Request,
    course_id: str = Form(None),
    file_ids: list[str] = Form(None),
    skip_videos: bool = Form(False),
    convert_word: bool = Form(False),
    convert_powerpoint: bool = Form(False),
    replace_originals: bool = Form(False),
):
    if "token" not in request.session:
        return RedirectResponse("/login")
    if not course_id or not file_ids:
        raise HTTPException(status_code=400, detail="Select at least one file")

    credentials = Credentials.from_authorized_user_info(request.session["token"], SCOPES)
    classroom = build("classroom", "v1", credentials=credentials)
    drive = build("drive", "v3", credentials=credentials)
    try:
        course = get_course(classroom, course_id)
        available = list_course_files(classroom, course_id)
        selected = select_course_files(available, file_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    options = DownloadOptions(
        include_videos=not skip_videos,
        convert_word=convert_word,
        convert_powerpoint=convert_powerpoint,
        keep_originals=not replace_originals,
    )
    entries, report = prepare_download(drive, course, selected, options)
    return stream_zip(entries, report)
```

Remove `download_scope` and whole-course branch.

- [ ] **Step 7: Delete duplicate app modules and update dependency stubs**

Delete `app/classroom.py` and `app/classroom_downloader.py`. Replace response stub with:

```python
class StreamingResponse:
    def __init__(self, content, media_type=None, headers=None):
        self.body_iterator = content
        self.media_type = media_type
        self.headers = headers or {}


fastapi_responses.StreamingResponse = StreamingResponse
```

Replace zip stub with constructor-compatible class:

```python
class StubZipFile:
    def __init__(self, *args, **kwargs):
        self.entries = []

    def write_iter(self, path, iterable):
        self.entries.append((path, iterable))

    def __iter__(self):
        for _path, iterable in self.entries:
            yield from iterable


zipstream.ZipFile = StubZipFile
```

- [ ] **Step 8: Run web and shared tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_app tests.test_web_adapters tests.test_parity_contract tests.test_core_catalog tests.test_core_files tests.test_core_models -v`

Expected: PASS. No import references to deleted app modules.

- [ ] **Step 9: Commit web pipeline**

```bash
git add app tests/test_web_app.py tests/test_parity_contract.py tests/test_support.py
git commit -m "feat(web): stream parity download reports"
```

### Task 7: Web State And Download Controls

**Files:**
- Modify: `app/templates/courses.html:44-286`
- Create: `tests/test_web_template.py`

**Interfaces:**
- Consumes: Task 6 form names and route behavior.
- Produces: client-side `active`, `archived`, `all` filter with default `all`.
- Produces: `skip_videos`, `convert_word`, `convert_powerpoint`, `replace_originals` controls.

- [ ] **Step 1: Write failing template contract test**

```python
# tests/test_web_template.py
import pathlib
import unittest


class WebTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = pathlib.Path("app/templates/courses.html").read_text(encoding="utf-8")

    def test_template_contains_parity_controls(self):
        for name in (
            'name="course_id"',
            'name="skip_videos"',
            'name="convert_word"',
            'name="convert_powerpoint"',
            'name="replace_originals"',
            'data-course-state=',
        ):
            self.assertIn(name, self.template)

    def test_template_removes_obsolete_course_scope(self):
        self.assertNotIn('name="download_scope"', self.template)
        self.assertNotIn('name="course_ids"', self.template)

    def test_api_file_names_are_rendered_with_dom_text_nodes(self):
        self.assertIn("document.createTextNode", self.template)
        self.assertNotIn("${x.name}", self.template)
        self.assertNotIn('onclick="openDrawer', self.template)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run template test and verify failure**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_template -v`

Expected: FAIL on missing new controls and old field names.

- [ ] **Step 3: Add course-state filter**

Add `data-course-state="{{ c.state|lower }}"` to cards and render state from `c.state`. Add controls:

```html
<div id="courseStateFilters" class="flex rounded-xl border border-gray-200 bg-white p-1 text-xs font-semibold">
  <button type="button" data-state-filter="all" class="state-filter rounded-lg bg-emerald-100 px-3 py-2 text-emerald-700">All</button>
  <button type="button" data-state-filter="active" class="state-filter rounded-lg px-3 py-2 text-gray-500">Active</button>
  <button type="button" data-state-filter="archived" class="state-filter rounded-lg px-3 py-2 text-gray-500">Archived</button>
</div>
```

Use one filter function:

```javascript
let selectedCourseState = "all";

function filterCourses(){
  const query = searchInput.value.toLowerCase().trim();
  document.querySelectorAll(".course-card").forEach((card)=>{
    const nameMatches = !query || (card.dataset.courseName || "").includes(query);
    const stateMatches = selectedCourseState === "all" || card.dataset.courseState === selectedCourseState;
    card.classList.toggle("hidden", !(nameMatches && stateMatches));
  });
  updateCourseCount();
}

document.querySelectorAll(".state-filter").forEach((button)=>{
  button.addEventListener("click", ()=>{
    selectedCourseState = button.dataset.stateFilter;
    document.querySelectorAll(".state-filter").forEach((item)=>{
      item.classList.toggle("bg-emerald-100", item === button);
      item.classList.toggle("text-emerald-700", item === button);
      item.classList.toggle("text-gray-500", item !== button);
    });
    filterCourses();
  });
});
```

- [ ] **Step 4: Add download options**

Replace hidden fields and add exact options:

```html
<input type="hidden" name="course_id" id="activeCourseId">
<fieldset class="space-y-3 border-t p-6 text-sm">
  <legend class="font-semibold text-gray-700">Download options</legend>
  <label class="flex items-center gap-2"><input type="checkbox" name="skip_videos" value="true"> Skip video files</label>
  <label class="flex items-center gap-2"><input id="convertWord" type="checkbox" name="convert_word" value="true"> Convert Word files to PDF</label>
  <label class="flex items-center gap-2"><input id="convertPowerPoint" type="checkbox" name="convert_powerpoint" value="true"> Convert PowerPoint files to PDF</label>
  <label class="flex items-center gap-2"><input id="replaceOriginals" type="checkbox" name="replace_originals" value="true" disabled> Replace originals after successful conversion</label>
</fieldset>
```

Enable replacement only when conversion is selected:

```javascript
const convertWord = document.getElementById("convertWord");
const convertPowerPoint = document.getElementById("convertPowerPoint");
const replaceOriginals = document.getElementById("replaceOriginals");

function updateReplaceControl(){
  replaceOriginals.disabled = !(convertWord.checked || convertPowerPoint.checked);
  if(replaceOriginals.disabled){replaceOriginals.checked = false;}
}
convertWord.addEventListener("change", updateReplaceControl);
convertPowerPoint.addEventListener("change", updateReplaceControl);
```

- [ ] **Step 5: Remove unsafe API-name interpolation**

Replace `fileList.innerHTML = f.map(...)` with:

```javascript
const fileList = document.getElementById("fileList");
fileList.replaceChildren();
f.forEach((item)=>{
  const label = document.createElement("label");
  label.className = "block rounded-lg border p-3 hover:bg-gray-50";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = true;
  checkbox.name = "file_ids";
  checkbox.value = item.id;
  label.append(checkbox, document.createTextNode(` ${item.name}`));
  fileList.appendChild(label);
});
```

Replace inline course-name JavaScript with data attributes:

```html
<button type="button" data-manage-files data-course-id="{{ c.id }}" data-course-name="{{ c.name }}"
  class="mt-5 rounded-lg bg-emerald-50 py-2 text-emerald-700 hover:bg-emerald-100">
  Manage Files
</button>
```

```javascript
document.querySelectorAll("[data-manage-files]").forEach((button)=>{
  button.addEventListener("click", ()=>openDrawer(button.dataset.courseId, button.dataset.courseName));
});
```

- [ ] **Step 6: Run template and web tests**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_web_template tests.test_web_app -v`

Expected: PASS. Existing empty-selection client validation and hidden iframe download behavior remain.

- [ ] **Step 7: Commit web controls**

```bash
git add app/templates/courses.html tests/test_web_template.py
git commit -m "feat(web): add parity download controls"
```

### Task 8: Local And Cloud Run Sidecar Configuration

**Files:**
- Create: `compose.yaml`
- Create: `deploy/cloud-run-service.yaml`
- Create: `deploy/render_cloud_run.py`
- Modify: `.gitignore`
- Create: `tests/test_deploy_config.py`

**Interfaces:**
- Produces: local `web` and `gotenberg` Compose services.
- Produces: tokenized Cloud Run service config using `__WEB_IMAGE__` only.
- Produces: renderer requiring explicit immutable web image URL.

- [ ] **Step 1: Write failing deployment config tests**

```python
# tests/test_deploy_config.py
import pathlib
import tempfile
import unittest

from deploy.render_cloud_run import render_service


class DeployConfigTests(unittest.TestCase):
    def test_cloud_run_sidecar_contract(self):
        text = pathlib.Path("deploy/cloud-run-service.yaml").read_text(encoding="utf-8")
        for value in (
            "gotenberg/gotenberg:8.34.0-libreoffice",
            'run.googleapis.com/container-dependencies: \'{"web":["gotenberg"]}\'',
            "containerConcurrency: 1",
            "timeoutSeconds: 900",
            "path: /health",
            "port: 3000",
            "memory: 1Gi",
            "memory: 2Gi",
        ):
            self.assertIn(value, text)

    def test_renderer_replaces_only_web_image_token(self):
        rendered = render_service("asia-south1-docker.pkg.dev/example/app/web@sha256:abc")
        self.assertNotIn("__WEB_IMAGE__", rendered)
        self.assertIn("web@sha256:abc", rendered)
        self.assertIn("gotenberg/gotenberg:8.34.0-libreoffice", rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run deployment tests and verify missing-file failure**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_deploy_config -v`

Expected: FAIL because deploy files do not exist.

- [ ] **Step 3: Create local Compose service**

```yaml
# compose.yaml
name: gcr-downloader
services:
  web:
    build: .
    ports:
      - "8080:8080"
    environment:
      SESSION_SECRET: ${SESSION_SECRET:-dev-secret}
      GOOGLE_OAUTH_JSON: ${GOOGLE_OAUTH_JSON:?Set GOOGLE_OAUTH_JSON}
      REDIRECT_URI: ${REDIRECT_URI:-http://localhost:8080/callback}
      GOTENBERG_URL: http://gotenberg:3000
    depends_on:
      gotenberg:
        condition: service_healthy
  gotenberg:
    image: gotenberg/gotenberg:8.34.0-libreoffice
    environment:
      LIBREOFFICE_AUTO_START: "true"
      LIBREOFFICE_MAX_QUEUE_SIZE: "1"
      LIBREOFFICE_START_TIMEOUT: 60s
      API_TIMEOUT: 120s
    healthcheck:
      test: ["CMD", "curl", "--fail", "http://localhost:3000/health"]
      interval: 5s
      timeout: 3s
      retries: 24
```

Do not add `ports` to Gotenberg service.

- [ ] **Step 4: Create Cloud Run service template**

```yaml
# deploy/cloud-run-service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: classroom-downloader-web
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/container-dependencies: '{"web":["gotenberg"]}'
    spec:
      containerConcurrency: 1
      timeoutSeconds: 900
      containers:
        - name: web
          image: __WEB_IMAGE__
          ports:
            - containerPort: 8080
          env:
            - name: GOTENBERG_URL
              value: http://localhost:3000
            - name: SESSION_SECRET
              valueFrom:
                secretKeyRef:
                  name: classroom-session-secret
                  key: latest
            - name: GOOGLE_OAUTH_JSON
              valueFrom:
                secretKeyRef:
                  name: google-oauth-json
                  key: latest
          resources:
            limits:
              cpu: "1"
              memory: 2Gi
        - name: gotenberg
          image: gotenberg/gotenberg:8.34.0-libreoffice
          env:
            - name: LIBREOFFICE_AUTO_START
              value: "true"
            - name: LIBREOFFICE_MAX_QUEUE_SIZE
              value: "1"
            - name: LIBREOFFICE_START_TIMEOUT
              value: 60s
            - name: API_TIMEOUT
              value: 120s
          resources:
            limits:
              cpu: "1"
              memory: 1Gi
          startupProbe:
            httpGet:
              path: /health
              port: 3000
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 48
```

Only web declares `containerPort`; Gotenberg remains instance-local.

- [ ] **Step 5: Create deterministic renderer**

```python
# deploy/render_cloud_run.py
import argparse
import pathlib

TOKEN = "__WEB_IMAGE__"
TEMPLATE = pathlib.Path(__file__).with_name("cloud-run-service.yaml")


def render_service(web_image: str) -> str:
    if not web_image or "://" in web_image or " " in web_image:
        raise ValueError("Provide a container image reference")
    text = TEMPLATE.read_text(encoding="utf-8")
    if text.count(TOKEN) != 1:
        raise RuntimeError("Cloud Run template must contain one web image token")
    return text.replace(TOKEN, web_image)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--output", default="deploy/cloud-run-service.rendered.yaml")
    args = parser.parse_args()
    pathlib.Path(args.output).write_text(render_service(args.web_image), encoding="utf-8")


if __name__ == "__main__":
    main()
```

Add generated output to `.gitignore`:

```gitignore
deploy/cloud-run-service.rendered.yaml
```

- [ ] **Step 6: Run config tests and Compose validation**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_deploy_config -v`

Expected: PASS.

Run: `GOOGLE_OAUTH_JSON='{"web":{}}' docker compose config`

Expected: exit `0`; rendered config contains no published Gotenberg port.

Run: `git check-ignore deploy/cloud-run-service.rendered.yaml`

Expected: prints `deploy/cloud-run-service.rendered.yaml`.

- [ ] **Step 7: Commit deployment config**

```bash
git add compose.yaml deploy .gitignore tests/test_deploy_config.py
git commit -m "build: add Gotenberg sidecar deployment"
```

### Task 9: Real Gotenberg Conversion Smoke Test

**Files:**
- Create: `tests/generate_office_fixtures.py`
- Create: `tests/fixtures/sample.docx`
- Create: `tests/fixtures/sample.pptx`
- Create: `tests/test_gotenberg_integration.py`

**Interfaces:**
- Consumes: Task 5 `convert_to_pdf()` and Task 8 Compose network.
- Produces: opt-in integration suite controlled by `GOTENBERG_INTEGRATION=1`.

- [ ] **Step 1: Add reproducible fixture generator**

```python
# tests/generate_office_fixtures.py
import pathlib

from docx import Document
from pptx import Presentation

OUTPUT = pathlib.Path(__file__).with_name("fixtures")
OUTPUT.mkdir(exist_ok=True)

document = Document()
document.add_heading("Classroom Downloader", level=1)
document.add_paragraph("Gotenberg DOCX integration fixture")
document.save(OUTPUT / "sample.docx")

presentation = Presentation()
slide = presentation.slides.add_slide(presentation.slide_layouts[1])
slide.shapes.title.text = "Classroom Downloader"
slide.placeholders[1].text = "Gotenberg PPTX integration fixture"
presentation.save(OUTPUT / "sample.pptx")
```

- [ ] **Step 2: Generate fixtures inside one-off Python container**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.12-slim sh -c "pip install --no-cache-dir python-docx==1.2.0 python-pptx==1.0.2 && python tests/generate_office_fixtures.py"
```

Expected: both generated files exist and are non-empty.

- [ ] **Step 3: Write skipped-by-default integration test**

```python
# tests/test_gotenberg_integration.py
import os
import pathlib
import unittest

from app.gotenberg import convert_to_pdf


@unittest.skipUnless(os.environ.get("GOTENBERG_INTEGRATION") == "1", "Gotenberg integration disabled")
class GotenbergIntegrationTests(unittest.TestCase):
    def test_docx_and_pptx_convert_to_pdf(self):
        base_url = os.environ.get("GOTENBERG_URL", "http://gotenberg:3000")
        for fixture in ("sample.docx", "sample.pptx"):
            path = pathlib.Path("tests/fixtures") / fixture
            with self.subTest(fixture=fixture), path.open("rb") as source:
                pdf = convert_to_pdf(source, fixture, base_url=base_url, max_attempts=1)
                self.assertEqual(pdf.read(5), b"%PDF-")
                pdf.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Verify default unit discovery skips integration**

Run: `scripts/run-python-in-container.sh -m unittest tests.test_gotenberg_integration -v`

Expected: 1 skipped, 0 failures.

- [ ] **Step 5: Run real sidecar integration in app container**

Run:

```bash
set -eu
docker compose up -d --wait gotenberg
trap 'docker compose down' EXIT
docker build -t classroom-downloader:test .
docker run --rm \
  --network gcr-downloader_default \
  -v "$PWD/tests:/app/tests:ro" \
  -e GOTENBERG_URL=http://gotenberg:3000 \
  -e GOTENBERG_INTEGRATION=1 \
  classroom-downloader:test \
  python -m unittest discover -s tests -p 'test_gotenberg_integration.py' -v
```

Expected: DOCX and PPTX subtests pass; cleanup removes sidecar/network.

- [ ] **Step 6: Commit integration fixtures**

```bash
git add tests/generate_office_fixtures.py tests/fixtures tests/test_gotenberg_integration.py
git commit -m "test: cover real Gotenberg conversion"
```

### Task 10: Documentation, Cleanup, And Full Verification

**Files:**
- Modify: `README.md`
- Replace: `cli/README.md`
- Modify: `docs/superpowers/specs/2026-08-01-app-cli-feature-parity-design.md`
- Verify all files changed in Tasks 1-9.

**Interfaces:**
- Consumes: completed implementation and deployment commands.
- Produces: canonical feature matrix, CLI/web instructions, local Compose and Cloud Run deployment steps.

- [ ] **Step 1: Update canonical README**

Replace stale web-on-hold note. Add matrix with shared features and explicit platform differences. Document:

```text
Shared: active/archived/all filters, Drive exports, video option, Word/PowerPoint conversion, keep/replace, retries, reports.
Web only: per-file selection, stateless ZIP, Gotenberg.
CLI only: course selection, base directory, dry-run, persistent index, local LibreOffice.
```

Add CLI example `python classroom_downloader.py --course-state archived`. Add local `docker compose up --build` flow and exact renderer/deploy flow:

```bash
python deploy/render_cloud_run.py --web-image "$WEB_IMAGE"
gcloud run services replace deploy/cloud-run-service.rendered.yaml --region asia-south1
```

Document required Secret Manager names and OAuth callback URI.

- [ ] **Step 2: Replace divergent CLI README**

Keep only project title, link `../README.md` as canonical documentation, CLI install/run commands, credentials location, and CLI-only flags. Remove old fork URL, `web/` path, and duplicated full guide.

- [ ] **Step 3: Mark design implemented**

Change spec status from `Approved` to `Implemented` only after all verification steps below pass.

- [ ] **Step 4: Run full unit suite in built app image**

Run:

```bash
docker build -t classroom-downloader:test .
```

Expected: all non-integration tests pass; Gotenberg integration test reports one intentional skip.

- [ ] **Step 5: Run compile and lint checks in containers**

Run:

```bash
docker run --rm -v "$PWD/tests:/app/tests:ro" classroom-downloader:test python -m compileall app cli gcr_downloader tests
```

Expected: both commands exit `0` with no errors.

- [ ] **Step 6: Run Compose and Gotenberg smoke checks**

Run exact Task 9 integration command again after final code/docs state.

Expected: Gotenberg health succeeds; DOCX and PPTX conversions pass; `docker compose down` leaves no project containers.

- [ ] **Step 7: Verify removal and repository hygiene**

Run:

```bash
test ! -e app/classroom.py
```

Expected: removed files absent, diff check clean, status lists only intended implementation/docs changes.

- [ ] **Step 8: Commit docs and final cleanup**

```bash
git add README.md cli/README.md docs/superpowers/specs/2026-08-01-app-cli-feature-parity-design.md
git commit -m "docs: document app and CLI parity"
```

- [ ] **Step 9: Review complete branch diff**

Run:

```bash
git status --short --branch
```

Expected: clean tracked worktree, task commits visible in order, no whitespace errors. Review behavior against every acceptance criterion in design before integration choice.
