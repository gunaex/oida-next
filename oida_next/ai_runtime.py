"""Server-side AI planning with bounded providers and validated structured output."""

import json
import re
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException
from pydantic import Field

from .protocol import StrictModel

LOCAL_BASE = "http://127.0.0.1:11434"
DEEPSEEK_BASE = "https://api.deepseek.com"


class AISettings(StrictModel):
    provider: str = Field(pattern="^(local|deepseek)$")
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=500)


class AIPlanRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=8000)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str | None


def _setting(store, key: str) -> str | None:
    with store.tx() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _config(store) -> ProviderConfig:
    provider = _setting(store, "ai_provider") or "local"
    model = _setting(store, "ai_model") or "mistral:latest"
    key = _setting(store, "ai_deepseek_key")
    if provider not in {"local", "deepseek"}:
        raise HTTPException(503, "AI provider configuration is invalid")
    return ProviderConfig(provider, model, key)


def _store_setting(db, key: str, value: str):
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))


def _prompt(title: str, requirement: str) -> tuple[str, str]:
    system = (
        "You are the planning engine for a governed software delivery system. "
        "Produce a practical draft for human review. Never claim approval or execution. "
        "Return only valid JSON."
    )
    user = f"""PROJECT: {title}
REQUIREMENT:
{requirement}

Return this JSON object:
{{
  "summary": "concise solution summary",
  "assumptions": ["explicit assumption"],
  "risks": ["material risk"],
  "pm_tasks": [{{"title":"...","description":"...","phase":"Planning|UR|DR|DN|ST|UT|IP","priority":"High|Med|Low"}}],
  "qa_suites": [{{"name":"...","description":"...","suite_type":"SMOKE|INTEGRATION|REGRESSION|UAT|OTHER","test_cases":[{{"title":"...","description":"...","expected_result":"...","priority":"HIGH|MEDIUM|LOW","category":"FUNCTIONAL|SECURITY|PERFORMANCE|RECOVERY","negative_path":false}}]}}],
  "document_requirements": [{{"title":"...","description":"...","acceptance_criteria":["measurable outcome"],"priority":"MUST|SHOULD|COULD"}}],
  "infra": {{"provider":"AWS|GCP|ON_PREM","platform":"KUBERNETES|NATIVE_VM|OPENSHIFT_OCP","components":["..."],"rationale":"..."}}
}}
Create 4-12 PM tasks, 3-8 QA suites with 2-8 cases each, and 5-20 atomic document requirements. Include negative, security, performance, and recovery coverage where relevant. Return infrastructure components as separate array items, never one comma-separated item. Give every requirement measurable acceptance criteria. Keep all values specific to the supplied requirement."""
    return system, user


def _json_object(text: str) -> dict:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI did not return JSON") from None
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise TypeError("AI plan must be an object")
    return value


def validate_plan(value: dict) -> dict:
    required = {
        "summary",
        "assumptions",
        "risks",
        "pm_tasks",
        "qa_suites",
        "document_requirements",
        "infra",
    }
    if not required.issubset(value) or not isinstance(value["summary"], str):
        raise ValueError("AI plan is missing required sections")
    limits = {
        "assumptions": (0, 20),
        "risks": (0, 20),
        "pm_tasks": (1, 30),
        "qa_suites": (1, 20),
        "document_requirements": (1, 40),
    }
    for key, (minimum, maximum) in limits.items():
        if not isinstance(value[key], list) or not minimum <= len(value[key]) <= maximum:
            raise ValueError(f"AI plan has invalid {key}")
    for task in value["pm_tasks"]:
        if not isinstance(task, dict) or not all(
            isinstance(task.get(k), str) and task[k].strip()
            for k in ("title", "description", "phase", "priority")
        ):
            raise ValueError("AI plan contains an invalid PM task")
        task["priority"] = {"Medium": "Med", "MEDIUM": "Med"}.get(
            task["priority"], task["priority"]
        )
    for suite in value["qa_suites"]:
        if (
            not isinstance(suite, dict)
            or not isinstance(suite.get("test_cases"), list)
            or not suite["test_cases"]
        ):
            raise ValueError("AI plan contains an invalid QA suite")
        for case in suite["test_cases"]:
            if not isinstance(case, dict) or not all(
                isinstance(case.get(key), str) and case[key].strip()
                for key in ("title", "description", "expected_result", "priority")
            ):
                raise ValueError("AI plan contains an invalid QA case")
            case.setdefault("category", "FUNCTIONAL")
            case.setdefault("negative_path", False)
    for requirement in value["document_requirements"]:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("title"), str):
            raise TypeError("AI plan contains an invalid document requirement")
        criteria = requirement.setdefault("acceptance_criteria", [])
        if not criteria:
            requirement["acceptance_criteria"] = [requirement.get("description", "Requirement met")]
    infra = value["infra"]
    if (
        not isinstance(infra, dict)
        or not isinstance(infra.get("components"), list)
        or not infra["components"]
    ):
        raise ValueError("AI plan contains an invalid infrastructure brief")
    if len(infra["components"]) == 1 and "," in infra["components"][0]:
        infra["components"] = [
            component.strip()
            for component in infra["components"][0].split(",")
            if component.strip()
        ]
    return value


async def generate_plan(
    store, title: str, requirement: str, transport=None
) -> tuple[dict, str, str]:
    config = _config(store)
    system, user = _prompt(title, requirement)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=180, trust_env=False) as client:
            if config.provider == "local":
                response = await client.post(
                    LOCAL_BASE + "/api/generate",
                    json={
                        "model": config.model,
                        "prompt": system + "\n\n" + user,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 3000},
                    },
                )
                response.raise_for_status()
                raw = response.json().get("response", "")
            else:
                if not config.api_key:
                    raise HTTPException(409, "DeepSeek API key is not configured")
                response = await client.post(
                    DEEPSEEK_BASE + "/chat/completions",
                    headers={"Authorization": "Bearer " + config.api_key},
                    json={
                        "model": config.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
        return validate_plan(_json_object(raw)), config.provider, config.model
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"AI planning failed: {type(exc).__name__}") from None


def install_ai(app, store, operator):
    @app.get("/api/v1/ai/settings", dependencies=[Depends(operator)])
    def settings():
        config = _config(store)
        return {
            "provider": config.provider,
            "model": config.model,
            "has_api_key": bool(config.api_key),
            "local_base_url": LOCAL_BASE,
        }

    @app.put("/api/v1/ai/settings", dependencies=[Depends(operator)])
    def update(body: AISettings):
        if (
            body.provider == "deepseek"
            and not body.api_key
            and not _setting(store, "ai_deepseek_key")
        ):
            raise HTTPException(422, "DeepSeek API key is required")
        with store.tx() as db:
            _store_setting(db, "ai_provider", body.provider)
            _store_setting(db, "ai_model", body.model.strip())
            if body.api_key:
                _store_setting(db, "ai_deepseek_key", body.api_key)
        config = _config(store)
        return {
            "provider": config.provider,
            "model": config.model,
            "has_api_key": bool(config.api_key),
        }

    @app.post("/api/v1/ai/plan", dependencies=[Depends(operator)])
    async def plan(body: AIPlanRequest):
        value, provider, model = await generate_plan(
            store, body.title.strip(), body.requirement.strip()
        )
        return {
            "plan": value,
            "provider": provider,
            "model": model,
            "authority": "DRAFT_REQUIRES_HUMAN_APPROVAL",
        }
