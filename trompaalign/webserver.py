import flask
from celery import Celery, Task
from flask import jsonify, Flask, request
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

from trompaalign import extensions, tasks
from trompaalign import log
from trompasolid import client


def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.autodiscover_tasks(['trompaalign'], force=True)
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app


def create_app():
    app = flask.Flask(__name__)
    app.config.from_pyfile("../config.py")
    extensions.db.init_app(app)
    extensions.redis_client.init_app(app)
    extensions.backend.init_app(app)
    client.set_backend(extensions.db.session)

    if app.config['SENTRY_DSN']:
        sentry_sdk.init(
            dsn=app.config['SENTRY_DSN'],
            integrations=[
                FlaskIntegration(),
                CeleryIntegration(),
            ],
            traces_sample_rate=1.0
        )

    celery_init_app(app)
    log.logger.info("Webapp started")
    return app


webserver_bp = flask.Blueprint('trompaalign', __name__)


@webserver_bp.route("/")
def index():
    return jsonify({"status": "ok"})
