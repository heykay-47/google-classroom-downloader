import os
import json
from google_auth_oauthlib.flow import Flow
from gcr_downloader.files import SCOPES

REDIRECT_URI = os.environ.get(
    "REDIRECT_URI",
    "https://classroom-downloader-web-936773451602.asia-south1.run.app/callback",
)

if os.environ.get("K_SERVICE") is None:
    import oauthlib.oauth2.rfc6749.parameters as _oauth_parameters
    from oauthlib.oauth2.rfc6749.utils import is_secure_transport as _orig_is_secure_transport

    def _is_secure_transport_allow_loopback(uri):
        if uri and uri.startswith(("http://localhost", "http://127.0.0.1")):
            return True
        return _orig_is_secure_transport(uri)

    _oauth_parameters.is_secure_transport = _is_secure_transport_allow_loopback


def get_flow(state=None):
    client_config_str = os.environ.get("GOOGLE_OAUTH_JSON")
    if not client_config_str:
        raise RuntimeError("GOOGLE_OAUTH_JSON environment variable not set")

    client_config = json.loads(client_config_str)

    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI,
    )
