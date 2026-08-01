# App and CLI Feature Parity Design

**Date:** 2026-08-01
**Status:** Implemented

## Context

This repository contains two user-facing downloaders:

- `app/`: FastAPI web app that authenticates through a web OAuth flow and returns a ZIP archive.
- `cli/`: interactive local script that authenticates as a desktop app and writes files to disk.

Both implementations discover Google Classroom attachments and download or export Google Drive files, but portable behavior is duplicated and has drifted. The live web path uses `app/main.py`, `app/classroom.py`, and `app/drive.py`. `app/classroom_downloader.py` is an unused, older CLI-style implementation.

Parity means shared portable capabilities and semantics, not identical interaction models. Web remains file-oriented and stateless. CLI remains course-oriented and keeps local quality-of-life features.

## Goals

- Define portable Classroom and Drive behavior once.
- Give both interfaces active/archived course filtering, video controls, consistent exports, document conversion choices, safe duplicate handling, retries, and explicit completion reports.
- Keep web per-file selection and CLI course-level selection.
- Convert web Word and PowerPoint files through a private Gotenberg sidecar.
- Preserve existing OAuth entry points, local CLI history, atomic writes, and web ZIP delivery.
- Prevent future parity drift with shared policy and contract tests.

## Non-Goals

- Per-file selection in CLI.
- Persistent browser or server-side web download history.
- Web dry-run or arbitrary output-directory controls.
- Replacing CLI desktop OAuth or web session OAuth.
- General UI redesign unrelated to parity controls.
- Spreadsheet-to-PDF conversion.

## Feature Contract

| Capability | Shared contract | Web adapter | CLI adapter |
| --- | --- | --- | --- |
| Course states | Fetch `ACTIVE` and `ARCHIVED`; default to `all`; support `active`, `archived`, and `all` filters | Client-side state filter plus existing name search | New `--course-state`; existing `--course-name-contains` remains |
| Selection | Selected resources are validated and deduplicated | User selects files inside one course | User selects one or more whole courses |
| Workspace exports | Docs to PDF, Slides to PPTX, Sheets to XLSX, Drawings to PNG, Jamboard to PDF | Shared mapping | Shared mapping |
| Videos | Included by default; explicit skip option | Download-form control | Existing prompt retained with same default |
| Office conversion | Word and PowerPoint conversion disabled by default; user selects file types | Gotenberg `/forms/libreoffice/convert` | Local LibreOffice CLI |
| Originals | Kept by default; user may replace originals after successful conversion | ZIP includes original plus PDF, or PDF only in replace mode | Local files retain or delete original |
| Conversion failure | Original always survives; failure is reported | Original remains in ZIP | Original remains on disk |
| Retries | Three attempts with `1s` then `2s` backoff | Drive and retryable Gotenberg failures | Drive failures |
| Naming | Safe course/file names and deterministic numeric suffixes | Unique paths within current ZIP | Unique paths on local filesystem |
| Reporting | Shared per-item outcomes and summary counts | `_download_report.json` in every ZIP | Concise terminal summary |
| Download history | Not portable | Per-request deduplication only | Persistent `download_index.json` and local existence checks |
| Delivery QoL | Platform-specific | ZIP response, logout, search, file drawer | `--base-dir`, `--dry-run`, confirmation, index recovery |

## Architecture

Create top-level `gcr_downloader/` package. Neither interface imports the other.

### `gcr_downloader/catalog.py`

Owns Google Classroom catalog behavior:

- Paginated active and archived course listing.
- Course-state filtering.
- Paginated coursework and coursework-material attachment enumeration.
- Drive file ID deduplication while preserving stable order.
- Validation that web-submitted file IDs belong to selected course.

It accepts Google API service objects and returns typed domain records. It has no FastAPI, terminal, filesystem, or OAuth dependencies.

### `gcr_downloader/files.py`

Owns portable file policy:

- Drive and Classroom ID validation.
- Safe filename normalization.
- Google Workspace export mapping and extension selection.
- Video detection by MIME type and extension.
- Deterministic duplicate-name allocation.
- Word and PowerPoint conversion classification.

It does not download bytes or invoke a conversion engine.

### `gcr_downloader/models.py`

Defines dataclasses:

- `Course`
- `CourseFile`
- `DownloadOptions`
- `ItemResult`
- `DownloadReport`

`DownloadOptions` contains video inclusion, Word conversion, PowerPoint conversion, and keep-originals behavior. Course-state filtering is a catalog input, not a download option. `DownloadReport` serializes the same outcomes for both adapters.

### Web Adapter

- `app/main.py`: HTTP/session orchestration, form validation, selected-file ownership checks, response creation.
- `app/drive.py`: Drive metadata and byte transfer using shared export plans.
- `app/gotenberg.py`: localhost health check and LibreOffice conversion request.
- `app/zipstreamer.py`: archive path registration, streamed ZIP response, final report entry, cleanup.
- `app/templates/courses.html`: course-state, video, conversion, and keep-original controls.

