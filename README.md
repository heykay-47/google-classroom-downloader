# Google Classroom Auto File Downloader

Fork of [Evani Menon's original project](https://github.com/evanimenon/google-classroom-downloader), published under the MIT License. This fork adds stronger filename and path handling, atomic downloads, safer Drive export and PDF conversion, resilient MIME handling, regression tests, an improved web download flow, and full feature parity between the web app and the CLI.

Automatically download all attachments (assignments, materials, links, PDFs, Docs, Slides, etc.) from your Google Classroom courses using the official Google Classroom + Drive APIs.

---
<img width="1496" height="934" alt="Screenshot 2025-11-30 at 11 49 51" src="https://github.com/user-attachments/assets/dbb28418-cc97-49e0-8400-b87227a8c655" />


## Features

| Scope | Features |
| --- | --- |
| Shared | active/archived/all filters, Drive exports, video option, Word/PowerPoint conversion, keep/replace, retries, reports |
| Web only | course search/state filters, grouped file drawer with type filter, per-file selection, remembered local options, stateless ZIP, Gotenberg, preparation feedback |
| CLI only | course selection, base directory, dry-run, per-file progress, resumable index, safer OAuth recovery, local LibreOffice |

---

## Project Structure

```
google-classroom-downloader/
│
├── app/                     # Cloud Run web app (FastAPI)
├── cli/                     # Local CLI downloader
│   └── classroom_downloader.py
├── gcr_downloader/          # Shared catalog, file policy, and models
├── deploy/                  # Cloud Run multi-container config and renderer
├── tests/                   # Unit, parity, and integration tests
├── docs/                    # Legal / public website and design specs
└── README.md                # Project root README
```

---

## Installation (CLI)

### 1. Clone this repository

```bash
git clone https://github.com/heykay-47/google-classroom-downloader.git
cd google-classroom-downloader/cli
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

(Optional virtual environment)

```bash
python3 -m venv venv
source venv/bin/activate   # macOS / Linux
# OR
venv\Scripts\activate      # Windows
```

---

## Google OAuth Setup (One-Time)

Follow these steps carefully.

### 1. Open Google Cloud Console
[https://console.cloud.google.com/](https://console.cloud.google.com/)

<img width="1446" height="893" alt="Screenshot 2025-11-30 at 01 57 31" src="https://github.com/user-attachments/assets/d695f9a7-6bac-422e-872e-54da2210b76d" />


### 2. Create a New Project
**IAM & Admin → Create Project**
Project name: `Classroom Downloader`
<img width="1446" height="891" alt="Screenshot 2025-11-30 at 02 01 39" src="https://github.com/user-attachments/assets/7997fa7a-d279-4ec6-bfad-b1ea076c255a" />


### 3. Enable APIs

Go to: **APIs & Services → Enable APIs & Services**

Enable:

* **Google Classroom API**
* **Google Drive API**
<img width="1444" height="891" alt="Screenshot 2025-11-30 at 02 03 16" src="https://github.com/user-attachments/assets/2028fdd2-322d-44a7-b31f-287ab0a91eeb" />

### 4. Configure OAuth Consent Screen

Left sidebar → **OAuth consent screen**

* User Type: **External**
* App Name: `Classroom Downloader`
* Add your email under **Test Users**
* Save

### 5. Create OAuth Desktop Credentials

Left sidebar → **APIs and Services → OAuth Consent Screen → Clients → Create Client**

* Application type: **Desktop App**
* Name: `Classroom Desktop`
* Click **Download JSON**
<img width="1447" height="892" alt="Screenshot 2025-11-30 at 02 03 54" src="https://github.com/user-attachments/assets/bea31c22-dfca-4484-b020-95c4e51e2267" />

Rename the downloaded file to:

```
credentials.json
```

Place it inside:

```
google-classroom-downloader/cli/credentials.json
```

---

## Running the Downloader (CLI)

Run:

```bash
python classroom_downloader.py
```

On first run:

* A browser window appears
* Log in with your Google account
* Approve the requested permissions
* `token.json` is generated automatically

The CLI checks that saved credentials include all required Classroom/Drive
permissions. Revoked or expired refresh grants trigger one new consent flow;
network/service failures stop with retry guidance without replacing the saved
token. Cancellation, timeout, and incomplete consent also leave that token intact.

Downloads will appear under:

```
downloads/
    <Course Name>/
        file1.pdf
        file2.docx
```

### Advanced Usage (CLI-only flags)

The CLI saves `download_index.json` in the current working directory after each
file's outcome using a flushed temporary file and atomic replacement. Restart
from the same working directory and download directory to reuse that checkpoint.
The index format is unchanged, including support for legacy file-ID lists.

Press **Ctrl+C** to stop: completed work is checkpointed, a partial summary is
printed, and the CLI exits with code `130`. An interrupted download's partial
file is removed. If conversion is interrupted, the downloaded source is kept for
the next run. A checkpoint write failure stops the run with an error rather than
continuing without durable progress.

If the index is corrupt, an interactive run warns before authentication and asks
whether to preserve a private backup and proceed with an empty index (which may
redownload files). Only an explicit **yes** continues, after the original bytes
are flushed to a unique same-directory `.download_index.json.*.corrupt.bak` backup
and atomically published without replacing any existing backup. The original
index stays untouched until the next checkpoint. If backup creation fails, the
run stops. Declining, noninteractive runs, and corrupt-index dry-runs stop without
authentication or writes. You can instead repair the index manually. Backups may
contain private filenames: keep them private (Windows inherits directory access
controls); Git and Docker ignore these backups and temporary index files.
**Dry-run** does not write the index, create download directories, convert files,
or delete duplicates.

Progress shows each selected course's position and discovered-file count, then
each file's position and outcome (downloaded, converted, skipped, or failed with
a reason). These are file counts, not byte-transfer percentages. Dry-run outcomes
are labelled planned rather than completed; Ctrl+C still prints a partial summary.

Download only archived courses:

```bash
python classroom_downloader.py --course-state archived
```

Download only one course:

```bash
python classroom_downloader.py --course-name-contains "CSE201"
```

Run without downloading (simulation):

```bash
python classroom_downloader.py --dry-run
```

Change download directory:

```bash
python classroom_downloader.py --base-dir "/Users/me/ClassroomFiles"
```

---

## Web App — Local Run (Compose)

`compose.yaml` starts the web app plus a private [Gotenberg](https://gotenberg.dev) sidecar (pinned `gotenberg/gotenberg:8.34.0-libreoffice`, not exposed to the host) for Word and PowerPoint conversion.

`GOOGLE_OAUTH_JSON` is **required** in the environment (the web app refuses to start without it). `SESSION_SECRET` is optional locally and defaults to `dev-secret`.

```bash
GOOGLE_OAUTH_JSON='{"web":{...}}' docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) and sign in. The compose file sets `REDIRECT_URI` to `http://localhost:8080/callback`; make sure that URI is registered as an authorized redirect URI on your OAuth client.

