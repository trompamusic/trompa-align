import os

from celery.schedules import crontab

REDIS_URL = os.getenv("TR_ALIGN_REDIS_URL")

SECRET_KEY = os.getenv("TR_ALIGN_SECRET_KEY")
SQLALCHEMY_DATABASE_URI = os.getenv("TR_ALIGN_SQLALCHEMY_DATABASE_URI")

BASE_URL = os.getenv("TR_ALIGN_BASE_URL")
REDIRECT_URL_BACKEND = os.path.join(BASE_URL, "api/auth/callback-backend")
REDIRECT_URLS = [BASE_URL, REDIRECT_URL_BACKEND]

# If a client id document url is specified then use it with the oidc client
# otherwise the client will use dynamic registration.
CLIENT_ID_DOCUMENT_URL = os.getenv("TR_ALIGN_CLIENT_ID_DOCUMENT_URL") or None

SENTRY_DSN = os.getenv("TR_ALIGN_SENTRY_DSN")

CELERY = {
    "broker_url": REDIS_URL,
    "result_backend": REDIS_URL,
    "task_ignore_result": True,
    "task_serializer": "json",
    "result_serializer": "dataclass-json",
    "accept_content": ["json", "dataclass-json"],
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
    # Browser authentication returns to the React app.
    CLIENT_REGISTRATION_DATA["redirect_uris"].extend(["http://localhost:3000"])

# TODO: Dynamic registration from solid-oidc originally included these additional fields:
#  grant_types: client_credentials  -  at least one provider (Redpencil) fails if we send this
#  "token_endpoint_auth_method": "client_secret_basic",   -   not sure what this represents or if it's necessary
#  We should also confirm with the provider's supported features that we send the correct data
