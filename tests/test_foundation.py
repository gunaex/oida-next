import hashlib
import json
import secrets
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from oida_next.agent import Agent
from oida_next.control import create_app
from oida_next.models import DeterministicPlanner
from oida_next.protocol import canonical
from oida_next.security import load_key, redact, signed_headers


@pytest.fixture
def system(tmp_path):
    app = create_app(tmp_path / "control.db")
    password = secrets.token_urlsafe(32)
    app.state.store.initialize_password(password)
    client = TestClient(app)
    token = client.post("/api/v1/login", json={"password": password}).json()["access_token"]
    operator = {"Authorization": "Bearer " + token}
    phrase = secrets.token_urlsafe(32)
    agent = Agent("http://127.0.0.1", tmp_path / "agent", phrase, True)
    agent.client.close()
    agent.client = client
    enrollment = client.post("/api/v1/enrollment", headers=operator).json()["token"]
    agent.register(enrollment)
    yield app, client, operator, agent, tmp_path, phrase, password
    agent.close()


def submit(system, recipe="workspace_demo", **extra):
    _, client, headers, agent, *_ = system
    body = {
        "goal": "Test artifact round trip",
        "target": agent.agent_id,
        "recipe": recipe,
        "idempotency_key": secrets.token_hex(12),
        **extra,
    }
    response = client.post("/api/v1/goals", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_full_roundtrip_evidence(system):
    _, client, headers, agent, *_ = system
    job = submit(system)
    agent.tick()
    final = client.get(f"/api/v1/jobs/{job['id']}", headers=headers).json()
    assert final["state"] == "SUCCEEDED"
    evidence = client.get(f"/api/v1/jobs/{job['id']}/evidence", headers=headers).json()
    assert hashlib.sha256(evidence["content"].encode()).hexdigest() == evidence["sha256"]
    assert "artifact.txt" in evidence["content"]
    events = client.get("/api/v1/events", headers=headers).json()
    assert {"job.dispatched", "job.output", "task.validation_passed", "job.completed"} <= {
        e["type"] for e in events
    }


def test_ecosystem_execution_trace(system):
    _, client, headers, agent, *_ = system
    work = client.post("/api/v1/work", headers=headers, json={"title": "Integrated work"}).json()
    job = submit(system)
    endpoint = f"/api/v1/work/{work['id']}/jobs/{job['id']}"
    assert client.put(endpoint).status_code == 401
    for _ in range(2):
        assert client.put(endpoint, headers=headers).json()["execution_started"] is False
    trace_url = f"/api/v1/work/{work['id']}/execution"
    assert client.get(trace_url).status_code == 401
    trace = client.get(trace_url, headers=headers).json()
    assert len(trace["jobs"]) == 1
    assert trace["jobs"][0]["evidence"] is None
    agent.tick()
    trace = client.get(trace_url, headers=headers).json()
    assert trace["jobs"][0]["state"] == "SUCCEEDED"
    evidence = trace["jobs"][0]["evidence"]
    assert hashlib.sha256(evidence["content"].encode()).hexdigest() == evidence["sha256"]
    assert trace["remote_synced"] is False
    events = client.get("/api/v1/events", headers=headers).json()
    assert len([e for e in events if e["type"] == "work.job_linked"]) == 1
    assert client.put(f"/api/v1/work/{work['id']}/jobs/missing", headers=headers).status_code == 404


def test_approval_exact_action_and_sandbox_package(system):
    _, client, headers, agent, *_ = system
    job = submit(system, "package_check", timeout=60)
    assert job["state"] == "WAITING_APPROVAL"
    assert agent.tick() is None
    endpoint = f"/api/v1/jobs/{job['id']}/approval"
    assert (
        client.post(
            endpoint, headers=headers, json={"action_hash": "wrong", "approve": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint, headers=headers, json={"action_hash": job["action_hash"], "approve": True}
        ).status_code
        == 200
    )
    agent.tick()
    final = client.get(f"/api/v1/jobs/{job['id']}", headers=headers).json()
    assert final["state"] == "SUCCEEDED", final
    assert "host_packages_modified" in final["result"]["evidence"]


def test_duplicate_claim_execution_and_result(system):
    _, _, _, agent, *_ = system
    submit(system)
    job = agent.call("POST", "/api/v1/agents/claim")
    assert agent.call("POST", "/api/v1/agents/claim")["lease"] == job["lease"]
    result = agent.execute(job)
    artifact = agent.root / job["id"] / "artifact.txt"
    before = artifact.stat().st_mtime_ns
    assert agent.execute(job) == result
    assert artifact.stat().st_mtime_ns == before
    endpoint = f"/api/v1/agents/jobs/{job['id']}/result"
    agent.call("POST", endpoint, result)
    assert agent.call("POST", endpoint, result)["duplicate"]


def test_control_restart_and_agent_reconnect(system):
    _, _, headers, agent, root, phrase, _ = system
    job = submit(system)
    new_client = TestClient(create_app(root / "control.db"))
    agent.client = new_client
    agent.tick()
    assert (
        new_client.get(f"/api/v1/jobs/{job['id']}", headers=headers).json()["state"] == "SUCCEEDED"
    )
    resumed = Agent("http://127.0.0.1", root / "agent", phrase, True)
    resumed.client.close()
    resumed.client = new_client
    assert resumed.agent_id == agent.agent_id
    assert resumed.tick() is None
    resumed.close()


def test_interrupted_execution_never_repeated(system):
    _, _, _, agent, *_ = system
    submit(system)
    job = agent.call("POST", "/api/v1/agents/claim")
    agent.journal.execute(
        "INSERT INTO executions VALUES(?,?,?,NULL)", (job["id"], job["action_hash"], "STARTED")
    )
    agent.journal.commit()
    result = agent.execute(job)
    assert result["state"] == "FAILED"
    assert not (agent.root / job["id"]).exists()


def test_queued_cancel_and_reject(system):
    _, client, headers, agent, *_ = system
    job = submit(system)
    client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert agent.tick() is None
    job = submit(system, "package_check")
    result = client.post(
        f"/api/v1/jobs/{job['id']}/approval",
        headers=headers,
        json={"action_hash": job["action_hash"], "approve": False},
    )
    assert result.json()["state"] == "CANCELLED"


def test_running_cancel(system, monkeypatch):
    _, client, headers, agent, *_ = system
    job = submit(system)
    job = agent.call("POST", "/api/v1/agents/claim")
    client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    monkeypatch.setitem(
        __import__("oida_next.agent", fromlist=["RECIPES"]).RECIPES,
        "workspace_demo",
        "import time; time.sleep(10)",
    )
    assert agent.execute(job)["state"] == "CANCELLED"


def test_timeout(system, monkeypatch):
    _, _, _, agent, *_ = system
    submit(system, timeout=1)
    job = agent.call("POST", "/api/v1/agents/claim")
    monkeypatch.setitem(
        __import__("oida_next.agent", fromlist=["RECIPES"]).RECIPES,
        "workspace_demo",
        "import time; time.sleep(5)",
    )
    assert agent.execute(job)["state"] == "TIMED_OUT"


def test_signed_replay_tampering_and_auth(system):
    _, client, _, agent, *_ = system
    path = "/api/v1/agents/heartbeat"
    body = canonical({"capabilities": {}})
    signed = signed_headers(agent.key, agent.agent_id, "POST", path, body)
    assert client.post(path, content=body, headers=signed).status_code == 200
    assert client.post(path, content=body, headers=signed).status_code == 401
    signed = signed_headers(agent.key, agent.agent_id, "POST", path, body)
    assert (
        client.post(
            path, content=canonical({"capabilities": {"os": "tampered"}}), headers=signed
        ).status_code
        == 401
    )
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.post("/api/v1/agents/claim").status_code == 401


def test_job_idempotency_conflict(system):
    _, client, headers, agent, *_ = system
    key = secrets.token_hex(12)
    first = submit(system, idempotency_key=key)
    assert submit(system, idempotency_key=key)["id"] == first["id"]
    changed = {
        "goal": "different",
        "recipe": "system_info",
        "target": agent.agent_id,
        "idempotency_key": key,
    }
    assert client.post("/api/v1/goals", headers=headers, json=changed).status_code == 409


def test_checksum_tamper(system):
    _, _, _, agent, *_ = system
    submit(system)
    job = agent.call("POST", "/api/v1/agents/claim")
    result = agent.execute(job)
    result["checksum"] = "0" * 64
    with pytest.raises(httpx.HTTPStatusError):
        agent.call("POST", f"/api/v1/agents/jobs/{job['id']}/result", result)


def test_key_encryption_and_tls(tmp_path):
    phrase = secrets.token_urlsafe(32)
    load_key(tmp_path / "key.enc", phrase)
    assert b"ENCRYPTED PRIVATE KEY" in (tmp_path / "key.enc").read_bytes()
    with pytest.raises(ValueError):
        load_key(tmp_path / "key.enc", "incorrect-unlock-password")
    with pytest.raises(ValueError):
        Agent("http://example.com", tmp_path / "bad", phrase, True)


def test_policy_path_traversal_and_plan_tampering(system):
    _, _, _, agent, *_ = system
    submit(system)
    job = agent.call("POST", "/api/v1/agents/claim")
    copy = json.loads(json.dumps(job))
    copy["id"] = "../../etc"
    with pytest.raises(ValueError):
        agent.execute(copy)
    copy = json.loads(json.dumps(job))
    copy["action"]["arguments"] = ["rm", "-rf", "/"]
    with pytest.raises(ValueError):
        agent.execute(copy)


def test_readiness_protocol_ui(system):
    _, client, headers, *_ = system
    assert client.get("/ready").json()["status"] == "READY"
    assert client.get("/openapi.json").json()["info"]["title"] == "OIDA Next"
    assert "Mission control" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/api/v1/models", headers=headers).json()[0]["cost"] == 0


def test_unknown_goal_and_redaction():
    with pytest.raises(ValueError):
        DeterministicPlanner().plan("Delete all databases")
    assert "supersecret" not in redact("token=supersecret")
    assert "\x1b" not in redact("\x1b[31mhello")


def test_structured_and_bearer_secret_redaction():
    assert json.loads(redact('{"token": "private value"}')) == {"token": "[REDACTED]"}
    assert "private-value" not in redact("Authorization: Bearer private-value")
    assert "private-material" not in redact(
        "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
    )


def test_setup_requires_loopback_origin_and_is_one_time(tmp_path):
    app = create_app(tmp_path / "setup.db")
    local = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 30000))
    body = {"password": secrets.token_urlsafe(24)}
    assert local.post("/api/v1/setup", json=body).status_code == 403
    assert (
        local.post(
            "/api/v1/setup", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert local.post("/api/v1/setup", json=body, headers=headers).status_code == 200
    assert local.post("/api/v1/setup", json=body, headers=headers).status_code == 409
    assert local.get("/api/v1/setup-status").json()["initialized"]


def test_expired_signature(system):
    _, client, _, agent, *_ = system
    headers = signed_headers(agent.key, agent.agent_id, "POST", "/api/v1/agents/claim", b"")
    headers["X-Timestamp"] = str(int(time.time()) - 300)
    assert client.post("/api/v1/agents/claim", headers=headers).status_code == 401
