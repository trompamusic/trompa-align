import os
import logging
from dataclasses import asdict, is_dataclass
from logging.config import dictConfig

import flask
import sentry_sdk
from celery import Celery, Task
from celery.result import AsyncResult
from flask import current_app, jsonify, redirect, request, url_for
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.flask import FlaskIntegration
from solidauth import client
import solidauth

from trompaalign import celery_serializers  # noqa: F401
from trompaalign import extensions, tasks
from trompaalign.solid import (
    SolidError,
    get_storage_from_profile,
    lookup_provider_from_profile,
    upload_midi_to_pod,
    upload_webmidi_to_pod,
)


logger = logging.getLogger(__name__)


def celery_init_app(app: flask.Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.autodiscover_tasks(["trompaalign"], force=True)
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app


def configure_logging():
    print("Configuring logging")
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
                }
            },
            "handlers": {
                "wsgi": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://flask.logging.wsgi_errors_stream",
                    "formatter": "default",
                },
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                },
            },
            "root": {"level": "INFO", "handlers": ["wsgi"]},
            "loggers": {
                "trompaalign": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
            },
        }
    )


def create_app():
    configure_logging()
    app = flask.Flask(__name__, static_folder="/clara/static")
    app.config.from_pyfile("../config.py")
    extensions.db.init_app(app)
    extensions.redis_client.init_app(app)
    extensions.backend.init_app(app)
    extensions.cors.init_app(app)

    if app.config["SENTRY_DSN"]:
        sentry_sdk.init(
            dsn=app.config["SENTRY_DSN"],
            integrations=[
                FlaskIntegration(),
                CeleryIntegration(),
            ],
            traces_sample_rate=1.0,
        )

    with app.app_context():
        # On startup, generate keys if they don't exist
        if extensions.backend.backend.is_ready():
            if not extensions.backend.backend.get_relying_party_keys():
                print("On startup generating new RP keys")
                new_key = solidauth.solid.generate_keys()
                extensions.backend.backend.save_relying_party_keys(new_key)
        else:
            print("Warning: Backend isn't ready yet")

    celery_init_app(app)
    return app


webserver_bp = flask.Blueprint("trompaalign", __name__)


def get_client_id_document_url_if_configured():
    if current_app.config["ALWAYS_USE_CLIENT_URL"]:
        return current_app.config["CLIENT_ID_DOCUMENT_URL"]
    else:
        return None


@webserver_bp.route("/clara.jsonld")
def clara_jsonld():
    # In Solid-OIDC you can register a client by having the "client_id" field be a URL to a json-ld document
    # It's normally recommended that this is a static file, but for simplicity serve it from flask

    baseurl = current_app.config["BASE_URL"]
    if not baseurl.endswith("/"):
        baseurl += "/"

    client_information = {
        "@context": ["https://www.w3.org/ns/solid/oidc-context.jsonld"],
        "client_id": baseurl + "clara.jsonld",
        **current_app.config["CLIENT_REGISTRATION_DATA"],
    }

    response = jsonify(client_information)
    response.content_type = "application/ld+json"
    return response


@webserver_bp.route("/clara-backend.jsonld")
@webserver_bp.route("/clara-backend<string:suffix>.jsonld")
def clara_backend_jsonld(suffix=""):
    # In Solid-OIDC you can register a client by having the "client_id" field be a URL to a json-ld document
    # It's normally recommended that this is a static file, but for simplicity serve it from flask

    baseurl = current_app.config["BASE_URL"]
    if baseurl.endswith("/"):
        baseurl = baseurl[:-1]

    client_information = {
        "@context": ["https://www.w3.org/ns/solid/oidc-context.jsonld"],
        "client_id": baseurl + url_for("trompaalign.clara_backend_jsonld", suffix=suffix),
        **current_app.config["CLIENT_REGISTRATION_DATA"],
    }

    response = jsonify(client_information)
    response.content_type = "application/ld+json"
    return response


@webserver_bp.route("/api/auth/request", methods=["POST"])
def auth_request():
    webid = request.form.get("webid_or_provider")
    redirect_after = request.form.get("redirect_after")

    # This redirect URL is the react app: It will receive the code and state, and then perform an API request
    # to /api/auth/callback
    redirect_url = flask.current_app.config["REDIRECT_URL_BACKEND"]
    client_id_document_url = get_client_id_document_url_if_configured()

    use_client_id_document = current_app.config["ALWAYS_USE_CLIENT_URL"]

    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=use_client_id_document)

    # if we always use a client url, generate the url and pass it to generate_authentication_url
    # if it fails with ClientIDDocumentRegistrationNotSupportedError then we need to do dynamic registration
    # this means we need to pass registration_request (current_app.config["CLIENT_REGISTRATION_DATA"]) and client_id_document_url=None
    # if always_use_client_url is False then always do a dynamic registration

    registration_request = current_app.config["CLIENT_REGISTRATION_DATA"]
    try:
        data = cl.generate_authentication_url(webid, registration_request, redirect_url, client_id_document_url)

        provider = data["provider"]
        flask.session["provider"] = provider
        flask.session["redirect_after"] = redirect_after
        log_messages = data.get("log_messages", [])
        print("AUTH LOG")
        for log_message in log_messages:
            print(" ", log_message)

        return jsonify(data)

    except client.NoProviderError as e:
        return jsonify({"error": str(e)}), 400


