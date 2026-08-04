import os
import json
import logging
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.downloads import prepare_download
from app.oauth import get_flow, SCOPES
from app.zipstreamer import stream_zip
from gcr_downloader.catalog import (
    CatalogError,
    get_course,
    list_course_files,
    list_courses,
    select_course_files,
)
from gcr_downloader.models import DownloadOptions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SESSION_SECRET = os.environ.get("SESSION_SECRET")
IS_CLOUD_RUN = os.environ.get("K_SERVICE") is not None

if not SESSION_SECRET:
    if IS_CLOUD_RUN:
        raise RuntimeError("SESSION_SECRET not set")
    SESSION_SECRET = "dev-secret"

app = FastAPI()

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

IS_LOCAL = os.environ.get("K_SERVICE") is None

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="classroom_session_v5",
    same_site="none" if not IS_LOCAL else "lax",
    https_only=not IS_LOCAL,
)

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def home():
    return RedirectResponse("/login")


@app.get("/login")
def login(request: Request):
    request.session.clear()

    try:
        flow = get_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )

        request.session["state"] = state

        return RedirectResponse(auth_url)

    except Exception:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="Login failed")


@app.get("/callback")
def oauth_callback(request: Request):
    state = request.session.get("state")
    if not state:
        return RedirectResponse("/login")

    try:
        flow = get_flow(state=state)
        flow.fetch_token(authorization_response=str(request.url))

        request.session["token"] = json.loads(flow.credentials.to_json())

        return RedirectResponse("/courses")

    except Exception:
        logger.exception("OAuth callback failed")
        return RedirectResponse("/login")


@app.get("/courses")
def courses(request: Request):
    if "token" not in request.session:
        return RedirectResponse("/login")

    creds = Credentials.from_authorized_user_info(request.session["token"], SCOPES)

    classroom = build("classroom", "v1", credentials=creds)
    try:
        courses = list_courses(classroom, state="all")
        error_message = None
    except CatalogError as exc:
        logger.warning("Failed to load courses: %s", exc)
        courses = []
        error_message = str(exc)

    return templates.TemplateResponse(
        "courses.html",
        {
            "request": request,
            "courses": courses,
            "error": error_message,
        },
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@app.post("/download")
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
