import os

REDIS_URL = os.getenv("CONFIG_REDIS_URL")

SECRET_KEY = os.getenv("CONFIG_SECRET_KEY")
env = os.getenv("ENV")
if env == "local":
    SQLALCHEMY_DATABASE_URI = os.getenv("CONFIG_SQLALCHEMY_DATABASE_URI_LOCAL")
else:
    SQLALCHEMY_DATABASE_URI = os.getenv("CONFIG_SQLALCHEMY_DATABASE_URI_DOCKER")

BASE_URL = os.getenv("CONFIG_BASE_URL")
REDIRECT_URL = os.path.join(BASE_URL, "auth/callback")

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