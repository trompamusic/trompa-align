import os

from celery.schedules import crontab

REDIS_URL = os.getenv("TR_ALIGN_REDIS_URL")

SECRET_KEY = os.getenv("TR_ALIGN_SECRET_KEY")
SQLALCHEMY_DATABASE_URI = os.getenv("TR_ALIGN_SQLALCHEMY_DATABASE_URI")

BASE_URL = os.getenv("TR_ALIGN_BASE_URL")
REDIRECT_URL = os.path.join(BASE_URL, "auth/callback")
REDIRECT_URL_BACKEND = os.path.join(BASE_URL, "api/auth/callback-backend")
# When deployed on production, we can redirect to the react app (base url), or /api/auth/callback (API)
REDIRECT_URLS = [REDIRECT_URL, BASE_URL, REDIRECT_URL_BACKEND]

# When accessing an OP, should you register a client ID ahead of time, or submit a URL?
#  if the OP doesn't support client registration, it'll always submit a URL
ALWAYS_USE_CLIENT_URL = os.getenv("TR_ALIGN_ALWAYS_USE_CLIENT_URL", "true").lower() == "true"
CLIENT_ID_DOCUMENT_URL = os.getenv("TR_ALIGN_CLIENT_ID_DOCUMENT_URL", None)
if ALWAYS_USE_CLIENT_URL and CLIENT_ID_DOCUMENT_URL is None:
    raise ValueError("TR_ALIGN_CLIENT_ID_DOCUMENT_URL must be set if TR_ALIGN_ALWAYS_USE_CLIENT_URL is true")

BACKEND = os.getenv("TR_ALIGN_BACKEND")
if BACKEND not in ["redis", "db"]:
    raise ValueError("TR_ALIGN_BACKEND must be 'redis' or 'db'")

SENTRY_DSN = os.getenv("TR_ALIGN_SENTRY_DSN")

CELERY = {
    "broker_url": REDIS_URL,
    "result_backend": REDIS_URL,
    "task_ignore_result": True,
    "beat_schedule": {
        "refresh-all-authentication-tokens": {
            "task": "trompaalign.tasks.refresh_all_authentication_tokens",
            "schedule": crontab(minute=0, hour="0,12"),
        },
    },
}

LOCAL_DEV = os.getenv("TR_ALIGN_LOCAL_DEV") == "true"


CLIENT_REGISTRATION_DATA = {
    "client_name": "Clara",
    "redirect_uris": REDIRECT_URLS,
    "post_logout_redirect_uris": [BASE_URL + "/logout"],
    "client_uri": BASE_URL,
    "logo_uri": BASE_URL + "/logo.png",
    "scope": "openid webid offline_access",
    "grant_types": ["refresh_token", "authorization_code"],
    "response_types": ["code"],
    "default_max_age": 3600,
    "require_auth_time": True,
}

if LOCAL_DEV:
    # React app on :3000 for js auth, and /auth/callback handler to send requests to the backend
    CLIENT_REGISTRATION_DATA["redirect_uris"].extend(["http://localhost:3000", "http://localhost:3000/auth/callback"])

# TODO: Dynamic registration from solid-oidc originally included these additional fields:
#  grant_types: client_credentials  -  at least one provider (Redpencil) fails if we send this
#  "token_endpoint_auth_method": "client_secret_basic",   -   not sure what this represents or if it's necessary
#  We should also confirm with the provider's supported features that we send the correct data