Delete `app/classroom.py` after moving its catalog behavior into shared package. Delete unused `app/classroom_downloader.py`.

### CLI Adapter

`cli/classroom_downloader.py` remains executable entry point and retains:

- Desktop OAuth and token refresh.
- Interactive course-level selection and confirmation.
- `--base-dir`, `--course-name-contains`, and `--dry-run`.
- Local atomic writes and persistent index recovery.
- LibreOffice discovery and conversion.
- Terminal rendering.

Move shared constants from `cli/constants.py` into shared package, then delete `cli/constants.py`.
CLI-only token, index, and default-directory constants move into `cli/classroom_downloader.py`.

## Data Flow

### Web

1. `GET /courses` loads active and archived courses through shared catalog.
2. Browser applies name and state filters without another API request.
3. File drawer requests one course's deduplicated attachment catalog.
4. User selects files and download options.
5. `POST /download` validates session, course ID, options, and non-empty file selection.
6. Server re-enumerates selected course and rejects any requested ID not attached to it.
7. Shared file policy resolves video exclusions, export format, conversion need, and unique archive paths under sanitized course name.
8. Web adapter downloads each accepted item atomically into request-scoped spooled temporary storage.
9. Selected Word or PowerPoint artifacts are sent to Gotenberg. Successful PDFs are verified before original-replacement policy runs.
10. ZIP response streams prepared artifacts and ends with `_download_report.json`.
11. Request-scoped temporary resources close after response completion or disconnect.

Web remains stateless between requests. It does not store downloaded IDs in cookies, browser storage, database, or server filesystem.
The unused `download_scope=courses` branch is removed; `/download` accepts one course ID and selected file IDs from the file drawer.
Each item uses an `8 MiB` in-memory spool threshold before spilling to request-scoped temporary storage. No item is registered in the archive until its download or conversion artifact is complete.

### CLI

1. Parse arguments, including `--course-state {active,archived,all}` with default `all`.
2. Authenticate and load local index.
3. Fetch active and archived courses, then apply state and name filters.
4. User selects whole courses.
5. Collect conversion and video options.
6. Enumerate each selected course through shared catalog.
7. Shared file policy resolves export, video, and naming behavior.
8. Filesystem adapter uses existing atomic downloads and index-aware duplicate recovery.
9. Local LibreOffice converts selected Word and PowerPoint artifacts.
10. Original is removed only after non-empty PDF exists. Index path changes with replacement.
11. Save index only outside dry-run and print shared report summary.

## Conversion Contract

Conversion applies to `.doc`, `.docx`, `.ppt`, and `.pptx` artifacts. This includes a Google Slides export produced as `.pptx`.

### Web Gotenberg Adapter

- Base URL: `GOTENBERG_URL`, default `http://localhost:3000`.
- Health route: `GET /health`.
- Conversion route: `POST /forms/libreoffice/convert`.
- Request: one multipart `files` part per conversion call.
- Success: HTTP `200`, non-empty body, PDF content type, and PDF signature.
- Client errors: Gotenberg `4xx` is not retried.
- Transient errors: timeout, connection failure, `5xx`, and `503` receive three attempts with `1s` then `2s` backoff.
- Failure: retain original artifact and record sanitized conversion error.

When keep-originals is enabled, archive contains original and PDF with independently unique names. In replace mode, archive contains only verified PDF. Conversion failure overrides replace mode and includes original.

### CLI LibreOffice Adapter

Existing executable discovery remains. Conversion success requires non-empty PDF output. Existing PDF collision never deletes source. Replace mode updates `download_index.json` only after verified conversion and source removal.

## Error Handling

### Abort Before Download

These errors abort without producing an archive or modifying CLI index:

- Authentication/session failure.
- Course catalog failure.
- Selected-course attachment enumeration failure.
- Empty selection.
- Invalid download options.
- Submitted file ID not attached to submitted course.

Web returns user-safe `4xx` or `502`; CLI prints a concise error and exits non-zero. Detailed exceptions remain in logs.

### Best-Effort Item Processing

After validated item planning starts, one item failure does not discard successful items.

Statuses are:

- `downloaded`
- `converted`
- `skipped_video`
- `skipped_existing` (CLI only)
- `dry_run` (CLI only)
- `download_failed`
- `conversion_failed`

`conversion_failed` may still include original output path. Download failures never create partial destination files or mark CLI index entries as downloaded.

### Report Shape

Web report is UTF-8 JSON with:

- Schema version `1`.
- Summary counts by status.
- Course name and source filename per item.
- Final output paths.
- Sanitized message for skipped or failed item.

Raw OAuth data, access tokens, stack traces, and credential material never enter report. CLI uses same report object but renders text instead of persisting another file.

## Gotenberg Deployment

Current deployment facts were verified on 2026-08-01 against official Gotenberg and Google Cloud documentation.

