import datetime
import runpy
from pathlib import Path
from unittest.mock import Mock, call, create_autospec

import pytest
from flask import Flask
from solidauth import model, solid
from solidauth.backend import SolidBackend
from solidauth.client import SolidClient
from solidauth.solid import ProviderConfigurationError

from trompaalign import cli, cli_api, extensions, tasks, webserver

ISSUER = "https://issuer.example"
WEBID = "https://pod.example/profile/card#me"
DOCUMENT = "https://app.example/client.jsonld"
OTHER_DOCUMENT = "https://app.example/other.jsonld"
DYNAMIC = "registered-client"


@pytest.fixture
def backend(monkeypatch):
    backend = create_autospec(SolidBackend, instance=True)
    backend.get_client_registration.return_value = {"client_id": DYNAMIC, "client_secret": "secret"}
    backend.get_resource_server_configuration.return_value = {"issuer": ISSUER, "scopes_supported": ["webid"]}
    monkeypatch.setattr(extensions.backend, "backend", backend, raising=False)
    return backend


@pytest.fixture
def app(backend):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test",
        CLIENT_ID_DOCUMENT_URL=DOCUMENT,
        REDIRECT_URL_BACKEND="https://app.example/api/auth/callback-backend",
        CLIENT_REGISTRATION_DATA={"client_name": "test"},
    )
    app.register_blueprint(webserver.webserver_bp)
    app.cli.add_command(cli.cli)
    app.cli.add_command(cli.db_bp)
    app.cli.add_command(cli_api.cli_api)
    return app


def token(client_id, *, expired=False, dynamic=False):
    return model.TokenResponse(
        issuer=ISSUER,
        webid=WEBID,
        client_id=client_id,
        added=datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2 if expired else 0),
        data={"access_token": client_id, "refresh_token": "refresh", "expires_in": 3600},
        client_registration=(model.ClientRegistration(ISSUER, client_id, {}) if dynamic else None),
    )


@pytest.mark.parametrize("document_url", [None, DOCUMENT, ""])
def test_registration_configuration(monkeypatch, document_url):
    monkeypatch.setenv("TR_ALIGN_BASE_URL", "https://app.example")
    monkeypatch.setenv("TR_ALIGN_LOCAL_DEV", "true")
    if document_url is None:
        monkeypatch.delenv("TR_ALIGN_CLIENT_ID_DOCUMENT_URL", raising=False)
    else:
        monkeypatch.setenv("TR_ALIGN_CLIENT_ID_DOCUMENT_URL", document_url)
    path = Path(__file__).resolve().parents[2] / "config.py"
    config = runpy.run_path(str(path))
    assert config["CLIENT_ID_DOCUMENT_URL"] == (document_url or None)
    assert config["CLIENT_REGISTRATION_DATA"]["redirect_uris"] == [
        "https://app.example",
        "https://app.example/api/auth/callback-backend",
        "http://localhost:3000",
    ]


@pytest.mark.parametrize("document_url", [None, DOCUMENT])
def test_authorization_and_callback_use_same_identity_and_redirect(app, backend, monkeypatch, document_url):
    app.config["CLIENT_ID_DOCUMENT_URL"] = document_url
    constructor = create_autospec(SolidClient)
    monkeypatch.setattr(webserver.client, "SolidClient", constructor)
    client = constructor.return_value
    client.generate_authentication_url.return_value = {"provider": ISSUER, "auth_url": ISSUER + "/authorize"}
    client.authentication_callback.return_value = (True, {})
    browser = app.test_client()
    response = browser.post("/api/auth/request", data={"webid_or_provider": WEBID, "redirect_after": "/select"})
    assert response.status_code == 200
    client.generate_authentication_url.assert_called_once_with(
        WEBID, app.config["CLIENT_REGISTRATION_DATA"], app.config["REDIRECT_URL_BACKEND"]
    )
    response = browser.get("/api/auth/callback-backend", query_string={"code": "code", "state": "state", "iss": ISSUER})
    assert response.status_code == 302
    assert response.location == "/select"
    client.authentication_callback.assert_called_once_with("code", "state", ISSUER, app.config["REDIRECT_URL_BACKEND"])
    assert constructor.call_args_list == [call(backend, client_id_document_url=document_url)] * 2
    assert browser.post("/api/auth/callback").status_code == 405


