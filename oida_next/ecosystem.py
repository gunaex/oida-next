"""Operator-owned cross-application work records; no remote authority implied."""

import json
import time
import uuid
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field

from .protocol import StrictModel


class Work(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)


class Reference(StrictModel):
    system: Literal["pm", "qa", "document", "infra"]
    external_id: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)


class State(StrictModel):
    status: Literal["OPEN", "IN_PROGRESS", "BLOCKED", "DONE"]


class Project(StrictModel):
    name: str = Field(min_length=1, max_length=200)


def install(app, store, operator, event):
    with store.tx() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS ecosystem_work(
                id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,
                status TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS ecosystem_refs(
                work_id TEXT REFERENCES ecosystem_work(id),system TEXT NOT NULL,
                external_id TEXT NOT NULL,note TEXT NOT NULL,
                PRIMARY KEY(work_id,system,external_id));
            CREATE TABLE IF NOT EXISTS ecosystem_jobs(
                work_id TEXT NOT NULL REFERENCES ecosystem_work(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                PRIMARY KEY(work_id,job_id));
            CREATE TABLE IF NOT EXISTS ecosystem_projects(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS ecosystem_project_links(
                project_id TEXT NOT NULL REFERENCES ecosystem_projects(id),
                system TEXT NOT NULL,external_id TEXT NOT NULL,
                PRIMARY KEY(project_id,system),UNIQUE(system,external_id));
            CREATE TABLE IF NOT EXISTS ecosystem_project_work(
                work_id TEXT PRIMARY KEY REFERENCES ecosystem_work(id),
                project_id TEXT NOT NULL REFERENCES ecosystem_projects(id));
        """)

    def require_work(db, work_id):
        if not db.execute("SELECT 1 FROM ecosystem_work WHERE id=?", (work_id,)).fetchone():
            raise HTTPException(404, "Work not found")

    def require_project(db, project_id):
        if not db.execute("SELECT 1 FROM ecosystem_projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")

    @app.post("/api/v1/projects", dependencies=[Depends(operator)], status_code=201)
    def create_project(body: Project):
        if not body.name.strip():
            raise HTTPException(422, "Name must not be blank")
        project_id = str(uuid.uuid4())
        with store.tx() as db:
            db.execute(
                "INSERT INTO ecosystem_projects VALUES(?,?,?)",
                (project_id, body.name.strip(), time.time()),
            )
            event(db, "project.created", "operator", payload={"project_id": project_id})
        return {"id": project_id, "remote_created": False}

    @app.get("/api/v1/projects", dependencies=[Depends(operator)])
    def projects():
        with store.tx() as db:
            items = []
            for row in db.execute(
                "SELECT * FROM ecosystem_projects ORDER BY created DESC LIMIT 200"
            ):
                item = dict(row)
                item["links"] = [
                    dict(x)
                    for x in db.execute(
                        "SELECT system,external_id FROM ecosystem_project_links WHERE project_id=?",
                        (row["id"],),
                    )
                ]
                item["work_ids"] = [
                    x[0]
                    for x in db.execute(
                        "SELECT work_id FROM ecosystem_project_work WHERE project_id=?",
                        (row["id"],),
                    )
                ]
                item["remote_verified"] = False
                items.append(item)
            return items

    @app.put("/api/v1/projects/{project_id}/links", dependencies=[Depends(operator)])
    def map_project(project_id: str, body: Reference):
        import sqlite3

        external_id = body.external_id.strip()
        if not external_id:
            raise HTTPException(422, "Reference must not be blank")
        with store.tx() as db:
            require_project(db, project_id)
            existing = db.execute(
                "SELECT external_id FROM ecosystem_project_links WHERE project_id=? AND system=?",
                (project_id, body.system),
            ).fetchone()
            if existing:
                if existing[0] != external_id:
                    raise HTTPException(409, "Project already mapped; refusing silent reassignment")
            else:
                try:
                    db.execute(
                        "INSERT INTO ecosystem_project_links VALUES(?,?,?)",
                        (project_id, body.system, external_id),
                    )
                except sqlite3.IntegrityError:
                    raise HTTPException(409, "External project already mapped") from None
                event(
                    db,
                    "project.mapped",
                    "operator",
                    payload={"project_id": project_id, "system": body.system},
                )
        return {"mapped": True, "remote_verified": False}

    @app.put("/api/v1/projects/{project_id}/work/{work_id}", dependencies=[Depends(operator)])
    def map_work(project_id: str, work_id: str):
        with store.tx() as db:
            require_project(db, project_id)
            require_work(db, work_id)
            old = db.execute(
                "SELECT project_id FROM ecosystem_project_work WHERE work_id=?", (work_id,)
            ).fetchone()
            if old and old[0] != project_id:
                raise HTTPException(409, "Work already belongs to another project")
            if not old:
                db.execute("INSERT INTO ecosystem_project_work VALUES(?,?)", (work_id, project_id))
                event(
                    db,
                    "project.work_attached",
                    "operator",
                    payload={"project_id": project_id, "work_id": work_id},
                )
        return {"attached": True}

    @app.put("/api/v1/work/{work_id}/jobs/{job_id}", dependencies=[Depends(operator)])
    def link_job(work_id: str, job_id: str):
        with store.tx() as db:
            require_work(db, work_id)
            if not db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise HTTPException(404, "Job not found")
            inserted = db.execute(
                "INSERT OR IGNORE INTO ecosystem_jobs VALUES(?,?)", (work_id, job_id)
            ).rowcount
            if inserted:
                event(db, "work.job_linked", "operator", job=job_id, payload={"work_id": work_id})
        return {"linked": True, "execution_started": False}

    @app.get("/api/v1/work/{work_id}/execution", dependencies=[Depends(operator)])
    def execution(work_id: str):
        with store.tx() as db:
            require_work(db, work_id)
            jobs = []
            for row in db.execute(
                """SELECT j.id,j.goal,j.state,j.result FROM jobs j
                JOIN ecosystem_jobs e ON e.job_id=j.id WHERE e.work_id=?
                ORDER BY j.created""",
                (work_id,),
            ):
                item = dict(row)
                result = json.loads(item.pop("result")) if row["result"] else None
                item["evidence"] = (
                    {"content": result["evidence"], "sha256": result["checksum"]}
                    if result
                    else None
                )
                jobs.append(item)
        return {"work_id": work_id, "jobs": jobs, "remote_synced": False}

    @app.get("/api/v1/ecosystem", dependencies=[Depends(operator)])
    def capabilities():
        return {
            "mode": "reference_only",
            "remote_execution": False,
            "systems": [
                {"id": "pm", "url": "https://pmagain.kanphong.com", "sync": "NOT_CONFIGURED"},
                {"id": "qa", "url": "https://qaagain.kanphong.com", "sync": "NOT_CONFIGURED"},
                {"id": "document", "url": None, "sync": "NOT_CONFIGURED"},
                {"id": "infra", "url": None, "sync": "NOT_CONFIGURED"},
            ],
        }

    @app.get("/api/v1/work", dependencies=[Depends(operator)])
    def list_work():
        with store.tx() as db:
            result = []
            for row in db.execute("SELECT * FROM ecosystem_work ORDER BY created DESC LIMIT 200"):
                item = dict(row)
                item["references"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT system,external_id,note FROM ecosystem_refs WHERE work_id=?",
                        (row["id"],),
                    )
                ]
                result.append(item)
            return result

    @app.post("/api/v1/work", dependencies=[Depends(operator)], status_code=201)
    def create_work(body: Work):
        if not body.title.strip():
            raise HTTPException(422, "Title must not be blank")
        work_id = str(uuid.uuid4())
        now = time.time()
        with store.tx() as db:
            db.execute(
                "INSERT INTO ecosystem_work VALUES(?,?,?,?,?,?)",
                (work_id, body.title.strip(), body.description, "OPEN", now, now),
            )
            event(db, "work.created", "operator", payload={"work_id": work_id})
        return {"id": work_id, "status": "OPEN"}

    @app.patch("/api/v1/work/{work_id}", dependencies=[Depends(operator)])
    def change_state(work_id: str, body: State):
        with store.tx() as db:
            require_work(db, work_id)
            db.execute(
                "UPDATE ecosystem_work SET status=?,updated=? WHERE id=?",
                (body.status, time.time(), work_id),
            )
            event(
                db,
                "work.status_changed",
                "operator",
                payload={"work_id": work_id, "status": body.status},
            )
        return {"id": work_id, "status": body.status}

    @app.put("/api/v1/work/{work_id}/references", dependencies=[Depends(operator)])
    def attach(work_id: str, body: Reference):
        if not body.external_id.strip():
            raise HTTPException(422, "Reference must not be blank")
        with store.tx() as db:
            require_work(db, work_id)
            db.execute(
                """INSERT INTO ecosystem_refs VALUES(?,?,?,?)
                ON CONFLICT(work_id,system,external_id) DO UPDATE SET note=excluded.note""",
                (work_id, body.system, body.external_id.strip(), body.note),
            )
            event(
                db,
                "work.reference_attached",
                "operator",
                payload={"work_id": work_id, "system": body.system},
            )
        return {"saved": True, "remote_synced": False}
