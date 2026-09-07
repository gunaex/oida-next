from fastapi.testclient import TestClient

from oida_next.control import create_app


def plan():
    return {
        "summary": "Deliver an auditable service",
        "assumptions": ["One delivery team"],
        "risks": ["Migration timing"],
        "pm_tasks": [
            {
                "title": "Confirm scope",
                "description": "Review the requested outcome",
                "phase": "Planning",
                "priority": "High",
            }
        ],
        "qa_suites": [
            {
                "name": "Acceptance",
                "description": "Validate the user journey",
                "suite_type": "UAT",
                "test_cases": [
                    {
                        "title": "Complete the journey",
                        "description": "Submit a valid request",
                        "expected_result": "The request is accepted",
                        "priority": "HIGH",
                    }
                ],
            }
        ],
        "document_requirements": [
            {
                "title": "Audit history",
                "description": "Store every approval",
                "priority": "MUST",
            }
        ],
        "infra": {
            "provider": "ON_PREM",
            "platform": "KUBERNETES",
            "components": ["API", "Database"],
            "rationale": "Keep delivery data private",
        },
    }


def test_draft_requires_reviewed_hash_and_distributes_every_generated_item(tmp_path, monkeypatch):
    async def generated(store, title, requirement, transport=None):
        value = plan()
        if "REQUESTED CHANGE" in requirement:
            value["pm_tasks"][0]["description"] = "Review the expanded outcome"
            value["pm_tasks"].append(
                {
                    "title": "Prepare rollout",
                    "description": "Plan the release",
                    "phase": "IP",
                    "priority": "High",
                }
            )
            value["qa_suites"][0]["test_cases"].append(
                {
                    "title": "Reject invalid input",
                    "description": "Submit invalid data",
                    "expected_result": "The request is rejected",
                    "priority": "HIGH",
                }
            )
            value["document_requirements"][0]["description"] = "Record every revised approval"
            value["infra"]["components"].append("Queue")
        return value, "local", "mistral:latest"

    monkeypatch.setattr("oida_next.ai_workflow.generate_plan", generated)
    app = create_app(tmp_path / "workflow.db")
    app.state.store.initialize_password("owner-password-long-enough")
    calls = []

    async def connected(request):
        return {"token": "module-token"}

    async def module_call(module, method, path, token, *, body=None, params=None):
        calls.append((module, method, path, token, body, params))
        if method == "GET" and module == "pm":
            return [{"id": "pm-task", "status": "Todo"}]
        if method == "GET" and module == "qa" and path.endswith("/suites"):
            return [{"id": "qa-suite", "status": "ACTIVE"}]
        if method == "GET" and module == "qa":
            return [{"id": "qa-case"}]
        if method == "GET" and module == "document":
            return [{"id": "document-requirement", "status": "DRAFT"}]
        if method == "GET" and path.startswith("v1/workspaces/"):
            return {"workspace": {"currentDesignId": "design"}}
        if method == "GET" and path.startswith("v1/designs/"):
            return {"design": {"designId": "design", "status": "DRAFT"}}
        if module == "document" and method == "POST" and path.endswith("/draft"):
            return {"change_id": "change", "draft": {"id": "document-revision"}}
        if module == "document" and method == "PUT":
            return {"id": "document-revision"}
        if module == "pm" and path == "projects":
            return {"id": "pm-project", "slug": "delivery"}
        if module == "pm":
            return {"id": "pm-task"}
        if module == "qa" and path == "projects":
            return {"id": "qa-project", "slug": "delivery"}
        if path.endswith("/suites"):
            return {"id": "qa-suite"}
        if path.endswith("/revisions"):
            return {"id": "qa-revision"}
        if module == "qa":
            return {"id": "qa-case"}
        if module == "document" and path == "projects":
            return {"id": "document-project", "key": "AI-TEST"}
        if module == "document":
            return {"id": "document-requirement", "code": "REQ-1"}
        if path == "v1/workspaces":
            return {"workspace": {"workspaceId": "workspace"}}
        if path == "v1/designs":
            return {"design": {"designId": "design"}}
        return {"ok": True}

    app.state.identity_connection = connected
    app.state.module_json = module_call
    client = TestClient(app)
    login = client.post("/api/v1/login", json={"password": "owner-password-long-enough"}).json()
    client.headers["Authorization"] = "Bearer " + login["access_token"]

    created = client.post(
        "/api/v1/ai/drafts",
        json={
            "title": "Delivery",
            "requirement": "Build the governed workflow",
            "idempotency_key": "workflow-test-key-0001",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "GENERATING"
    draft = client.get("/api/v1/ai/drafts").json()[0]
    assert draft["status"] == "DRAFT"
    assert calls == []

    changed = plan()
    changed["summary"] = "Human-reviewed delivery plan"
    edited = client.put(f"/api/v1/ai/drafts/{draft['id']}", json={"plan": changed}).json()
    assert edited["plan_hash"] != draft["plan_hash"]
    stale = client.post(
        f"/api/v1/ai/drafts/{draft['id']}/approve",
        json={"plan_hash": draft["plan_hash"]},
    )
    assert stale.status_code == 409
    assert calls == []

    approved = client.post(
        f"/api/v1/ai/drafts/{draft['id']}/approve",
        json={"plan_hash": edited["plan_hash"]},
    )
    assert approved.status_code == 200
    result = approved.json()
    assert result["status"] == "APPROVED"
    assert len(result["items"]) == 12
    assert {item["module"] for item in result["items"]} == {
        "pm",
        "qa",
        "document",
        "infra",
    }
    assert all(item["status"] == "CREATED" for item in result["items"])
    assert all(call[3] == "module-token" for call in calls)

    verification = client.post(f"/api/v1/ai/drafts/{draft['id']}/verify")
    assert verification.status_code == 200
    assert verification.json()["healthy"] is True
    assert set(verification.json()["modules"]) == {"pm", "qa", "document", "infra"}
    assert client.get("/api/v1/ai/drafts").json()[0]["verification"]["healthy"] is True

    repeated = client.post(
        "/api/v1/ai/drafts",
        json={
            "title": "Delivery",
            "requirement": "Build the governed workflow",
            "idempotency_key": "workflow-test-key-0001",
        },
    )
    assert repeated.json()["id"] == draft["id"]

    revision_created = client.post(
        f"/api/v1/ai/drafts/{draft['id']}/revisions",
        json={
            "change_request": "Add rollout, negative testing, and queue resilience",
            "idempotency_key": "workflow-revision-key-0001",
        },
    )
    assert revision_created.json()["status"] == "GENERATING"
    revision = client.get("/api/v1/ai/drafts").json()[0]
    assert revision["parent_id"] == draft["id"]
    assert revision["diff"]["pm"]["added"] == ["Prepare rollout"]
    assert revision["diff"]["infra"]["changed"] is True

    revised = client.post(
        f"/api/v1/ai/drafts/{revision['id']}/approve-revision",
        json={
            "plan_hash": revision["plan_hash"],
            "modules": ["pm", "qa", "document", "infra"],
        },
    )
    assert revised.status_code == 200
    assert revised.json()["status"] == "APPROVED"
    assert revised.json()["selected_modules"] == ["document", "infra", "pm", "qa"]

    revision_check = client.post(f"/api/v1/ai/drafts/{revision['id']}/verify")
    assert revision_check.status_code == 200
    assert revision_check.json()["healthy"] is True
    assert revision_check.json()["modules"]["pm"]["expected"] == 1
    assert revision_check.json()["modules"]["qa"]["cases"]["expected"] == 1
