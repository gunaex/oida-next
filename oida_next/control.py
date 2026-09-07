"""Single-process modular control plane, with durable SQLite transactions."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from .models import MODEL_REGISTRY, DeterministicPlanner
from .protocol import (
    TERMINAL,
    Approval,
    Goal,
    Heartbeat,
    Progress,
    Registration,
    Result,
    StrictModel,
    action_plan,
    digest,
)
from .security import password_hash, redact, signature_message


class Login(StrictModel):
    password: str = Field(min_length=1, max_length=256)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.tx() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS enrollment(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,name TEXT NOT NULL,
                    public_key TEXT UNIQUE NOT NULL,capabilities TEXT NOT NULL,seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS nonces(agent TEXT,nonce TEXT,created REAL,
                    PRIMARY KEY(agent,nonce));
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,goal TEXT,target TEXT,
                    action TEXT,action_hash TEXT,state TEXT,lease TEXT,lease_until REAL,
                    created REAL,updated REAL,idempotency TEXT UNIQUE,request_hash TEXT,
                    result TEXT,cancel_requested INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,actor TEXT,agent TEXT,job TEXT,type TEXT,severity TEXT,
                    payload TEXT,correlation_id TEXT);
                CREATE TABLE IF NOT EXISTS progress(job TEXT,sequence INTEGER,
                    PRIMARY KEY(job,sequence));
            """)
        os.chmod(path, 0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize_password(self, password: str):
        if len(password) < 16:
            raise ValueError("Operator password needs at least 16 characters")
        with self.tx() as db:
            if db.execute("SELECT 1 FROM settings WHERE key='password'").fetchone():
                raise ValueError("Operator already initialized; refusing overwrite")
            salt = secrets.token_bytes(16)
            db.execute("INSERT INTO settings VALUES('salt',?)", (salt.hex(),))
            db.execute(
                "INSERT INTO settings VALUES('password',?)", (password_hash(password, salt),)
            )


def event(db, kind: str, actor: str = "system", agent: str = "", job: str = "", payload=None):
    db.execute(
        "INSERT INTO events(timestamp,actor,agent,job,type,severity,payload,correlation_id) VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), actor, agent, job, kind, "info", json.dumps(payload or {}), job),
    )


def job_view(row) -> dict:
    result = dict(row)
    result["action"] = json.loads(result["action"])
    result["result"] = json.loads(result["result"]) if result["result"] else None
    result.pop("request_hash", None)
    return result


def create_app(
    path: Path, local_agent_url: str | None = None, *, identity_config=None, identity_transport=None
) -> FastAPI:
    store = Store(path)
    app = FastAPI(title="OIDA Next", version="0.1.0")
    app.state.store = store
    app.state.local_agent_process = None
    failures: dict[str, list[float]] = {}

    @app.exception_handler(RequestValidationError)
    async def invalid_fields(request: Request, exc: RequestValidationError):
        # Default validation detail can echo password/token input back in a response.
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    def unlock_local_agent(password: str):
        if not local_agent_url:
            return
        existing = app.state.local_agent_process
        if existing is not None and existing.poll() is None:
            return
        from .security import load_key, public_key

        agent_root = path.parent / "local-agent"
        phrase = hashlib.sha256(("oida-next-local-agent-v1:" + password).encode()).hexdigest()
        key = load_key(agent_root / "identity.enc", phrase)
        pub = public_key(key)
        with store.tx() as db:
            registered = db.execute("SELECT 1 FROM agents WHERE public_key=?", (pub,)).fetchone()
            enrollment_token = secrets.token_urlsafe(32)
            if not registered:
                db.execute(
                    "INSERT INTO enrollment VALUES(?,?)",
                    (hashlib.sha256(enrollment_token.encode()).hexdigest(), time.time() + 300),
                )
                event(db, "agent.local_enrollment_created", "operator")
        command = [
            sys.executable,
            "-m",
            "oida_next.agent",
            "--url",
            local_agent_url,
            "--data",
            str(agent_root),
            "--allow-loopback-http",
        ]
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "OIDA_AGENT_PASSPHRASE": phrase,
        }
        if not registered:
            command.append("--enroll")
            env["OIDA_ENROLLMENT_TOKEN"] = enrollment_token
        app.state.local_agent_process = subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    @app.get("/api/v1/setup-status")
    def setup_status():
        with store.tx() as db:
            initialized = bool(db.execute("SELECT 1 FROM settings WHERE key='password'").fetchone())
        return {"initialized": initialized}

    @app.post("/api/v1/setup")
    def setup(body: Login, request: Request):
        # Initial owner setup is deliberately unavailable through a reverse proxy or Tunnel.
        if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(403, "Initial setup requires this machine's loopback browser")
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "Loopback hostname required")
        if request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Same-origin setup required")
        try:
            store.initialize_password(body.password)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"initialized": True}

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        # Host exposure is intentionally controlled by deployment, never trust forwarded headers.
        from .module_gateway import MAX_UPLOAD

        module_proxy = any(
            request.url.path.startswith(f"/api/v1/modules/{name}/proxy/")
            for name in ("pm", "qa", "document", "infra")
        )
        limit = MAX_UPLOAD if module_proxy else 100000
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            size = limit + 1
        if size < 0 or size > limit:
            from starlette.responses import JSONResponse

            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    def operator(request: Request):
        value = request.headers.get("authorization", "")
        if value and not value.startswith("Bearer "):
            raise HTTPException(401, "Invalid authorization scheme")
        raw_token = value[7:] if value else request.cookies.get("__Host-oida_session", "")
        if not raw_token:
            raise HTTPException(401, "Operator login required")
        if (
            not value
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and not permitted_origin(request)
        ):
            raise HTTPException(403, "Same-origin request required")
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with store.tx() as db:
            if not db.execute(
                "SELECT 1 FROM sessions WHERE hash=? AND expires>?", (token_hash, time.time())
            ).fetchone():
                raise HTTPException(401, "Session expired or invalid")
        request.state.operator_session = token_hash
        return "operator"

    def permitted_origin(request: Request) -> bool:
        allowed = {os.environ.get("OIDA_PUBLIC_ORIGIN", "https://oida-next.kanphong.com")}
        if request.url.hostname in {"127.0.0.1", "localhost", "::1"}:
            allowed.add(str(request.base_url).rstrip("/"))
        return request.headers.get("origin") in allowed

    @app.get("/api/v1/session", dependencies=[Depends(operator)])
    def current_session():
        return {"authenticated": True}

    async def agent_auth(request: Request):
        agent = request.headers.get("x-agent-id", "")
        timestamp, nonce = (
            request.headers.get("x-timestamp", ""),
            request.headers.get("x-nonce", ""),
        )
        body = await request.body()
        try:
            if abs(time.time() - int(timestamp)) > 60 or not 16 <= len(nonce) <= 80:
                raise ValueError()
            with store.tx() as db:
                row = db.execute("SELECT public_key FROM agents WHERE id=?", (agent,)).fetchone()
                if not row:
                    raise ValueError()
                key = Ed25519PublicKey.from_public_bytes(base64.b64decode(row[0], validate=True))
                key.verify(
                    base64.b64decode(request.headers.get("x-signature", ""), validate=True),
                    signature_message(request.method, request.url.path, timestamp, nonce, body),
                )
                db.execute("DELETE FROM nonces WHERE created<?", (time.time() - 120,))
                db.execute("INSERT INTO nonces VALUES(?,?,?)", (agent, nonce, time.time()))
        except (ValueError, InvalidSignature, sqlite3.IntegrityError):
            raise HTTPException(401, "Invalid or replayed agent request") from None
        return agent

    def owned(db, job_id: str, agent: str, lease: str | None = None):
        row = db.execute("SELECT * FROM jobs WHERE id=? AND target=?", (job_id, agent)).fetchone()
        if not row or (lease is not None and row["lease"] != lease):
            raise HTTPException(403, "Job ownership or lease mismatch")
        return row

    @app.get("/health")
    def health():
        return {"status": "ok", "product": "OIDA_NEXT"}

    @app.get("/ready")
    def ready():
        with store.tx() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "READY", "database": "READY", "protocol": "oida.v1"}

    @app.post("/api/v1/login")
    def login(body: Login, request: Request, response: Response):
        if request.headers.get("origin") and not permitted_origin(request):
            raise HTTPException(403, "Login origin rejected")
        client = request.client.host if request.client else "unknown"
        now = time.time()
        failures[client] = [t for t in failures.get(client, []) if t > now - 60]
        if len(failures[client]) >= 10:
            raise HTTPException(429, "Too many attempts; retry in one minute")
        with store.tx() as db:
            values = dict(db.execute("SELECT key,value FROM settings"))
            valid = "password" in values and hmac.compare_digest(
                values["password"], password_hash(body.password, bytes.fromhex(values["salt"]))
            )
            if not valid:
                failures[client].append(now)
                raise HTTPException(401, "Invalid credentials")
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute(
                "INSERT INTO sessions VALUES(?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), now + 3600),
            )
            event(db, "operator.login", "operator")
        unlock_local_agent(body.password)
        response.set_cookie(
            "__Host-oida_session",
            token,
            max_age=3600,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return {"access_token": token, "expires_in": 3600}

    @app.post("/api/v1/logout")
    def logout(request: Request, response: Response, actor=Depends(operator)):
        with store.tx() as db:
            db.execute(
                "DELETE FROM sessions WHERE hash=?",
                (request.state.operator_session,),
            )
        app.state.disconnect_identity(request)
        response.delete_cookie(
            "__Host-oida_session", path="/", secure=True, httponly=True, samesite="strict"
        )
        return {"ok": True}

    @app.post("/api/v1/enrollment")
    def enrollment(actor=Depends(operator)):
        token = secrets.token_urlsafe(32)
        with store.tx() as db:
            db.execute(
                "INSERT INTO enrollment VALUES(?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), time.time() + 300),
            )
            event(db, "agent.enrollment_created", actor)
        return {"token": token, "expires_in": 300}

    @app.post("/api/v1/agents/register")
    def register(body: Registration, request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(body.public_key, validate=True))
        except ValueError:
            raise HTTPException(422, "Invalid public key") from None
        with store.tx() as db:
            hashed = hashlib.sha256(token.encode()).hexdigest()
            if not db.execute(
                "SELECT 1 FROM enrollment WHERE hash=? AND expires>?", (hashed, time.time())
            ).fetchone():
                raise HTTPException(401, "Enrollment is invalid, expired, or already used")
            if db.execute("SELECT 1 FROM agents WHERE public_key=?", (body.public_key,)).fetchone():
                raise HTTPException(409, "Key already registered")
            agent = hashlib.sha256(body.public_key.encode()).hexdigest()[:32]
            db.execute("DELETE FROM enrollment WHERE hash=?", (hashed,))
            db.execute(
                "INSERT INTO agents VALUES(?,?,?,?,?)",
                (agent, body.name, body.public_key, json.dumps(body.capabilities), time.time()),
            )
            event(db, "agent.registered", "operator", agent)
        return {"agent_id": agent, "protocol": "oida.v1"}

    @app.post("/api/v1/agents/heartbeat")
    def heartbeat(body: Heartbeat, agent=Depends(agent_auth)):
        with store.tx() as db:
            previous = db.execute(
                "SELECT seen,capabilities FROM agents WHERE id=?", (agent,)
            ).fetchone()
            if previous[0] < time.time() - 20:
                event(db, "agent.connected", agent, agent)
            if json.loads(previous[1]) != body.capabilities:
                event(db, "agent.capabilities_changed", agent, agent)
            db.execute(
                "UPDATE agents SET seen=?,capabilities=? WHERE id=?",
                (time.time(), json.dumps(body.capabilities), agent),
            )
            db.execute(
                "UPDATE jobs SET lease_until=? WHERE target=? AND state IN ('DISPATCHED','RUNNING')",
                (time.time() + 30, agent),
            )
        return {"ok": True}

    @app.get("/api/v1/agents")
    def agents(actor=Depends(operator)):
        with store.tx() as db:
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "capabilities": json.loads(r["capabilities"]),
                    "online": r["seen"] > time.time() - 20,
                    "last_seen": r["seen"],
                }
                for r in db.execute("SELECT * FROM agents")
            ]

    from .ecosystem import install

    install(app, store, operator, event)
    from .identity_bridge import install_identity

    install_identity(app, operator, identity_config, identity_transport, store, event)
    from .ai_runtime import install_ai

    install_ai(app, store, operator)

    @app.get("/api/v1/models")
    def models(actor=Depends(operator)):
        return MODEL_REGISTRY

    @app.post("/api/v1/goals")
    def submit(body: Goal, actor=Depends(operator)):
        try:
            recipe = body.recipe or DeterministicPlanner().plan(body.goal)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        plan = action_plan(recipe, body.target, body.timeout)
        with store.tx() as db:
            old = db.execute(
                "SELECT * FROM jobs WHERE idempotency=?", (body.idempotency_key,)
            ).fetchone()
            if old:
                if old["request_hash"] != digest(body.model_dump()):
                    raise HTTPException(409, "Idempotency key reused for a different goal")
                return job_view(old)
            target = db.execute(
                "SELECT capabilities FROM agents WHERE id=?", (body.target,)
            ).fetchone()
            if not target:
                raise HTTPException(404, "Agent not found")
            caps = json.loads(target[0])
            if not caps.get("python") or caps.get("os") != "Linux":
                raise HTTPException(409, "Target lacks required Linux/Python capabilities")
            job, now = uuid.uuid4().hex, time.time()
            state = "WAITING_APPROVAL" if plan["risk"] == "MEDIUM" else "QUEUED"
            db.execute(
                "INSERT INTO jobs(id,goal,target,action,action_hash,state,created,updated,idempotency,request_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job,
                    redact(body.goal),
                    body.target,
                    json.dumps(plan),
                    digest(plan),
                    state,
                    now,
                    now,
                    body.idempotency_key,
                    digest(body.model_dump()),
                ),
            )
            event(db, "job.created", actor, body.target, job)
            event(
                db,
                "job.approval_required" if state == "WAITING_APPROVAL" else "job.queued",
                actor,
                body.target,
                job,
                {"action_hash": digest(plan)},
            )
            return job_view(db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())

    @app.get("/api/v1/jobs")
    def jobs(actor=Depends(operator)):
        with store.tx() as db:
            return [
                job_view(r)
                for r in db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100")
            ]

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str, actor=Depends(operator)):
        with store.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Job not found")
            return job_view(row)

    @app.post("/api/v1/jobs/{job_id}/approval")
    def approval(job_id: str, body: Approval, actor=Depends(operator)):
        with store.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if (
                not row
                or row["state"] != "WAITING_APPROVAL"
                or row["action_hash"] != body.action_hash
            ):
                raise HTTPException(409, "Approval must match the exact waiting action")
            state = "QUEUED" if body.approve else "CANCELLED"
            db.execute("UPDATE jobs SET state=?,updated=? WHERE id=?", (state, time.time(), job_id))
            event(
                db,
                "job.approved" if body.approve else "job.rejected",
                actor,
                row["target"],
                job_id,
                {"action_hash": body.action_hash},
            )
        return {"state": state}

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str, actor=Depends(operator)):
        with store.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Job not found")
            if row["state"] in TERMINAL:
                return {"state": row["state"]}
            state = "CANCELLED" if row["state"] in {"QUEUED", "WAITING_APPROVAL"} else row["state"]
            db.execute(
                "UPDATE jobs SET cancel_requested=1,state=?,updated=? WHERE id=?",
                (state, time.time(), job_id),
            )
            event(db, "job.cancel_requested", actor, row["target"], job_id)
        return {"state": state}

    @app.post("/api/v1/agents/claim")
    def claim(agent=Depends(agent_auth)):
        with store.tx() as db:
            # Never redeliver an uncertain started job to a different execution.
            old = db.execute(
                "SELECT * FROM jobs WHERE target=? AND state IN ('DISPATCHED','RUNNING') ORDER BY created LIMIT 1",
                (agent,),
            ).fetchone()
            if old:
                return job_view(old)
            row = db.execute(
                "SELECT * FROM jobs WHERE target=? AND state='QUEUED' ORDER BY created LIMIT 1",
                (agent,),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE jobs SET state='DISPATCHED',lease=?,lease_until=?,updated=? WHERE id=?",
                (uuid.uuid4().hex, time.time() + 30, time.time(), row["id"]),
            )
            event(db, "job.dispatched", "scheduler", agent, row["id"])
            return job_view(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    @app.get("/api/v1/agents/jobs/{job_id}")
    def agent_job(job_id: str, agent=Depends(agent_auth)):
        with store.tx() as db:
            return job_view(owned(db, job_id, agent))

    @app.post("/api/v1/agents/jobs/{job_id}/progress")
    def progress(job_id: str, body: Progress, agent=Depends(agent_auth)):
        with store.tx() as db:
            row = owned(db, job_id, agent, body.lease)
            if row["state"] in TERMINAL:
                return {"accepted": False}
            if db.execute(
                "SELECT 1 FROM progress WHERE job=? AND sequence=?", (job_id, body.sequence)
            ).fetchone():
                return {"accepted": True, "duplicate": True}
            db.execute("INSERT INTO progress VALUES(?,?)", (job_id, body.sequence))
            db.execute(
                "UPDATE jobs SET state='RUNNING',updated=? WHERE id=?", (time.time(), job_id)
            )
            event(
                db,
                "job.output",
                agent,
                agent,
                job_id,
                {"sequence": body.sequence, "output": redact(body.output)},
            )
        return {"accepted": True}

    @app.post("/api/v1/agents/jobs/{job_id}/result")
    def result(job_id: str, body: Result, agent=Depends(agent_auth)):
        if hashlib.sha256(body.evidence.encode()).hexdigest() != body.checksum:
            raise HTTPException(422, "Evidence checksum mismatch")
        if body.state == "SUCCEEDED" and body.exit_code != 0:
            raise HTTPException(422, "Success requires exit code zero")
        sanitized = body.model_dump()
        sanitized["output"] = redact(body.output)
        sanitized["evidence"] = redact(body.evidence)
        sanitized["checksum"] = hashlib.sha256(sanitized["evidence"].encode()).hexdigest()
        with store.tx() as db:
            row = owned(db, job_id, agent, body.lease)
            if row["cancel_requested"] and body.state == "SUCCEEDED":
                sanitized["state"] = "CANCELLED"
            if row["result"]:
                if json.loads(row["result"]) != sanitized:
                    raise HTTPException(409, "A different final result already exists")
                return {"accepted": True, "duplicate": True}
            if row["state"] in TERMINAL:
                raise HTTPException(409, "Job already closed")
            event(
                db,
                "task.validation_passed",
                "validator",
                agent,
                job_id,
                {"checksum": sanitized["checksum"]},
            )
            db.execute(
                "UPDATE jobs SET state=?,result=?,updated=? WHERE id=?",
                (sanitized["state"], json.dumps(sanitized), time.time(), job_id),
            )
            event(db, "job.completed", agent, agent, job_id, {"state": sanitized["state"]})
        return {"accepted": True}

    @app.get("/api/v1/events")
    def events(after: int = 0, actor=Depends(operator)):
        with store.tx() as db:
            return [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT * FROM events WHERE id>? ORDER BY id LIMIT 200", (after,)
                )
            ]

    @app.get("/api/v1/jobs/{job_id}/evidence")
    def evidence(job_id: str, actor=Depends(operator)):
        with store.tx() as db:
            row = db.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or not row[0]:
                raise HTTPException(404, "No evidence yet")
            result = json.loads(row[0])
        return {"content": result["evidence"], "sha256": result["checksum"]}

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "web/index.html")

    @app.get("/app.js")
    def javascript():
        return FileResponse(Path(__file__).parent / "web/app.js", media_type="text/javascript")

    @app.get("/style.css")
    def css():
        return FileResponse(Path(__file__).parent / "web/style.css", media_type="text/css")

    @app.get("/orchestrator.css")
    def orchestrator_css():
        return FileResponse(Path(__file__).parent / "web/orchestrator.css", media_type="text/css")

    @app.get("/ecosystem.js")
    def ecosystem_javascript():
        return FileResponse(
            Path(__file__).parent / "web/ecosystem.js", media_type="text/javascript"
        )

    @app.get("/setup.js")
    def setup_javascript():
        return FileResponse(Path(__file__).parent / "web/setup.js", media_type="text/javascript")

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/control.db"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--init", action="store_true")
    parser.add_argument(
        "--socket", type=Path, help="Optional Unix socket for private Tunnel ingress"
    )
    parser.add_argument(
        "--local-agent",
        action="store_true",
        help="Unlock an isolated local agent when the operator logs in",
    )
    args = parser.parse_args()
    from .identity_bridge import configured_identity

    app = create_app(
        args.data,
        f"http://127.0.0.1:{args.port}" if args.local_agent else None,
        identity_config=configured_identity(),
    )
    if args.init:
        import getpass

        app.state.store.initialize_password(
            getpass.getpass("New operator password (16+ characters): ")
        )
    if not args.socket:
        uvicorn.run(app, host=args.host, port=args.port, access_log=False, proxy_headers=False)
        return
    args.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if args.socket.exists() or args.socket.is_symlink():
        if (
            args.socket.is_symlink()
            or not args.socket.is_socket()
            or args.socket.stat().st_uid != os.getuid()
        ):
            raise SystemExit("Refusing to replace an unexpected ingress socket path")
        args.socket.unlink()
    local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    local.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    local.bind((args.host, args.port))
    ingress = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    ingress.bind(str(args.socket))
    os.chmod(args.socket, 0o660)
    try:
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, proxy_headers=False))
        server.run(sockets=[local, ingress])
    finally:
        local.close()
        ingress.close()


if __name__ == "__main__":
    main()
