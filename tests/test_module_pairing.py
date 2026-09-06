import json

import httpx
import pytest
from test_identity_bridge import setup


@pytest.mark.parametrize("denied", [False, True])
def test_pairing_keeps_tokens_private_and_revokes_temporary_login(tmp_path, denied):
    paths = []

    def remote(request):
        paths.append(request.url.path)
        assert "owner-password" not in request.content.decode()
        assert request.headers.get("authorization") is None
        if request.url.host == "identity.test":
            return httpx.Response(
                200,
                json={
                    "email": "central@example.test",
                    "accessToken": "private-central-token",
                    "expiresIn": 300,
                    "tokenType": "Bearer",
                    "mustChangePassword": False,
                },
            )
        assert request.url.host == "qa.test"
        if request.url.path.endswith("/login"):
            assert request.headers.get("cookie") is None
            assert json.loads(request.content)["email"] == "local@example.test"
            return httpx.Response(
                200,
                json={"must_change_password": False},
                headers=[
                    ("set-cookie", "access_token=private-local-token; Path=/; Secure"),
                    ("set-cookie", "refresh_token=private-refresh; Path=/api/auth; Secure"),
                ],
            )
        assert "private-local-token" in request.headers["cookie"]
        if request.url.path.endswith("/link-identity"):
            assert json.loads(request.content) == {
                "current_password": "local-proof",
                "identity_token": "private-central-token",
            }
            return httpx.Response(
                409 if denied else 200, json={"linked": True, "private": "upstream-secret"}
            )
        assert request.url.path.endswith("/logout")
        assert "private-refresh" in request.headers["cookie"]
        return httpx.Response(200, json={"ok": True})

    c = setup(tmp_path, remote)
    body = {"email": "local@example.test", "password": "local-proof"}
    assert c.post("/api/v1/modules/qa/pair", json=body).status_code == 401
    c.post("/api/v1/identity", json={"email": "central@example.test", "password": "central-proof"})
    result = c.post("/api/v1/modules/qa/pair", json=body)
    assert result.status_code == (409 if denied else 200)
    assert "private" not in result.text and "upstream-secret" not in result.text
    assert result.headers.get("set-cookie") is None
    assert paths[-3:] == ["/api/auth/login", "/api/auth/link-identity", "/api/auth/logout"]
    assert c.post("/api/v1/modules/arbitrary/pair", json=body).status_code == 404
