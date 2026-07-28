import sys
import types


def install_dependency_stubs():
    google_oauth_credentials = types.ModuleType("google.oauth2.credentials")
    google_oauth_credentials.Credentials = type("Credentials", (), {})

    google_auth_flow = types.ModuleType("google_auth_oauthlib.flow")
    google_auth_flow.InstalledAppFlow = type("InstalledAppFlow", (), {})
    google_auth_flow.Flow = type("Flow", (), {})

    google_auth_requests = types.ModuleType("google.auth.transport.requests")
    google_auth_requests.Request = type("Request", (), {})

    google_api_discovery = types.ModuleType("googleapiclient.discovery")
    google_api_discovery.build = lambda *args, **kwargs: None

    google_api_http = types.ModuleType("googleapiclient.http")
    google_api_http.MediaIoBaseDownload = type("MediaIoBaseDownload", (), {})

    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
            self.detail = detail

    class FastAPI:
        def __init__(self):
            self.routes = []

        def add_middleware(self, *args, **kwargs):
            return None

        def _route(self, path):
            self.routes.append(types.SimpleNamespace(path=path))

            def decorator(function):
                return function

            return decorator

        def get(self, path):
            return self._route(path)

        def post(self, path):
            return self._route(path)

    fastapi.FastAPI = FastAPI
    fastapi.Request = type("Request", (), {})
    fastapi.Form = lambda default=None: default
    fastapi.HTTPException = HTTPException

    fastapi_responses = types.ModuleType("fastapi.responses")
    fastapi_responses.RedirectResponse = type("RedirectResponse", (), {})
    fastapi_responses.JSONResponse = type("JSONResponse", (), {})
    fastapi_responses.StreamingResponse = type("StreamingResponse", (), {})

    fastapi_templating = types.ModuleType("fastapi.templating")

    class Jinja2Templates:
        def __init__(self, *args, **kwargs):
            pass

    fastapi_templating.Jinja2Templates = Jinja2Templates

    starlette_sessions = types.ModuleType("starlette.middleware.sessions")
    starlette_sessions.SessionMiddleware = type("SessionMiddleware", (), {})

    proxy_headers = types.ModuleType("uvicorn.middleware.proxy_headers")
    proxy_headers.ProxyHeadersMiddleware = type("ProxyHeadersMiddleware", (), {})

    zipstream = types.ModuleType("zipstream")
    zipstream.ZIP_DEFLATED = 1
    zipstream.ZipFile = type("ZipFile", (), {})

    modules = {
        "google.oauth2.credentials": google_oauth_credentials,
        "google_auth_oauthlib.flow": google_auth_flow,
        "google.auth.transport.requests": google_auth_requests,
        "googleapiclient.discovery": google_api_discovery,
        "googleapiclient.http": google_api_http,
        "fastapi": fastapi,
        "fastapi.responses": fastapi_responses,
        "fastapi.templating": fastapi_templating,
        "starlette.middleware.sessions": starlette_sessions,
        "uvicorn.middleware.proxy_headers": proxy_headers,
        "zipstream": zipstream,
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)
