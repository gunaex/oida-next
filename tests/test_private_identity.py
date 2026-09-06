import json
import socketserver
import tempfile
import threading
from http.server import BaseHTTPRequestHandler

import pytest
from fastapi.testclient import TestClient

from oida_next.control import create_app
from oida_next.identity_bridge import IdentityConfig, configured_identity


def test_private_socket_configuration(monkeypatch):
    for name, value in {
        "OIDA_ACCOUNT_ORIGIN": "https://identity.test",
        "OIDA_PM_ORIGIN": "https://pm.test",
        "OIDA_QA_ORIGIN": "https://qa.test",
        "OIDA_ACCOUNT_SOCKET": "/run/oida/account.sock",
    }.items():
        monkeypatch.setenv(name, value)
    assert configured_identity().account_socket == "/run/oida/account.sock"
    for path in ["relative.sock", "/", "/run/../account.sock"]:
        with pytest.raises(ValueError, match="absolute file path"):
            IdentityConfig("https://identity.test", "https://pm.test", "https://qa.test", path)


def test_connection_uses_unix_socket_without_public_network(tmp_path):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(
                (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            payload = json.dumps(
                {
                    "email": "private@example.com",
                    "accessToken": "private-identity",
                    "tokenType": "Bearer",
                    "expiresIn": 300,
                    "mustChangePassword": False,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with tempfile.TemporaryDirectory(prefix="oida-uds-") as directory:
        socket = directory + "/account.sock"
        with socketserver.UnixStreamServer(socket, Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                app = create_app(
                    tmp_path / "control.db",
                    identity_config=IdentityConfig(
                        "https://does-not-exist.invalid",
                        "https://pm.invalid",
                        "https://qa.invalid",
                        socket,
                    ),
                )
                app.state.store.initialize_password("test-owner-password")
                client = TestClient(app)
                token = client.post(
                    "/api/v1/login", json={"password": "test-owner-password"}
                ).json()["access_token"]
                client.headers["Authorization"] = "Bearer " + token
                response = client.post(
                    "/api/v1/identity",
                    json={"email": "private@example.com", "password": "test-proof"},
                )
                assert response.status_code == 200
                assert "private-identity" not in response.text
                assert received == [
                    (
                        "/api/v1/auth/ecosystem-token",
                        {"email": "private@example.com", "password": "test-proof"},
                    )
                ]
            finally:
                server.shutdown()
                thread.join(timeout=5)