### Web file selection and download feedback

- Course search and active/archived/all filters help locate a course. Download
  options (skip videos, Word/PowerPoint conversion, and replace originals) are
  remembered locally in this browser, not synced to Google or another device.
  Replace originals is disabled and cleared unless a conversion is enabled. If
  local storage is unavailable, the page still works with defaults. Course filters
  and file selections are not persisted.
- The file drawer groups attachments by assignment, material, or announcement and
  shows available post titles/dates. The file-type filter narrows the
  view; file type is inferred from the filename extension, not verified MIME data.
  Unknown metadata is labelled rather than guessed.
- Per-post select/clear buttons affect only visible matching files. Course-wide
  controls affect the entire course. Hidden selected files remain selected and are
  included in the displayed count and download. Escape closes the drawer and
  keyboard focus stays within it while open.
- Submitting shows **Preparing N files…** and elapsed time, blocks repeat submits,
  and surfaces preparation/session errors with retry guidance. A request-specific
  status cookie acknowledges response readiness, **not** a completed browser save;
  check your browser's downloads for transfer/save status. Authentication cookies
  remain HttpOnly; only the non-sensitive readiness cookie is JavaScript-readable.
- After five minutes the controls recover without claiming to cancel server work.
  Each request carries its original absolute deadline, so even a late response
  cannot leave a fresh five-minute status cookie. Check browser downloads before
  retrying; no server-side progress registry is used.

To run the integration smoke test against the local Gotenberg container:

