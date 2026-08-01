# Google Classroom Auto File Downloader (CLI)

See [../README.md](../README.md) for the canonical documentation: features, Google OAuth setup, local Compose run, and Cloud Run deployment.

## Installation

```bash
cd cli
pip install -r requirements.txt
```

(Optional virtual environment)

```bash
python3 -m venv venv
source venv/bin/activate   # macOS / Linux
# OR
venv\Scripts\activate      # Windows
```

## Credentials

Place your OAuth desktop client JSON at `cli/credentials.json` before first run (see the "Google OAuth Setup (One-Time)" section in the [root README](../README.md)). On first run a browser window asks you to log in and approve permissions; `token.json` is generated automatically.

## Running

```bash
python classroom_downloader.py
```

Downloads appear under `downloads/<Course Name>/`.

## CLI-only flags

| Flag | Description |
| --- | --- |
| `--base-dir PATH` | Base directory where files are saved (default: `./downloads`) |
| `--course-name-contains TEXT` | Only download from courses whose name contains this substring (case-insensitive) |
| `--course-state STATE` | Filter courses by state: `active`, `archived`, or `all` (default: `all`) |
| `--dry-run` | List what would be downloaded without downloading |

Example:

```bash
python classroom_downloader.py --course-state archived
```
