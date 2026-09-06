import httpx
from fastapi.testclient import TestClient

from oida_next.control import create_app
from oida_next.identity_bridge import IdentityConfig


def test_requirement_creates_all_four_module_records_once(tmp_path):
    calls = []

    def remote(request):
        calls.append((request.url.host, request.method, request.url.path))
        if request.url.host == "account.test":
            return httpx.Response(
                200,
                json={
                    "email": "owner@example.test",
                    "accessToken": "shared-token",
                    "tokenType": "Bearer",
                    "expiresIn": 300,
                    "mustChangePassword": False,
                },
            )
        assert request.headers["authorization"] == "Bearer shared-token"
        if request.url.host == "pm.test":
            return httpx.Response(200, json={"id": 11, "slug": "alpha"})
        if request.url.host == "qa.test":
            return httpx.Response(200, json={"id": 22, "slug": "alpha"})
        if request.url.path == "/api/projects":
            return httpx.Response(201, json={"id": "prj-1", "key": "OIDA-123"})
        if request.url.path == "/api/requirements":
            return httpx.Response(201, json={"id": "req-1", "code": "REQ-0001"})
        return httpx.Response(200, json={"design": {"designId": "design-1"}})

    config = IdentityConfig(
        "https://account.test",
        "https://pm.test",
        "https://qa.test",
        document_origin="https://document.test",
        infra_origin="https://infra.test",
    )
    app = create_app(
        tmp_path / "oida.db", identity_config=config, identity_transport=httpx.MockTransport(remote)
    )
    app.state.store.initialize_password("owner-password-long-enough")
    client = TestClient(app)
    token = client.post("/api/v1/login", json={"password": "owner-password-long-enough"}).json()[
        "access_token"
    ]
    client.headers["Authorization"] = "Bearer " + token
    assert (
        client.post(
            "/api/v1/identity", json={"email": "owner@example.test", "password": "secret"}
        ).status_code
        == 200
    )

    body = {
        "title": "Alpha",
        "requirement": "Build the requested system",
        "idempotency_key": "12345678-1234-1234-1234-123456789012",
    }
    result = client.post("/api/v1/orchestrations", json=body)
    assert result.status_code == 200
    assert result.json()["status"] == "COMPLETE"
    assert set(result.json()["targets"]) == {"pm", "qa", "document", "infra"}
    first_count = len(calls)
    again = client.post("/api/v1/orchestrations", json=body)
    assert again.status_code == 200
    assert len(calls) == first_count
