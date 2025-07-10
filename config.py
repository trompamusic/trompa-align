import os

REDIS_URL = os.getenv("CONFIG_REDIS_URL")

SECRET_KEY = os.getenv("CONFIG_SECRET_KEY")
env = os.getenv("ENV")
if env == "local":
    SQLALCHEMY_DATABASE_URI = os.getenv("CONFIG_SQLALCHEMY_DATABASE_URI_LOCAL")
else:
    SQLALCHEMY_DATABASE_URI = os.getenv("CONFIG_SQLALCHEMY_DATABASE_URI_DOCKER")

BASE_URL = os.getenv("CONFIG_BASE_URL")
REDIRECT_URL = os.path.join(BASE_URL, "api/auth/callback")
# When deployed on production, we can redirect to the react app (base url), or /api/auth/callback (API)
REDIRECT_URLS = [REDIRECT_URL, BASE_URL]

# When accessing an OP, should you register a client ID ahead of time, or submit a URL?
#  if the OP doesn't support client registration, it'll always submit a URL
ALWAYS_USE_CLIENT_URL = False

BACKEND = os.getenv("CONFIG_BACKEND")
if BACKEND not in ["redis", "db"]:
    raise ValueError("CONFIG_BACKEND must be 'redis' or 'db'")

SENTRY_DSN = os.getenv("CONFIG_SENTRY_DSN")

CELERY = {
    "broker_url": REDIS_URL,
    "result_backend": REDIS_URL,
    "task_ignore_result": True,
}

LOCAL_DEV = os.getenv("CONFIG_LOCAL_DEV") == "true"


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
    # React app on :3000, Flask app on :5000
    CLIENT_REGISTRATION_DATA["redirect_uris"].extend(
        ["http://localhost:3000", "http://localhost:5000/api/auth/callback"]
    )

# TODO: Dynamic registration from solid-oidc originally included these additional fields:
#  grant_types: client_credentials  -  at least one provider (Redpencil) fails if we send this
#  "token_endpoint_auth_method": "client_secret_basic",   -   not sure what this represents or if it's necessary
#  We should also confirm with the provider's supported features that we send the correct data
