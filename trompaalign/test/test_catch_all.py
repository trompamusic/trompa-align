import pytest
from flask import Flask

from trompaalign import webserver


@pytest.fixture
def client(tmp_path, monkeypatch):
    clara = tmp_path / "clara"
    (clara / "static").mkdir(parents=True)
    (clara / "index.html").write_text("index")
    (clara / "static" / "app.js").write_text("app")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr(webserver, "CLARA_BUILD_DIRECTORY", str(clara))

    app = Flask(__name__, static_folder=None)
    app.register_blueprint(webserver.webserver_bp)
    return app.test_client()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/", b"index"),
        ("/static/app.js", b"app"),
        ("/select", b"index"),
        ("/static", b"index"),
    ],
)
def test_serves_clara_files_and_falls_back_to_index(client, path, body):
    response = client.get(path)
    assert response.status_code == 200
    assert response.data == body


@pytest.mark.parametrize("path", ["/../secret.txt", "/..%2Fsecret.txt", "/static/..%2F..%2Fsecret.txt"])
def test_does_not_serve_files_outside_clara(client, path):
    response = client.get(path)
    assert b"secret" not in response.data