```bash
GOOGLE_OAUTH_JSON='{"web":{}}' docker compose up -d --wait gotenberg
docker build -t classroom-downloader:test .
docker run --rm --network gcr-downloader_default \
  -v "$PWD/tests:/app/tests:ro" \
  -e GOTENBERG_URL=http://gotenberg:3000 \
  -e GOTENBERG_INTEGRATION=1 \
  classroom-downloader:test \
  python -m unittest discover -s tests -p 'test_gotenberg_integration.py' -v
GOOGLE_OAUTH_JSON='{"web":{}}' docker compose down
```

## Web App Deployment (Cloud Run)

The service runs two containers: the web app (port `8080`) and the Gotenberg sidecar (port `3000`, instance-local only).

### Required Secret Manager secrets

The rendered service reads both secrets with key `latest`:

| Secret name | Contents |
| --- | --- |
| `classroom-session-secret` | Random secret used to sign session cookies |
| `google-oauth-json` | Web OAuth client JSON string |

### OAuth callback URI

The app's default redirect URI is `https://classroom-downloader-web-936773451602.asia-south1.run.app/callback`. Register it as an authorized redirect URI on the OAuth client, or set the `REDIRECT_URI` environment variable to match your own domain's `/callback` URL.

### Build the web image, render, and deploy

```bash
docker build -t "$WEB_IMAGE" .
docker push "$WEB_IMAGE"

python deploy/render_cloud_run.py --web-image "$WEB_IMAGE"
gcloud run services replace deploy/cloud-run-service.rendered.yaml --region asia-south1
```

`deploy/render_cloud_run.py` substitutes your image reference into `deploy/cloud-run-service.yaml` and writes `deploy/cloud-run-service.rendered.yaml`. The rendered service sets `GOTENBERG_URL=http://localhost:3000` on the web container and configures concurrency `1`, a `900s` timeout, and a startup probe on Gotenberg.

---

## Development checks

GitHub Actions runs unit tests and Ruff on **Python 3.12**, plus JavaScript
behavior checks on **Node.js 24**, for every push and pull request. Install both
runtimes locally (with `node` on PATH: Python discovery also invokes the download
controller's Node check). From the repository root:

### WSL / Linux / macOS (bash)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/check_download_status.js
node --test tests/web_preferences.test.cjs
python -m ruff check .
```

For a checkout under `/mnt/c` in WSL, put the Linux virtual environment on the
Linux filesystem instead (for example, `~/.venvs/gcr-downloader`) and activate
that path. Keep Linux and native Windows virtual environments separate.

### Native Windows (PowerShell, without activation)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/check_download_status.js
node --test tests/web_preferences.test.cjs
.\.venv\Scripts\python.exe -m ruff check .
```

The unit tests use stubs/mocks and need no Google credentials, Docker, or live
services. Leave `GOTENBERG_INTEGRATION` unset (or set it to `0`) for these checks;
the Gotenberg smoke test is skipped by default. To explicitly run it against a
real sidecar, follow the opt-in Compose instructions above.

For opt-in Chromium drawer verification, install `agent-browser`, then set
`GCR_BROWSER_TESTS=1` and run discovery for `test_web_drawer_browser.py`. The test
requires the real Tailwind CSS to load and checks the drawer's computed fixed
position before viewport assertions. For offline/reliable styling, set
`GCR_BROWSER_TAILWIND_JS` to a local copy of the page's exact Tailwind CDN script;
the fixture serves it locally. Set `GCR_BROWSER_OUTPUT_DIR` to retain screenshots
and a browser snapshot in a directory of your choice; otherwise temporary output
is cleaned up automatically. This browser check is separate from default CI.

Ruff is pinned in `requirements-dev.txt`; `.ruff.toml` keeps the existing rule
baseline and per-file exceptions explicit. CI installs dependencies from the
package index but does not authenticate to Google or deploy anything.

---

## !!! Security Warning for Contributors !!!

This script uses OAuth tokens.  
**NEVER upload these files to GitHub:**

- `credentials.json`  
- `token.json`  
- `download_index.json`  
- `.download_index.json.*.corrupt.bak` (private corrupt-index backups)

The provided `.gitignore` already protects you.

!!! If you accidentally commit these files, revoke the OAuth credential immediately and re-generate it. !!!

---