- Pin `gotenberg/gotenberg:8.34.0-libreoffice`.
- Release `v8.34.0` was published 2026-06-12.
- Run FastAPI as sole Cloud Run ingress container on port `8080`.
- Run Gotenberg as sidecar on port `3000`; do not expose this port.
- Configure web container dependency on Gotenberg.
- Give Gotenberg HTTP startup probe `GET /health` on port `3000`.
- Set `GOTENBERG_URL=http://localhost:3000` only on web container.
- Start Gotenberg with `1 CPU / 1 GiB` and web with `1 CPU / 2 GiB` as deployment baseline.
- Set Cloud Run container concurrency to `1` because one Gotenberg LibreOffice process serializes conversions; scale service instances horizontally.
- Set service request timeout to `900` seconds for multi-file preparation and transfer.
- Configure `LIBREOFFICE_AUTO_START=true`, `LIBREOFFICE_MAX_QUEUE_SIZE=1`, `LIBREOFFICE_START_TIMEOUT=60s`, and `API_TIMEOUT=120s` on Gotenberg.
- Configure web Gotenberg client with `5s` connection timeout and `130s` response timeout.

Add `compose.yaml` for local web plus same pinned Gotenberg image. Add `deploy/cloud-run-service.yaml` for production multi-container deployment with explicit startup dependency and probe. OAuth/session secrets are injected only into web container.

Sources:

- Gotenberg conversion: https://gotenberg.dev/docs/convert-with-libreoffice/convert-to-pdf
- Gotenberg installation/resources: https://gotenberg.dev/docs/getting-started/installation
- Gotenberg configuration: https://gotenberg.dev/docs/configuration
- Gotenberg release: https://github.com/gotenberg/gotenberg/releases/tag/v8.34.0
- Cloud Run sidecars: https://docs.cloud.google.com/run/docs/deploying
- Cloud Run container dependencies: https://docs.cloud.google.com/run/docs/configuring/services/containers

## Security And Privacy

- Web verifies submitted file membership against selected course before Drive download.
- IDs, filenames, and archive paths pass shared validation/sanitization.
- Gotenberg is reachable only over instance-local networking.
- Gotenberg receives document bytes only; it receives no Google credentials or OAuth tokens.
- Temporary artifacts have request scope and are cleaned on success, error, or disconnect.
- Web adds no persistent user history or document storage.
- Existing secret exclusions in `.gitignore` and `.dockerignore` remain required.

## Testing

### Shared Unit Tests

- Pagination across active and archived courses.
- State filters and case-insensitive name filtering inputs.
- Coursework plus coursework-material enumeration.
- Stable Drive ID deduplication.
- ID validation, filename safety, and duplicate suffix allocation.
- Every Workspace export mapping.
- Video detection with extension, MIME type, and missing MIME type.
- Conversion classification and option defaults.
- Report counting and JSON serialization.

### Web Adapter Tests

- Empty and forged selections return `400`.
- Course enumeration failure returns `502` before ZIP response.
- Video option excludes video and reports skip.
- Gotenberg request uses correct route and multipart field.
- Gotenberg `4xx` is not retried; transient failures use exactly three attempts.
- Keep mode includes original and PDF.
- Replace mode includes verified PDF only.
- Conversion failure retains original and reports failure.
- Duplicate names receive deterministic unique archive paths.
- Every successful ZIP contains valid `_download_report.json`.
- Temporary resources clean up after response and failure.

### CLI Adapter Tests

- `--course-state` filtering and default.
- Existing course selection, dry-run, and video behavior.
- Existing atomic download and duplicate recovery guarantees.
- Index migration and out-of-root path protection.
- Keep/replace conversion behavior and index updates.
- Conversion failure retains source.
- Terminal summary reflects shared report.

### Contract And Integration Tests

- Same fake catalog and `DownloadOptions` produce same portable plans and outcomes in both adapters.
- Real Gotenberg sidecar converts small committed DOCX and PPTX fixtures.
- Local Compose health check reaches Gotenberg and web.
- Full verification runs unit tests, compile check, lint, Docker web build, and Compose conversion smoke test.

## Documentation Changes

- Add root README capability matrix matching this contract.
- Document CLI course-state filter and platform-specific QoL.
- Document web video and conversion controls.
- Replace single-container Cloud Run instructions with multi-container deployment.
- Document local Compose startup and Gotenberg resource needs.
- Update `cli/README.md` to defer to canonical root instructions instead of maintaining divergent feature claims.

## Acceptance Criteria

- Both interfaces fetch and filter active and archived courses.
- Both include videos by default and can exclude them.
- Both use one shared export, filename, validation, and deduplication policy.
- Both expose Word and PowerPoint conversion plus keep/replace choice.
- Web uses private same-instance Gotenberg; CLI uses local LibreOffice.
- Conversion failure never loses original.
- Web validates selected file membership and remains stateless across requests.
- CLI retains dry-run, output-directory, persistent-index, atomic-write, and course-selection behavior.
- Partial item failures are visible through shared report semantics.
- Existing OAuth behavior and entry points remain compatible.
- Dead duplicate modules are removed.
- Unit, parity, integration, lint, compile, and container checks pass.