@pytest.mark.parametrize("endpoint", ["request", "callback-backend"])
def test_provider_configuration_failure_is_reported(app, monkeypatch, endpoint):
    constructor = create_autospec(SolidClient)
    monkeypatch.setattr(webserver.client, "SolidClient", constructor)
    client = constructor.return_value
    client.generate_authentication_url.side_effect = ProviderConfigurationError("invalid provider")
    client.authentication_callback.side_effect = ProviderConfigurationError("invalid provider")
    browser = app.test_client()
    if endpoint == "request":
        response = browser.post("/api/auth/request", data={"webid_or_provider": WEBID})
    else:
        response = browser.get("/api/auth/callback-backend", query_string={"iss": ISSUER})
    assert response.status_code == 400
    assert response.json == {"error": "invalid provider"}
    constructor.assert_called_once()


@pytest.mark.parametrize("document_url", [DOCUMENT, None])
def test_cli_and_normal_task_use_configured_identity(app, backend, monkeypatch, document_url):
    app.config["CLIENT_ID_DOCUMENT_URL"] = document_url
    constructor = create_autospec(SolidClient)
    monkeypatch.setattr(cli.client, "SolidClient", constructor)
    monkeypatch.setattr(cli, "lookup_provider_from_profile", lambda _: ISSUER)
    monkeypatch.setattr(cli, "get_storage_from_profile", lambda _: "https://pod.example/")
    listing = Mock(return_value={"@graph": []})
    monkeypatch.setattr(cli, "get_pod_listing", listing)
    result = app.test_cli_runner().invoke(args=["solid", "list-pod", WEBID])
    assert result.exit_code == 0, result.output
    constructor.assert_called_once_with(backend, client_id_document_url=document_url)
    assert listing.call_args.args[0] is constructor.return_value
    assert "--use-client-id-document" not in app.test_cli_runner().invoke(args=["solid", "list-pod", "--help"]).output
    constructor.reset_mock()
    monkeypatch.setattr(tasks, "lookup_provider_from_profile", lambda _: None)
    with app.app_context():
        tasks.add_score.run(WEBID, "https://score.example/score.mei")
    constructor.assert_called_once_with(backend, client_id_document_url=document_url)


@pytest.mark.parametrize("document_url", [DOCUMENT, None])
def test_api_cli_uses_configured_identity(app, backend, monkeypatch, tmp_path, document_url):
    app.config["CLIENT_ID_DOCUMENT_URL"] = document_url
    constructor = create_autospec(SolidClient)
    monkeypatch.setattr(cli_api.client, "SolidClient", constructor)
    monkeypatch.setattr(cli_api, "lookup_provider_from_profile", lambda _: ISSUER)
    monkeypatch.setattr(cli_api, "get_storage_from_profile", lambda _: "https://pod.example/")
    upload = Mock(return_value="https://pod.example/midi")
    monkeypatch.setattr(cli_api, "upload_midi_to_pod", upload)
    monkeypatch.setattr(tasks, "align_recording", Mock())
    midi = tmp_path / "recording.mid"
    midi.write_bytes(b"test-midi")
    result = app.test_cli_runner().invoke(args=["api", "align", WEBID, "https://score.example/score", str(midi)])
    assert result.exit_code == 0, result.output
    constructor.assert_called_once_with(backend, client_id_document_url=document_url)
    assert upload.call_args.args[0] is constructor.return_value


def test_database_commands_are_available(app):
    result = app.test_cli_runner().invoke(args=["db", "--help"])
    assert result.exit_code == 0
    assert "create-database" in result.output
    assert "upgrade" in result.output


