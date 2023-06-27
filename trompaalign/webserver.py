import os
import flask
from celery import Celery, Task
from celery.result import AsyncResult
import sentry_sdk
from flask import request, jsonify
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from trompasolid.authentication import generate_authentication_url, NoProviderError, authentication_callback
from trompasolid.backend.db_backend import DBBackend

from trompaalign import extensions, tasks
from trompasolid import client

from trompaalign.solid import SolidError, lookup_provider_from_profile, upload_webmidi_to_pod, upload_midi_to_pod, \
    get_storage_from_profile


def celery_init_app(app: flask.Flask) -> Celery:
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
    app = flask.Flask(__name__, static_folder="/clara/static")
    app.config.from_pyfile("../config.py")
    extensions.db.init_app(app)
    extensions.redis_client.init_app(app)
    extensions.backend.init_app(app)
    extensions.cors.init_app(app)
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
    return app


webserver_bp = flask.Blueprint('trompaalign', __name__)


@webserver_bp.route("/api/auth/request", methods=["POST"])
def auth_request():
    webid = request.form.get("webid_or_provider")
    redirect_after = request.form.get("redirect_after")

    redirect_url = flask.current_app.config['REDIRECT_URL']
    always_use_client_url = flask.current_app.config['ALWAYS_USE_CLIENT_URL']
    try:
        data = generate_authentication_url(extensions.backend.backend, webid, redirect_url, always_use_client_url)

        provider = data['provider']
        flask.session['provider'] = provider
        flask.session['redirect_after'] = redirect_after
        log_messages = data.get('log_messages', [])
        print("AUTH LOG")
        for log_message in log_messages:
            print(" ", log_message)

        return jsonify(data)

    except NoProviderError as e:
        return jsonify({"error": str(e)}), 400


@webserver_bp.route("/api/auth/callback", methods=["POST"])
def auth_callback():
    auth_code = flask.request.form.get('code')
    state = flask.request.form.get('state')

    provider = flask.session['provider']

    redirect_uri = flask.current_app.config['REDIRECT_URL']
    always_use_client_url = flask.current_app.config['ALWAYS_USE_CLIENT_URL']
    success = authentication_callback(extensions.backend.backend, auth_code, state, provider, redirect_uri,
                                      always_use_client_url)

    return jsonify({"status": success})


@webserver_bp.route("/api/check_user_perms")
def check_user_perms():
    """Check if the given user has permissions in the backend to """
    profile_url = request.args.get("profile")
    if not profile_url:
        return jsonify({"status": "error"}), 400

    provider = lookup_provider_from_profile(profile_url)
    configuration = extensions.backend.backend.get_configuration_token(issuer=provider, profile=profile_url)
    has_permission = configuration is not None

    return jsonify({"has_permission": has_permission})


@webserver_bp.route("/api/add/status")
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


@webserver_bp.route("/api/add", methods=["POST"])
def add_score():
    score_url = request.json.get("score")
    profile = request.json.get("profile")

    if not score_url:
        return jsonify({"status": "error", "message": "Missing `score` parameter"}), 400
    if not profile:
        return jsonify({"status": "error", "message": "Missing `profile` parameter"}), 400

    task = tasks.add_score.delay(profile, score_url)
    return jsonify({"status": "queued", "task_id": task.task_id})


@webserver_bp.route("/api/align", methods=["POST"])
def align():
    file = request.files.get('file')
    payload = file.read()
    midi_type = request.form.get('midi_type')
    score_url = request.form.get('score')
    profile = request.form.get('profile')

    print("MIDI TYPE", midi_type)
    print("SCORE URL", score_url)
    print("PROFILE", profile)
    #webmidi_url = request.args.get('webmidi_url')
    #midi_url = request.args.get('midi_url')

    # if webmidi_url and midi_url:
    #     return jsonify({"status": "error", "message": "Must have only one of webmidi_url or midi_url"}), 400

    provider = lookup_provider_from_profile(profile)
    storage = get_storage_from_profile(profile)

    print("Uploading file")
    if midi_type == "webmidi":
        webmidi_url = upload_webmidi_to_pod(provider, profile, storage, payload)
        midi_url = None
    elif midi_type == "midi":
        midi_url = upload_midi_to_pod(provider, profile, storage, payload)
        webmidi_url = None
    else:
        return jsonify({"status": "error", "message": "Must have midi_type of webmidi or midi"}), 400

    # profile, score_url, webmidi_url, midi_url
    task = tasks.align_recording.delay(profile, score_url, webmidi_url, midi_url)
    print("made task", task.task_id)
    return jsonify({"status": "queued", "task_id": task.task_id})


@webserver_bp.route("/api/align/status")
def align_status():
    task_id = request.args.get("task")
    if not task_id:
        return jsonify({"status": "error", "message": "Missing `task` parameter"}), 400

    result = AsyncResult(task_id)
    if result.failed():
        if isinstance(result.result, SolidError):
            # This is a known failure mode, one of our custom exceptions
            return jsonify({"status": "error", "message": str(result.result)})
        else:
            # An unknown failure mode
            return jsonify({"status": "unknown", "message": str(result.result)})
    else:
        if result.ready():
            # Finished
            return jsonify({"status": "ok", "message": result.result})
        else:
            # Still running
            return jsonify({"status": "pending"})


@webserver_bp.route('/', defaults={'path': 'index.html'})
@webserver_bp.route('/<path:path>')
def catch_all(path):
    if "/" not in path:
        user_path = ""
        user_file = path
    else:
        user_path, user_file = path.rsplit("/", 1)
    return flask.send_from_directory(os.path.join('/clara', user_path), user_file)
