import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from oida_next.ai_runtime import _json_object, generate_plan, validate_plan
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

    normalized = sample_plan()
    normalized["infra"]["components"] = ["Kafka, Spark, Object Storage"]
    normalized["pm_tasks"][0]["priority"] = "Medium"
    normalized["qa_suites"][0]["suite_type"] = "RECOVERY"
    normalized["qa_suites"][0]["test_cases"][0].update(
        {
            "title": "Reject negative authorization",
            "description": "An unauthorized user requests protected data",
            "negative_path": False,
        }
    )
    result = validate_plan(normalized)
    assert result["infra"]["components"] == ["Kafka", "Spark", "Object Storage"]
    assert result["pm_tasks"][0]["priority"] == "Med"
    assert result["qa_suites"][0]["test_cases"][0]["category"] == "FUNCTIONAL"
    assert result["qa_suites"][0]["suite_type"] == "OTHER"
    assert result["qa_suites"][0]["test_cases"][0]["negative_path"] is True
    assert result["document_requirements"][0]["acceptance_criteria"]


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


def test_deepseek_provider_uses_server_key_and_returns_validated_plan(tmp_path):
    app = create_app(tmp_path / "deepseek.db")
    app.state.store.initialize_password("owner-password-long-enough")
    with app.state.store.tx() as db:
        db.execute("INSERT INTO settings VALUES('ai_provider','deepseek')")
        db.execute("INSERT INTO settings VALUES('ai_model','deepseek-chat')")
        db.execute("INSERT INTO settings VALUES('ai_deepseek_key','server-only-key')")

    def upstream(request):
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer server-only-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(sample_plan())}}]},
        )

    result, provider, model = asyncio.run(
        generate_plan(
            app.state.store,
            "Delivery",
            "Build the governed workflow",
            transport=httpx.MockTransport(upstream),
        )
    )
    assert result["summary"] == "Plan"
    assert (provider, model) == ("deepseek", "deepseek-chat")
