# Google Classroom Auto File Downloader

Fork of [Evani Menon's original project](https://github.com/evanimenon/google-classroom-downloader), published under the MIT License. This fork adds stronger filename and path handling, atomic downloads, safer Drive export and PDF conversion, resilient MIME handling, regression tests, an improved web download flow, and full feature parity between the web app and the CLI.

Automatically download all attachments (assignments, materials, links, PDFs, Docs, Slides, etc.) from your Google Classroom courses using the official Google Classroom + Drive APIs.

---
<img width="1496" height="934" alt="Screenshot 2025-11-30 at 11 49 51" src="https://github.com/user-attachments/assets/dbb28418-cc97-49e0-8400-b87227a8c655" />


## Features

| Scope | Features |
| --- | --- |
| Shared | active/archived/all filters, Drive exports, video option, Word/PowerPoint conversion, keep/replace, retries, reports |
| Web only | per-file selection, stateless ZIP, Gotenberg |
| CLI only | course selection, base directory, dry-run, persistent index, local LibreOffice |

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

Downloads will appear under:

```
downloads/
    <Course Name>/
        file1.pdf
        file2.docx
```

### Advanced Usage (CLI-only flags)

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

## !!! Security Warning for Contributors !!!

This script uses OAuth tokens.  
**NEVER upload these files to GitHub:**

- `credentials.json`  
- `token.json`  
- `download_index.json`  

The provided `.gitignore` already protects you.

!!! If you accidentally commit these files, revoke the OAuth credential immediately and re-generate it. !!!

---
