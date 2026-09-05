from fastapi.testclient import TestClient

from oida_next.control import create_app


def test_cookie_session_resume_csrf_and_logout(tmp_path):
    app = create_app(tmp_path / "cookies.db")
    app.state.store.initialize_password("owner-password-long-enough")
    c = TestClient(app, base_url="https://oida-next.kanphong.com")
    login = c.post("/api/v1/login", json={"password": "owner-password-long-enough"})
    cookie = login.headers["set-cookie"]
    assert "__Host-oida_session=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Domain=" not in cookie and "Path=/" in cookie
    assert c.get("/api/v1/session").json() == {"authenticated": True}
    for origin in [None, "https://attacker.test", "https://qaagain.kanphong.com"]:
        headers = {"Origin": origin} if origin else {}
        assert (
            c.post("/api/v1/projects", json={"name": "blocked"}, headers=headers).status_code == 403
        )
    headers = {"Origin": "https://oida-next.kanphong.com"}
    assert c.post("/api/v1/projects", json={"name": "allowed"}, headers=headers).status_code == 201
    assert (
        c.post(
            "/api/v1/projects",
            json={"name": "blocked"},
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )
    assert c.post("/api/v1/logout", headers=headers).status_code == 200
    assert c.get("/api/v1/session").status_code == 401
    assert (
        c.get(
            "/api/v1/session", headers={"Authorization": "Bearer " + login.json()["access_token"]}
        ).status_code
        == 401
    )


def test_cross_origin_login_rejected(tmp_path):
    app = create_app(tmp_path / "csrf.db")
    app.state.store.initialize_password("owner-password-long-enough")
    c = TestClient(app)
    assert (
        c.post(
            "/api/v1/login",
            json={"password": "owner-password-long-enough"},
            headers={"Origin": "https://attacker.test"},
        ).status_code
        == 403
    )
