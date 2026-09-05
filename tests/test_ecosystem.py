from fastapi.testclient import TestClient

from oida_next.control import create_app


def test_work_lifecycle_and_auth(tmp_path):
    app = create_app(tmp_path / "test.db")
    app.state.store.initialize_password("test-password-long-enough")
    c = TestClient(app)
    assert c.get("/api/v1/work").status_code == 401
    assert c.post("/api/v1/work", json={"title": "x"}).status_code == 401
    token = c.post("/api/v1/login", json={"password": "test-password-long-enough"}).json()[
        "access_token"
    ]
    c.headers["Authorization"] = "Bearer " + token
    work = c.post("/api/v1/work", json={"title": "Release check"})
    assert work.status_code == 201
    key = work.json()["id"]
    for system in ("pm", "qa", "document", "infra"):
        body = {"system": system, "external_id": "example-123", "note": "Reference only"}
        for _ in range(2):
            r = c.put(f"/api/v1/work/{key}/references", json=body)
            assert r.json() == {"saved": True, "remote_synced": False}
    assert len(c.get("/api/v1/work").json()[0]["references"]) == 4
    assert c.patch(f"/api/v1/work/{key}", json={"status": "DONE"}).status_code == 200
    assert c.get("/api/v1/work").json()[0]["status"] == "DONE"
    assert c.get("/api/v1/ecosystem").json()["remote_execution"] is False
    assert (
        c.put(
            f"/api/v1/work/{key}/references", json={"system": "shell", "external_id": "x"}
        ).status_code
        == 422
    )
    assert c.patch("/api/v1/work/missing", json={"status": "DONE"}).status_code == 404
    assert c.post("/api/v1/work", json={"title": "  "}).status_code == 422
    reopened = TestClient(create_app(tmp_path / "test.db"))
    reopened.headers.update(c.headers)
    assert len(reopened.get("/api/v1/work").json()) == 1
    assert "/ecosystem.js" in c.get("/").text
    assert c.get("/ecosystem.js").status_code == 200


def test_project_mapping_conflicts_and_persistence(tmp_path):
    path = tmp_path / "projects.db"
    app = create_app(path)
    app.state.store.initialize_password("test-password-long-enough")
    c = TestClient(app)
    assert c.get("/api/v1/projects").status_code == 401
    assert c.post("/api/v1/projects", json={"name": "No auth"}).status_code == 401
    token = c.post("/api/v1/login", json={"password": "test-password-long-enough"}).json()[
        "access_token"
    ]
    c.headers["Authorization"] = "Bearer " + token
    a = c.post("/api/v1/projects", json={"name": "Release A"}).json()["id"]
    b = c.post("/api/v1/projects", json={"name": "Release B"}).json()["id"]
    body = {"system": "qa", "external_id": "release-a"}
    for _ in range(2):
        assert c.put(f"/api/v1/projects/{a}/links", json=body).json() == {
            "mapped": True,
            "remote_verified": False,
        }
    assert c.put(f"/api/v1/projects/{b}/links", json=body).status_code == 409
    assert (
        c.put(f"/api/v1/projects/{a}/links", json={**body, "external_id": "other"}).status_code
        == 409
    )
    work = c.post("/api/v1/work", json={"title": "Test release"}).json()["id"]
    for _ in range(2):
        assert c.put(f"/api/v1/projects/{a}/work/{work}").status_code == 200
    assert c.put(f"/api/v1/projects/{b}/work/{work}").status_code == 409
    assert c.put(f"/api/v1/projects/{a}/work/missing").status_code == 404
    assert c.put("/api/v1/projects/missing/links", json=body).status_code == 404
    assert c.post("/api/v1/projects", json={"name": " "}).status_code == 422
    reopened = TestClient(create_app(path))
    reopened.headers.update(c.headers)
    record = next(p for p in reopened.get("/api/v1/projects").json() if p["id"] == a)
    assert record["work_ids"] == [work]
    assert record["links"] == [body]