@webserver_bp.route("/api/auth/callback", methods=["POST"])
def auth_callback():
    auth_code = flask.request.form.get("code")
    state = flask.request.form.get("state")

    provider = flask.session["provider"]

    redirect_url = flask.current_app.config["REDIRECT_URL"]
    client_id_document_url = get_client_id_document_url_if_configured()
    always_use_client_url = flask.current_app.config["ALWAYS_USE_CLIENT_URL"]
    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=always_use_client_url)
    success, data = cl.authentication_callback(auth_code, state, provider, redirect_url, client_id_document_url)
    return jsonify({"status": success, "data": data})


@webserver_bp.route("/api/auth/callback-backend", methods=["GET"])
def auth_callback_backend():
    print(flask.request.args)
    auth_code = flask.request.args.get("code")
    state = flask.request.args.get("state")

    provider = flask.request.args.get("iss")
    if not provider and "provider" in flask.session:
        provider = flask.session["provider"]
    if not provider:
        print("No provider found in session or args")
        return "No provider found", 400

    redirect_url = flask.current_app.config["REDIRECT_URL_BACKEND"]
    client_id_document_url = get_client_id_document_url_if_configured()
    always_use_client_url = flask.current_app.config["ALWAYS_USE_CLIENT_URL"]
    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=always_use_client_url)
    success, data = cl.authentication_callback(auth_code, state, provider, redirect_url, client_id_document_url)

    print("AUTH CALLBACK BACKEND")
    print("auth_code", auth_code)
    print("state", state)
    print("provider", provider)
    print("redirect_url", redirect_url)
    print("client_id_document_url", client_id_document_url)
    print("success", success)
    print("data", data)

    redirect_after = flask.session.get("redirect_after")
    print("redirect_after", redirect_after)

    if success and redirect_after:
        return redirect(redirect_after)
    elif success:
        return redirect("/")
    else:
        return "Error when doing callback", 500


@webserver_bp.route("/api/check_user_perms")
def check_user_perms():
    """Check if the given user has permissions in the backend to"""
    profile_url = request.args.get("profile")
    if not profile_url:
        return jsonify({"status": "error"}), 400

    provider = lookup_provider_from_profile(profile_url)
    always_use_client_url = flask.current_app.config["ALWAYS_USE_CLIENT_URL"]
    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=always_use_client_url)
    try:
        # Get an access token, and if it exists then also check that it hasn't expired.
        # if it expired, try and refresh it and return an error if that fails.
        cl.get_valid_access_token(provider, profile_url)
        has_permission = True
    except client.NoSuchAuthenticationError:
        has_permission = False
    except client.TokenRefreshFailed:
        has_permission = False
        # Token refresh failed, so we should delete the authentication and force the user to re-authenticate.
        extensions.backend.backend.delete_configuration_token(provider, profile_url, always_use_client_url)

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
            return jsonify({"status": "error", "error": str(result.result)})
        else:
            # An unknown failure mode
            print("Unknown failure mode", result.result)
            print(result.traceback)
            sentry_sdk.capture_exception(result.result)
            return jsonify({"status": "unknown", "error": str(result.result)})
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
    file = request.files.get("file")
    payload = file.read()
    midi_type = request.form.get("midi_type")
    score_url = request.form.get("score")
    profile = request.form.get("profile")

    provider = lookup_provider_from_profile(profile)
    storage = get_storage_from_profile(profile)
    use_client_id_document = flask.current_app.config["ALWAYS_USE_CLIENT_URL"]
    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=use_client_id_document)

    print("Uploading file")
    if midi_type == "webmidi":
        webmidi_url = upload_webmidi_to_pod(cl, provider, profile, storage, payload)
        midi_url = None
    elif midi_type == "midi":
        midi_url = upload_midi_to_pod(cl, provider, profile, storage, payload)
        webmidi_url = None
    else:
        return jsonify({"status": "error", "message": "Must have midi_type of webmidi or midi"}), 400

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
            return jsonify({"status": "error", "error": str(result.result)})
        if isinstance(result.result, tasks.AlignmentFailed):
            return jsonify({"status": "error", "error": str(result.result), "midi_url": result.result.midi_url})
        else:
            # An unknown failure mode
            print("Unknown failure mode", result.result)
            print(result.traceback)
            sentry_sdk.capture_exception(result.result)
            return jsonify({"status": "unknown", "error": str(result.result)})
    else:
        if result.ready():
            # Finished
            payload = result.result
            response = {"status": "ok"}
            if payload is None:
                return jsonify(response)
            if is_dataclass(payload):
                response.update(asdict(payload))
                return jsonify(response)
            logger.error(
                "Unexpected payload type returned from align_recording task: %s",
                type(payload),
            )
            return jsonify(response)
        else:
            # Still running
            return jsonify({"status": "pending"})


@webserver_bp.route("/", defaults={"path": "index.html"})
@webserver_bp.route("/<path:path>")
def catch_all(path):
    if "/" not in path:
        user_path = ""
        user_file = path
    else:
        user_path, user_file = path.rsplit("/", 1)
    if os.path.exists(os.path.join(os.path.join("/clara", user_path), user_file)):
        return flask.send_from_directory(os.path.join("/clara", user_path), user_file)
    else:
        return flask.send_from_directory("/clara", "index.html")
