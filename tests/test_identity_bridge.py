import httpx
from fastapi.testclient import TestClient

from oida_next.control import create_app
from oida_next.identity_bridge import IdentityConfig


def setup(tmp_path, handler, configured=True):
    config = (
        IdentityConfig("https://identity.test", "https://pm.test", "https://qa.test")
        if configured
        else None
    )
    app = create_app(
        tmp_path / "identity.db",
        identity_config=config,
        identity_transport=httpx.MockTransport(handler),
    )
    app.state.store.initialize_password("owner-password-long-enough")
    c = TestClient(app)
    session = c.post("/api/v1/login", json={"password": "owner-password-long-enough"}).json()[
        "access_token"
    ]
    c.headers["Authorization"] = "Bearer " + session
    return c


def test_identity_connection_projects_and_isolation(tmp_path):
    calls = []

    def remote(request):
        calls.append(request)
        if request.url.host == "identity.test":
            assert request.headers.get("authorization") is None
            return httpx.Response(
                200,
                json={
                    "email": "owner@example.test",
                    "accessToken": "module-only-token",
                    "tokenType": "Bearer",
                    "expiresIn": 300,
                    "mustChangePassword": False,
                },
            )
        assert request.url.host == "qa.test"
        assert request.headers["authorization"] == "Bearer module-only-token"
        assert request.headers.get("cookie") is None
        return httpx.Response(200, json=[{"slug": "alpha", "name": "Alpha"}])

    c = setup(tmp_path, remote)
    assert c.get("/api/v1/modules/qa/projects").status_code == 401
    result = c.post(
        "/api/v1/identity", json={"email": "owner@example.test", "password": "central-password"}
    )
    assert result.status_code == 200
    assert "module-only-token" not in result.text
    assert "central-password" not in result.text
    assert c.get("/api/v1/identity").json()["connected"] is True
    assert c.get("/api/v1/modules/qa/projects").json()[0]["external_id"] == "alpha"
    another = TestClient(c.app)
    token = another.post("/api/v1/login", json={"password": "owner-password-long-enough"}).json()[
        "access_token"
    ]
    another.headers["Authorization"] = "Bearer " + token
    assert another.get("/api/v1/identity").json()["connected"] is False
    assert another.get("/api/v1/modules/qa/projects").status_code == 401
    imported = c.post("/api/v1/modules/qa/projects/alpha/import")
    assert imported.status_code == 200
    project_id = imported.json()["project_id"]
    again = c.post("/api/v1/modules/qa/projects/alpha/import").json()
    assert again == {"project_id": project_id, "created": False, "remote_modified": False}
    assert len(c.get("/api/v1/projects").json()) == 1
    assert c.post("/api/v1/modules/qa/projects/missing/import").status_code == 404
    assert c.delete("/api/v1/identity").status_code == 200
    assert c.get("/api/v1/modules/qa/projects").status_code == 401
    assert len(calls) == 5


def test_disabled_and_unauthenticated_do_not_contact_upstream(tmp_path):
    def remote(request):
        raise AssertionError("Unexpected upstream request")

    c = setup(tmp_path, remote, configured=False)
    body = {"email": "owner@example.test", "password": "central-password"}
    assert c.post("/api/v1/identity", json=body).status_code == 503
    c.headers.clear()
    assert c.post("/api/v1/identity", json=body).status_code == 401


def test_login_limits_and_upstream_errors_are_sanitized(tmp_path):
    c = setup(tmp_path, lambda r: httpx.Response(401, text="private upstream error"))
    for _ in range(5):
        response = c.post(
            "/api/v1/identity", json={"email": "owner@example.test", "password": "bad"}
        )
        assert response.status_code == 401
        assert "private" not in response.text
    assert (
        c.post(
            "/api/v1/identity", json={"email": "owner@example.test", "password": "bad"}
        ).status_code
        == 429
    )


def test_password_validation_never_echoes_input(tmp_path):
    c = setup(tmp_path, lambda r: httpx.Response(500))
    password = "private-value-" * 30
    response = c.post(
        "/api/v1/identity", json={"email": "owner@example.test", "password": password}
    )
    assert response.status_code == 422
    assert password not in response.text
    assert "private-value" not in response.text


def test_upstream_password_change_and_malformed_contract(tmp_path):
    payload = {
        "email": "owner@example.test",
        "accessToken": "private-module-token",
        "tokenType": "Bearer",
        "expiresIn": 300,
        "mustChangePassword": True,
    }
    c = setup(tmp_path, lambda r: httpx.Response(200, json=payload))
    body = {"email": "owner@example.test", "password": "central-password"}
    assert c.post("/api/v1/identity", json=body).status_code == 403
    payload["mustChangePassword"] = False
    payload["expiresIn"] = 99999
    assert c.post("/api/v1/identity", json=body).status_code == 502
    assert c.get("/api/v1/identity").json()["connected"] is False