@pytest.mark.parametrize("reverse", [False, True])
def test_refresh_batch_uses_each_stored_identity(app, backend, monkeypatch, reverse):
    rows = [
        token(DOCUMENT, expired=True),
        token(OTHER_DOCUMENT, expired=True),
        token(DYNAMIC, expired=True, dynamic=True),
    ]
    if reverse:
        rows.reverse()
    app.config["CLIENT_ID_DOCUMENT_URL"] = "https://unrelated.example/client.jsonld"
    backend.get_token_responses.return_value = rows
    backend.get_token_response.side_effect = lambda issuer, webid, client_id: next(
        r for r in rows if r.client_id == client_id
    )
    monkeypatch.setattr(solid, "load_key", lambda _: object())
    refresh = Mock(return_value=(True, {"access_token": "new", "expires_in": 3600}))
    monkeypatch.setattr(solid, "refresh_auth_token", refresh)
    with app.app_context():
        tasks.refresh_all_authentication_tokens.run()
    assert backend.get_token_response.call_args_list == [call(ISSUER, WEBID, row.client_id) for row in rows]
    assert backend.update_token_response.call_count == 3
    for args in refresh.call_args_list:
        client_id, stored, auth = args.args[2:]
        assert stored.client_id == client_id
        assert auth == ((DYNAMIC, "secret") if client_id == DYNAMIC else None)
    backend.delete_token_response.assert_not_called()


@pytest.mark.parametrize("failure", ["refresh", "missing", "configuration", "registration"])
def test_refresh_batch_continues_and_only_deletes_failed_identity(app, backend, monkeypatch, failure):
    failed = token(DYNAMIC if failure == "registration" else DOCUMENT, expired=True, dynamic=failure == "registration")
    healthy = token(OTHER_DOCUMENT)
    backend.get_token_responses.return_value = [failed, healthy]
    backend.get_token_response.side_effect = (
        lambda issuer, webid, cid: (None if failure == "missing" else failed) if cid == failed.client_id else healthy
    )
    if failure == "registration":
        backend.get_client_registration.return_value = None
    if failure == "configuration":
        backend.get_resource_server_configuration.side_effect = ProviderConfigurationError("invalid provider")
    monkeypatch.setattr(solid, "load_key", lambda _: object())
    monkeypatch.setattr(solid, "refresh_auth_token", lambda *args: (False, {"error": "invalid_grant"}))
    with app.app_context():
        tasks.refresh_all_authentication_tokens.run()
    assert call(ISSUER, WEBID, OTHER_DOCUMENT) in backend.get_token_response.call_args_list
    if failure == "refresh":
        backend.delete_token_response.assert_called_once_with(ISSUER, WEBID, failed.client_id)
    else:
        backend.delete_token_response.assert_not_called()


@pytest.mark.parametrize("document_url,expected_id", [(DOCUMENT, DOCUMENT), (None, DYNAMIC)])
def test_permission_failure_deletes_only_selected_identity(app, backend, monkeypatch, document_url, expected_id):
    app.config["CLIENT_ID_DOCUMENT_URL"] = document_url
    monkeypatch.setattr(webserver, "lookup_provider_from_profile", lambda _: ISSUER)
    backend.get_token_response.return_value = token(expected_id, expired=True, dynamic=document_url is None)
    monkeypatch.setattr(solid, "load_key", lambda _: object())
    monkeypatch.setattr(solid, "refresh_auth_token", lambda *args: (False, {"error": "invalid_grant"}))
    response = app.test_client().get("/api/check_user_perms", query_string={"profile": WEBID})
    assert response.json == {"has_permission": False}
    backend.get_token_response.assert_called_once_with(ISSUER, WEBID, expected_id)
    backend.delete_token_response.assert_called_once_with(ISSUER, WEBID, expected_id)


def test_missing_dynamic_registration_has_no_permission(app, backend, monkeypatch):
    app.config["CLIENT_ID_DOCUMENT_URL"] = None
    backend.get_client_registration.return_value = None
    monkeypatch.setattr(webserver, "lookup_provider_from_profile", lambda _: ISSUER)
    response = app.test_client().get("/api/check_user_perms", query_string={"profile": WEBID})
    assert response.json == {"has_permission": False}
    backend.delete_token_response.assert_not_called()
