import flask
from celery import Celery, Task
from celery.result import AsyncResult
from flask import jsonify, Flask, request
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from trompasolid.backend.db_backend import DBBackend

from trompaalign import extensions, tasks
from trompaalign import log
from trompasolid import client

from trompaalign.solid import SolidError


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
    client.set_backend(DBBackend(extensions.db.session))

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


@webserver_bp.route("/add/status")
def add_score_status():
    task_id = request.args.get("task")
    if not task_id:
        return jsonify({"status": "error", "message": "Missing `task` parameter"}), 400

    result = AsyncResult(task_id)
    if result.failed():
        if isinstance(result.result, SolidError):
            # This is a known failure mode, one of our custom exceptions
            return jsonify({"status": "error", "container": str(result.result)})
        else:
            # An unknown failure mode
            return jsonify({"status": "unknown", "container": str(result.result)})
    else:
        if result.ready():
            # Finished
            return jsonify({"status": "ok", "container": result.result})
        else:
            # Still running
            return jsonify({"status": "pending"})


@webserver_bp.route("/add", methods=["POST"])
def add_score():
    score_url = request.values.get("score")
    title = request.values.get("title")
    profile = request.values.get("profile")

    if not score_url:
        return jsonify({"status": "error", "message": "Missing `score` parameter"}), 400
    if not profile:
        return jsonify({"status": "error", "message": "Missing `profile` parameter"}), 400

    task = tasks.add_score.delay(profile, score_url, title)
    return jsonify({"status": "queued", "task_id": task.task_id})


@webserver_bp.route("/align")
def align():
    score = request.args.get('score')
    performance = request.args.get('performance')
    webid = request.args.get('webid')
    provider = request.args.get('provider')

    tasks.align.delay(score, performance, provider, webid)
    return jsonify({"status": "ok"})