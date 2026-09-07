"""Durable AI drafts, approval, distribution, and live delivery verification."""

import asyncio
import hashlib
import json
import time
import uuid

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from pydantic import Field

from .ai_runtime import generate_plan, validate_plan
from .protocol import StrictModel


class DraftCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=16, max_length=100)


class DraftUpdate(StrictModel):
    plan: dict


class DraftApproval(StrictModel):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def install_ai_workflow(app, store, operator):
    with store.tx() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS ai_drafts(
                id TEXT PRIMARY KEY,title TEXT NOT NULL,requirement TEXT NOT NULL,
                provider TEXT NOT NULL,model TEXT NOT NULL,plan TEXT NOT NULL,
                plan_hash TEXT NOT NULL,status TEXT NOT NULL,idempotency TEXT UNIQUE NOT NULL,
                request_hash TEXT NOT NULL,error TEXT,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_draft_items(
                draft_id TEXT NOT NULL,module TEXT NOT NULL,item_key TEXT NOT NULL,
                status TEXT NOT NULL,result TEXT,error TEXT,updated REAL NOT NULL,
                PRIMARY KEY(draft_id,module,item_key),
                FOREIGN KEY(draft_id) REFERENCES ai_drafts(id));
            CREATE TABLE IF NOT EXISTS ai_verifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,draft_id TEXT NOT NULL,
                checked REAL NOT NULL,result TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES ai_drafts(id));
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(ai_drafts)")}
        if "error" not in columns:
            db.execute("ALTER TABLE ai_drafts ADD COLUMN error TEXT")

    def view(db, draft_id):
        row = db.execute("SELECT * FROM ai_drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise HTTPException(404, "AI draft not found")
        items = db.execute(
            "SELECT module,item_key,status,result,error FROM ai_draft_items WHERE draft_id=? ORDER BY module,item_key",
            (draft_id,),
        ).fetchall()
        last_check = db.execute(
            "SELECT checked,result FROM ai_verifications WHERE draft_id=? ORDER BY id DESC LIMIT 1",
            (draft_id,),
        ).fetchone()
        return {
            "id": row["id"],
            "title": row["title"],
            "requirement": row["requirement"],
            "provider": row["provider"],
            "model": row["model"],
            "plan": json.loads(row["plan"]),
            "plan_hash": row["plan_hash"],
            "status": row["status"],
            "error": row["error"],
            "created": row["created"],
            "updated": row["updated"],
            "verification": (
                {"checked": last_check["checked"], **json.loads(last_check["result"])}
                if last_check
                else None
            ),
            "items": [
                {
                    "module": x["module"],
                    "key": x["item_key"],
                    "status": x["status"],
                    "result": json.loads(x["result"]) if x["result"] else None,
                    "error": x["error"],
                }
                for x in items
            ],
        }

    @app.get("/api/v1/ai/drafts", dependencies=[Depends(operator)])
    def drafts():
        with store.tx() as db:
            ids = [
                r[0] for r in db.execute("SELECT id FROM ai_drafts ORDER BY created DESC LIMIT 20")
            ]
            return [view(db, item) for item in ids]

    async def generate_draft(draft_id: str, title: str, requirement: str):
        try:
            plan, provider, model = await generate_plan(store, title, requirement)
            with store.tx() as db:
                db.execute(
                    "UPDATE ai_drafts SET provider=?,model=?,plan=?,plan_hash=?,"
                    "status='DRAFT',error=NULL,updated=? WHERE id=?",
                    (provider, model, json.dumps(plan), _digest(plan), time.time(), draft_id),
                )
        except HTTPException as exc:
            with store.tx() as db:
                db.execute(
                    "UPDATE ai_drafts SET status='FAILED',error=?,updated=? WHERE id=?",
                    (str(exc.detail), time.time(), draft_id),
                )

    @app.post("/api/v1/ai/drafts", dependencies=[Depends(operator)])
    async def create_draft(body: DraftCreate, tasks: BackgroundTasks):
        title, requirement = body.title.strip(), body.requirement.strip()
        request_hash = _digest({"title": title, "requirement": requirement})
        with store.tx() as db:
            old = db.execute(
                "SELECT id,request_hash FROM ai_drafts WHERE idempotency=?", (body.idempotency_key,)
            ).fetchone()
            if old:
                if old["request_hash"] != request_hash:
                    raise HTTPException(409, "Idempotency key already used")
                return view(db, old["id"])
        now, draft_id = time.time(), str(uuid.uuid4())
        with store.tx() as db:
            db.execute(
                "INSERT INTO ai_drafts(id,title,requirement,provider,model,plan,plan_hash,"
                "status,idempotency,request_hash,error,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    title,
                    requirement,
                    "pending",
                    "pending",
                    "{}",
                    "0" * 64,
                    "GENERATING",
                    body.idempotency_key,
                    request_hash,
                    None,
                    now,
                    now,
                ),
            )
            result = view(db, draft_id)
        tasks.add_task(generate_draft, draft_id, title, requirement)
        return result

    @app.put("/api/v1/ai/drafts/{draft_id}", dependencies=[Depends(operator)])
    def update_draft(draft_id: str, body: DraftUpdate):
        try:
            plan = validate_plan(body.plan)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        with store.tx() as db:
            row = db.execute("SELECT status FROM ai_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise HTTPException(404, "AI draft not found")
            if row["status"] != "DRAFT":
                raise HTTPException(409, "Only a draft can be edited")
            db.execute(
                "UPDATE ai_drafts SET plan=?,plan_hash=?,updated=? WHERE id=?",
                (json.dumps(plan), _digest(plan), time.time(), draft_id),
            )
            return view(db, draft_id)

    @app.post("/api/v1/ai/drafts/{draft_id}/approve", dependencies=[Depends(operator)])
    async def approve(draft_id: str, body: DraftApproval, request: Request):
        connection = await app.state.identity_connection(request)
        if not connection:
            raise HTTPException(401, "OIDA identity is unavailable")
        with store.tx() as db:
            draft = view(db, draft_id)
            if draft["status"] not in {"DRAFT", "PARTIAL"}:
                raise HTTPException(409, "Draft is not awaiting approval")
            if draft["plan_hash"] != body.plan_hash:
                raise HTTPException(409, "Draft changed; review it again before approval")
            db.execute(
                "UPDATE ai_drafts SET status='DISTRIBUTING',updated=? WHERE id=?",
                (time.time(), draft_id),
            )
        token, plan = connection["token"], draft["plan"]

        async def ensure(module, key, factory):
            with store.tx() as db:
                row = db.execute(
                    "SELECT status,result FROM ai_draft_items WHERE draft_id=? AND module=? AND item_key=?",
                    (draft_id, module, key),
                ).fetchone()
            if row and row["status"] == "CREATED":
                return json.loads(row["result"])
            try:
                result = await factory()
                if not isinstance(result, dict) or not any(result.values()):
                    raise ValueError("Module returned no record identifier")
                status, error = "CREATED", None
            except (HTTPException, ValueError, KeyError) as exc:
                result, status = None, "FAILED"
                error = exc.detail if isinstance(exc, HTTPException) else str(exc)
            with store.tx() as db:
                db.execute(
                    "INSERT OR REPLACE INTO ai_draft_items VALUES(?,?,?,?,?,?,?)",
                    (
                        draft_id,
                        module,
                        key,
                        status,
                        json.dumps(result) if result else None,
                        error,
                        time.time(),
                    ),
                )
            if status == "FAILED":
                raise HTTPException(502, error)
            return result

        call = app.state.module_json
        failures = []

        try:
            pm = await ensure("pm", "project", lambda: _pm_project(call, token, draft))
            for index, task in enumerate(plan["pm_tasks"]):
                await ensure(
                    "pm", f"task-{index}", lambda task=task: _pm_task(call, token, pm["slug"], task)
                )
        except HTTPException as exc:
            failures.append("PM: " + str(exc.detail))
        try:
            qa = await ensure("qa", "project", lambda: _qa_project(call, token, draft))
            for sidx, suite in enumerate(plan["qa_suites"]):
                created = await ensure(
                    "qa",
                    f"suite-{sidx}",
                    lambda suite=suite: _qa_suite(call, token, qa["slug"], suite),
                )
                revision = await ensure(
                    "qa",
                    f"revision-{sidx}",
                    lambda created=created: _qa_revision(
                        call, token, qa["slug"], created["suite_id"], draft_id
                    ),
                )
                for cidx, case in enumerate(suite["test_cases"]):
                    await ensure(
                        "qa",
                        f"case-{sidx}-{cidx}",
                        lambda case=case, revision=revision, cidx=cidx: _qa_case(
                            call, token, qa["slug"], revision["revision_id"], case, cidx
                        ),
                    )
        except HTTPException as exc:
            failures.append("QA: " + str(exc.detail))
        try:
            document = await ensure(
                "document", "project", lambda: _document_project(call, token, draft, draft_id)
            )
            for index, requirement in enumerate(plan["document_requirements"]):
                await ensure(
                    "document",
                    f"requirement-{index}",
                    lambda requirement=requirement: _document_requirement(
                        call, token, document["project_id"], requirement, draft_id
                    ),
                )
        except HTTPException as exc:
            failures.append("Document: " + str(exc.detail))
        try:
            workspace = await ensure(
                "infra", "workspace", lambda: _infra_workspace(call, token, draft)
            )
            design = await ensure(
                "infra", "design", lambda: _infra_design(call, token, draft, plan["infra"])
            )
            await ensure(
                "infra",
                "flow",
                lambda: _infra_flow(call, token, design["design_id"], plan["infra"]),
            )
            await ensure(
                "infra",
                "link",
                lambda: _infra_link(call, token, workspace["workspace_id"], design["design_id"]),
            )
        except HTTPException as exc:
            failures.append("Infra: " + str(exc.detail))
        with store.tx() as db:
            status = "PARTIAL" if failures else "APPROVED"
            db.execute(
                "UPDATE ai_drafts SET status=?,updated=? WHERE id=?",
                (status, time.time(), draft_id),
            )
            result = view(db, draft_id)
        result["failures"] = failures
        return result

    @app.post("/api/v1/ai/drafts/{draft_id}/verify", dependencies=[Depends(operator)])
    async def verify(draft_id: str, request: Request):
        connection = await app.state.identity_connection(request)
        if not connection:
            raise HTTPException(401, "OIDA identity is unavailable")
        with store.tx() as db:
            draft = view(db, draft_id)
        if draft["status"] != "APPROVED":
            raise HTTPException(409, "Only approved work can run a full-loop check")
        call, token = app.state.module_json, connection["token"]
        checks = await asyncio.gather(
            _safe_check("pm", _verify_pm, call, token, draft),
            _safe_check("qa", _verify_qa, call, token, draft),
            _safe_check("document", _verify_document, call, token, draft),
            _safe_check("infra", _verify_infra, call, token, draft),
        )
        modules = {item["module"]: item for item in checks}
        result = {
            "healthy": all(item["verified"] for item in checks),
            "modules": modules,
        }
        with store.tx() as db:
            db.execute(
                "INSERT INTO ai_verifications(draft_id,checked,result) VALUES(?,?,?)",
                (draft_id, time.time(), json.dumps(result)),
            )
        return {"checked": time.time(), **result}


def _created(draft: dict, module: str, key: str | None = None) -> list[dict]:
    return [
        item
        for item in draft["items"]
        if item["module"] == module
        and item["status"] == "CREATED"
        and (key is None or item["key"] == key)
    ]


async def _safe_check(module: str, checker, call, token: str, draft: dict) -> dict:
    try:
        return {"module": module, **await checker(call, token, draft)}
    except (HTTPException, KeyError, TypeError, ValueError):
        return {
            "module": module,
            "verified": False,
            "state": "UNAVAILABLE",
            "message": f"{module.title()} status could not be verified",
        }


async def _verify_pm(call, token: str, draft: dict) -> dict:
    project = _created(draft, "pm", "project")[0]["result"]
    expected_ids = {
        item["result"]["task_id"]
        for item in _created(draft, "pm")
        if item["key"].startswith("task-")
    }
    tasks = await call("pm", "GET", f"{project['slug']}/tasks", token)
    found = [task for task in tasks if task.get("id") in expected_ids]
    done = sum(task.get("status") == "Done" for task in found)
    return {
        "verified": len(found) == len(expected_ids),
        "state": "DONE" if found and done == len(found) else "IN_PROGRESS",
        "found": len(found),
        "expected": len(expected_ids),
        "done": done,
        "url": f"/pm/{project['slug']}/tasks",
    }


async def _verify_qa(call, token: str, draft: dict) -> dict:
    project = _created(draft, "qa", "project")[0]["result"]
    suite_ids = {
        item["result"]["suite_id"]
        for item in _created(draft, "qa")
        if item["key"].startswith("suite-")
    }
    case_ids = {
        item["result"]["case_id"]
        for item in _created(draft, "qa")
        if item["key"].startswith("case-")
    }
    revision_ids = [
        item["result"]["revision_id"]
        for item in _created(draft, "qa")
        if item["key"].startswith("revision-")
    ]
    suites = await call("qa", "GET", f"{project['slug']}/suites", token)
    found_suites = [suite for suite in suites if suite.get("id") in suite_ids]
    case_lists = await asyncio.gather(
        *(
            call("qa", "GET", f"{project['slug']}/revisions/{item}/cases", token)
            for item in revision_ids
        )
    )
    found_cases = [case for cases in case_lists for case in cases if case.get("id") in case_ids]
    verified = len(found_suites) == len(suite_ids) and len(found_cases) == len(case_ids)
    return {
        "verified": verified,
        "state": "READY_FOR_EXECUTION" if verified else "INCOMPLETE",
        "suites": {"found": len(found_suites), "expected": len(suite_ids)},
        "cases": {"found": len(found_cases), "expected": len(case_ids)},
        "url": f"/qa/{project['slug']}/suites",
    }


async def _verify_document(call, token: str, draft: dict) -> dict:
    project = _created(draft, "document", "project")[0]["result"]
    expected_ids = {
        item["result"]["requirement_id"]
        for item in _created(draft, "document")
        if item["key"].startswith("requirement-")
    }
    requirements = await call(
        "document", "GET", f"projects/{project['project_id']}/requirements", token
    )
    found = [item for item in requirements if item.get("id") in expected_ids]
    confirmed = sum(item.get("status") == "CONFIRMED" for item in found)
    return {
        "verified": len(found) == len(expected_ids),
        "state": "CONFIRMED" if found and confirmed == len(found) else "DRAFT",
        "found": len(found),
        "expected": len(expected_ids),
        "confirmed": confirmed,
        "url": "/documents/#/requirements",
    }


async def _verify_infra(call, token: str, draft: dict) -> dict:
    workspace_id = _created(draft, "infra", "workspace")[0]["result"]["workspace_id"]
    design_id = _created(draft, "infra", "design")[0]["result"]["design_id"]
    workspace, design = await asyncio.gather(
        call("infra", "GET", f"v1/workspaces/{workspace_id}", token),
        call("infra", "GET", f"v1/designs/{design_id}", token),
    )
    linked = (workspace.get("workspace") or {}).get("currentDesignId") == design_id
    status = (design.get("design") or {}).get("status", "UNKNOWN")
    return {
        "verified": linked and bool(design.get("design")),
        "state": status,
        "workspace_id": workspace_id,
        "design_id": design_id,
        "linked": linked,
        "url": "/infra/",
    }


async def _pm_project(call, token, draft):
    r = await call(
        "pm", "POST", "projects", token, body={"name": draft["title"], "project_type": "simple"}
    )
    return {"project_id": r.get("id"), "slug": r.get("slug")}


async def _pm_task(call, token, slug, task):
    r = await call("pm", "POST", f"{slug}/tasks", token, body={**task, "status": "Todo"})
    return {"task_id": r.get("id")}


async def _qa_project(call, token, draft):
    r = await call("qa", "POST", "projects", token, body={"name": draft["title"]})
    return {"project_id": r.get("id"), "slug": r.get("slug")}


async def _qa_suite(call, token, slug, suite):
    r = await call(
        "qa",
        "POST",
        f"{slug}/suites",
        token,
        body={k: suite[k] for k in ("name", "description", "suite_type")},
    )
    return {"suite_id": r.get("id")}


async def _qa_revision(call, token, slug, suite_id, draft_id):
    r = await call(
        "qa",
        "POST",
        f"{slug}/suites/{suite_id}/revisions",
        token,
        body={"revision_label": "AI Draft 1", "change_summary": f"OIDA draft {draft_id}"},
    )
    return {"revision_id": r.get("id")}


async def _qa_case(call, token, slug, revision_id, case, index):
    r = await call(
        "qa",
        "POST",
        f"{slug}/revisions/{revision_id}/cases",
        token,
        body={
            "checkpoint_code": f"AI-{index + 1:03d}",
            "title": case.get("title", "Generated case"),
            "priority": case.get("priority", "MEDIUM"),
            "action_md": case.get("description", "Execute the described scenario."),
            "expected_result_md": case.get("expected_result", "The requirement is satisfied."),
            "category": case.get("category", "FUNCTIONAL"),
            "negative_path": bool(case.get("negative_path", False)),
            "sequence_no": index + 1,
        },
    )
    return {"case_id": r.get("id")}


async def _document_project(call, token, draft, draft_id):
    key = "AI-" + draft_id.split("-")[0].upper()
    r = await call(
        "document",
        "POST",
        "projects",
        token,
        body={
            "key": key,
            "name": draft["title"],
            "description": draft["requirement"],
            "metadata": {"source": "OIDA_AI", "draft_id": draft_id},
        },
    )
    return {"project_id": r.get("id"), "key": r.get("key")}


async def _document_requirement(call, token, project_id, requirement, draft_id):
    criteria = requirement.get("acceptance_criteria") or []
    description = requirement.get("description", "")
    if criteria:
        description += "\n\nAcceptance criteria:\n" + "\n".join(f"- {item}" for item in criteria)
    r = await call(
        "document",
        "POST",
        "requirements",
        token,
        body={
            "project_id": project_id,
            "title": requirement["title"],
            "description": description,
            "priority": requirement.get("priority", "SHOULD"),
            "source_type": "OIDA_AI",
            "source_reference": draft_id,
        },
    )
    return {"requirement_id": r.get("id"), "code": r.get("code")}


async def _infra_workspace(call, token, draft):
    r = await call(
        "infra",
        "POST",
        "v1/workspaces",
        token,
        body={"name": draft["title"], "fidelity": "LOCAL_RUNTIME"},
    )
    return {"workspace_id": (r.get("workspace") or {}).get("workspaceId")}


async def _infra_design(call, token, draft, infra):
    r = await call(
        "infra",
        "POST",
        "v1/designs",
        token,
        params={
            "name": draft["title"],
            "description": infra.get("rationale") or draft["requirement"],
        },
    )
    return {"design_id": (r.get("design") or {}).get("designId")}


async def _infra_flow(call, token, design_id, infra):
    components = infra["components"]
    nodes = [
        {
            "id": f"component-{i + 1}",
            "position": {"x": 280, "y": i * 120},
            "data": {
                "label": name,
                "category": "SERVICE",
                "provider": infra.get("provider", "ON_PREM"),
            },
        }
        for i, name in enumerate(components)
    ]
    edges = [
        {"id": f"edge-{i}-{i + 1}", "source": f"component-{i}", "target": f"component-{i + 1}"}
        for i in range(1, len(nodes))
    ]
    await call(
        "infra",
        "POST",
        f"v1/designs/{design_id}/update-flow",
        token,
        body={"flow": {"nodes": nodes, "edges": edges, "rationale": infra.get("rationale", "")}},
    )
    return {"flow_saved": True, "component_count": len(nodes)}


async def _infra_link(call, token, workspace_id, design_id):
    await call(
        "infra",
        "POST",
        f"v1/workspaces/{workspace_id}/current-design",
        token,
        params={"design_id": design_id},
    )
    return {"linked": True}
