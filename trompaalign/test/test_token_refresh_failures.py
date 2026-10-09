from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
from solidauth import client

from trompaalign import tasks, webserver


def test_permission_check_returns_temporary_error_without_deleting_token(monkeypatch):
    app = Flask(__name__)
    app.config["CLIENT_ID_DOCUMENT_URL"] = "document-id"
    backend = Mock()
    monkeypatch.setattr(webserver.extensions.backend, "backend", backend, raising=False)
    monkeypatch.setattr(webserver, "lookup_provider_from_profile", lambda _: "issuer")
    monkeypatch.setattr(
        client.SolidClient, "get_valid_access_token", Mock(side_effect=client.TokenRefreshRateLimited(5))
    )
    with app.test_request_context("/api/check_user_perms?profile=webid"):
        response, status, headers = webserver.check_user_perms()
    assert status == 503
    assert headers == {"Retry-After": "5"}
    assert response.json == {"error": "token_refresh_rate_limited"}
    backend.delete_token_response.assert_not_called()


def test_scheduled_refresh_preserves_temporary_failures_and_continues(monkeypatch):
    backend = Mock()
    backend.get_token_responses.return_value = [
        SimpleNamespace(issuer="issuer", webid="first", client_id="document-id", client_registration=None),
        SimpleNamespace(issuer="issuer", webid="second", client_id="document-id", client_registration=None),
    ]
    monkeypatch.setattr(tasks.backend, "backend", backend, raising=False)
    refresh = Mock(side_effect=[client.TokenRefreshRateLimited(5), "valid"])
    monkeypatch.setattr(client.SolidClient, "get_valid_access_token", refresh)
    tasks.refresh_all_authentication_tokens.run()
    assert refresh.call_count == 2
    backend.delete_token_response.assert_not_called()
