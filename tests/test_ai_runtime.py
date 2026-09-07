from fastapi.testclient import TestClient

from oida_next.ai_runtime import _json_object, validate_plan
from oida_next.control import create_app


def sample_plan():
    return {
        "summary": "Plan",
        "assumptions": [],
        "risks": ["Migration risk"],
        "pm_tasks": [
            {
                "title": "Plan",
                "description": "Plan delivery",
                "phase": "Planning",
                "priority": "High",
            }
        ],
        "qa_suites": [
            {
                "name": "Acceptance",
                "description": "Validate",
                "suite_type": "UAT",
                "test_cases": [
                    {
                        "title": "Happy path",
                        "description": "Works",
                        "expected_result": "The workflow completes",
                        "priority": "HIGH",
                    }
                ],
            }
        ],
        "document_requirements": [
            {"title": "Audit", "description": "Record changes", "priority": "MUST"}
        ],
        "infra": {
            "provider": "ON_PREM",
            "platform": "KUBERNETES",
            "components": ["API", "Database"],
            "rationale": "Private runtime",
        },
    }


def test_structured_plan_accepts_fenced_json_and_rejects_missing_sections():
    import json

    assert (
        validate_plan(_json_object("```json\n" + json.dumps(sample_plan()) + "\n```"))["summary"]
        == "Plan"
    )
    try:
        validate_plan({"summary": "incomplete"})
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete AI plan was accepted")


def test_ai_settings_never_return_deepseek_key(tmp_path):
    app = create_app(tmp_path / "oida.db")
    app.state.store.initialize_password("owner-password-long-enough")
    client = TestClient(app)
    token = client.post("/api/v1/login", json={"password": "owner-password-long-enough"}).json()[
        "access_token"
    ]
    client.headers["Authorization"] = "Bearer " + token
    secret = "deepseek-secret-value"
    response = client.put(
        "/api/v1/ai/settings",
        json={"provider": "deepseek", "model": "deepseek-chat", "api_key": secret},
    )
    assert response.status_code == 200
    assert response.json()["has_api_key"] is True
    assert secret not in response.text
    assert secret not in client.get("/api/v1/ai/settings").text
