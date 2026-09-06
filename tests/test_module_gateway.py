import httpx
from fastapi.testclient import TestClient
from test_identity_bridge import setup

from oida_next.control import create_app
from oida_next.identity_bridge import IdentityConfig


def test_gateway_uses_server_identity_and_preserves_binary_data(tmp_path):
    calls = []
    payload = b"\x00\xff" * 100000

    def remote(request):
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
        calls.append(request)
        assert request.url.host == "qa.test"
        assert request.headers["authorization"] == "Bearer private-central-token"
        assert "cookie" not in request.headers
        assert "x-actor" not in request.headers
        assert request.content == payload
        return httpx.Response(
            200,
            content=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "Set-Cookie": "secret=not-for-browser",
            },
        )

    c = setup(tmp_path, remote)
    c.post("/api/v1/identity", json={"email": "central@example.test", "password": "proof"})
    result = c.post(
        "/api/v1/modules/qa/proxy/project/files?version=1",
        content=payload,
        headers={"Cookie": "untrusted=anything", "X-Actor": "administrator"},
    )
    assert result.status_code == 200
    assert result.content == payload
    assert result.headers.get("set-cookie") is None
    assert result.headers["cache-control"] == "no-store"
    assert str(calls[0].url) == "https://qa.test/api/project/files?version=1"
    assert c.post("/api/v1/modules/qa/proxy/auth/login", json={}).status_code == 403
    assert c.get("/api/v1/modules/qa/proxy/%252fsecret").status_code == 400
    assert len(calls) == 1
    assert (
        c.post(
            "/api/v1/modules/qa/proxy/project/files",
            content=b"x",
            headers={"Content-Length": str(9 * 1024 * 1024)},
        ).status_code
        == 413
    )
    c.delete("/api/v1/identity")
    assert c.get("/api/v1/modules/qa/proxy/projects").status_code == 401


def test_gateway_does_not_follow_redirects_or_expose_upstream_failures(tmp_path):
    for code in (302, 500):

        def remote(request, code=code):
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
            return httpx.Response(
                code, text="private server error", headers={"Location": "https://evil.test"}
            )

        c = setup(tmp_path / str(code), remote)
        c.post("/api/v1/identity", json={"email": "central@example.test", "password": "proof"})
        response = c.get("/api/v1/modules/pm/proxy/projects")
        assert response.status_code == 502
        assert "private" not in response.text
        assert "location" not in response.headers


def test_document_and_infra_keep_their_native_api_paths(tmp_path):
    visited = []

    def remote(request):
        if request.url.host == "account.test":
            return httpx.Response(200, json={"email": "owner@example.com", "accessToken": "central-token",
                "tokenType": "Bearer", "expiresIn": 300, "mustChangePassword": False})
        assert request.headers["Authorization"] == "Bearer central-token"
        assert request.headers.get("X-Tenant-Id") is None
        visited.append(str(request.url))
        return httpx.Response(200, json=[])

    app = create_app(tmp_path / "all-modules.db", identity_config=IdentityConfig(
        "https://account.test", "https://pm.test", "https://qa.test",
        document_origin="https://document.test", infra_origin="https://infra.test"),
        identity_transport=httpx.MockTransport(remote))
    app.state.store.initialize_password("test-owner-password")
    c = TestClient(app)
    session = c.post("/api/v1/login", json={"password": "test-owner-password"}).json()["access_token"]
    c.headers["Authorization"] = "Bearer " + session
    c.post("/api/v1/identity", json={"email": "owner@example.com", "password": "central-proof"})
    assert c.get("/api/v1/modules/document/proxy/projects").status_code == 200
    assert c.get("/api/v1/modules/infra/proxy/v1/designs").status_code == 200
    assert visited == ["https://document.test/api/projects", "https://infra.test/api/v1/designs"]
