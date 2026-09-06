"""Session-bound Account Again connection; secrets stay out of browser/storage.

This is a transitional linking flow, not a replacement for OIDA owner login.
Module authorization remains module-owned. Connections deliberately expire and
are lost on restart rather than retaining account passwords or refresh tokens.
"""

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import Field, SecretStr

from .module_client import ModuleConfig, ModuleUnavailable, ProjectReader
from .module_gateway import GatewayTarget, forward_module
from .module_pairing import PairingDenied, pair_account
from .protocol import StrictModel


@dataclass(frozen=True)
class IdentityConfig:
    origin: str
    pm_origin: str
    qa_origin: str
    account_socket: str | None = None
    document_origin: str | None = None
    infra_origin: str | None = None
    module_sockets: dict[str, str] = field(default_factory=dict)
    owner_exchange_token: SecretStr | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.owner_exchange_token and not self.account_socket:
            raise ValueError("Owner exchange requires a private Account socket")
        ModuleConfig("pm", self.origin)
        ModuleConfig("pm", self.pm_origin)
        ModuleConfig("qa", self.qa_origin)
        for origin in (self.document_origin, self.infra_origin):
            if origin:
                ModuleConfig("pm", origin)
        for name, socket in self.module_sockets.items():
            if name not in {"pm", "qa", "document", "infra"}:
                raise ValueError("Unsupported private module")
            GatewayTarget("https://private.invalid", socket)
        if self.account_socket is not None:
            path = PurePosixPath(self.account_socket)
            if not path.is_absolute() or ".." in path.parts or str(path) == "/":
                raise ValueError("Account socket must be an explicit absolute file path")


def configured_identity() -> IdentityConfig | None:
    values = [
        os.environ.get(name, "")
        for name in ("OIDA_ACCOUNT_ORIGIN", "OIDA_PM_ORIGIN", "OIDA_QA_ORIGIN")
    ]
    if not any(values):
        return None
    if not all(values):
        raise ValueError("All three identity/module origins must be configured together")
    return IdentityConfig(
        values[0],
        values[1],
        values[2],
        account_socket=os.environ.get("OIDA_ACCOUNT_SOCKET") or None,
        owner_exchange_token=SecretStr(os.environ["OIDA_OWNER_EXCHANGE_TOKEN"])
        if os.environ.get("OIDA_OWNER_EXCHANGE_TOKEN")
        else None,
        document_origin=os.environ.get("OIDA_DOCUMENT_ORIGIN") or None,
        infra_origin=os.environ.get("OIDA_INFRA_ORIGIN") or None,
        module_sockets={
            name: socket
            for name in ("pm", "qa", "document", "infra")
            if (socket := os.environ.get(f"OIDA_{name.upper()}_SOCKET"))
        },
    )


class IdentityLogin(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=256)


class OrchestrationRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=16, max_length=100)


def install_identity(
    app, operator, config: IdentityConfig | None, transport=None, store=None, event=None
):
    connections: dict[str, dict] = {}
    attempts: dict[str, list[float]] = {}

    if store is not None:
        with store.tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrations(
                    id TEXT PRIMARY KEY,title TEXT NOT NULL,requirement TEXT NOT NULL,
                    idempotency TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,
                    created REAL NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS orchestration_targets(
                    orchestration_id TEXT NOT NULL,module TEXT NOT NULL,status TEXT NOT NULL,
                    result TEXT,error TEXT,updated REAL NOT NULL,
                    PRIMARY KEY(orchestration_id,module),
                    FOREIGN KEY(orchestration_id) REFERENCES orchestrations(id));
            """)

    def session_key(request):
        return request.state.operator_session

    app.state.disconnect_identity = lambda request: connections.pop(session_key(request), None)

    def prune():
        now = time.time()
        for key in list(connections):
            if connections[key]["expires"] <= now:
                del connections[key]
        for key in list(attempts):
            attempts[key] = [stamp for stamp in attempts[key] if now - stamp < 60]
            if not attempts[key]:
                del attempts[key]

    @app.get("/api/v1/identity", dependencies=[Depends(operator)])
    async def status(request: Request):
        connection = await connected(request)
        return {
            "configured": config is not None,
            "sso": bool(config and config.owner_exchange_token),
            "connected": bool(connection),
            "email": connection["email"] if connection else None,
            "expires": connection["expires"] if connection else None,
        }

    @app.delete("/api/v1/identity", dependencies=[Depends(operator)])
    def disconnect(request: Request):
        connections.pop(session_key(request), None)
        return {"disconnected": True}

    async def establish(body: IdentityLogin | None, request: Request):
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        capability = config.owner_exchange_token
        if body is None and capability is None:
            raise HTTPException(503, "Owner SSO is not configured")
        prune()
        # Global owner-level limit: issuing a fresh OIDA session cannot bypass it.
        history = attempts.setdefault("operator", [])
        if len(history) >= 5:
            raise HTTPException(429, "Please wait before retrying identity login")
        history.append(time.time())
        # Private Account deployment never needs a public hostname or TCP port.
        # The socket is operator-configured, never selected by a browser request.
        account_transport = (
            httpx.AsyncHTTPTransport(uds=config.account_socket)
            if config.account_socket
            else transport
        )
        account_origin = "http://localhost" if config.account_socket else config.origin.rstrip("/")
        try:
            async with (
                httpx.AsyncClient(
                    transport=account_transport, timeout=10, follow_redirects=False, trust_env=False
                ) as client,
                client.stream(
                    "POST",
                    account_origin
                    + ("/api/v1/auth/ecosystem-token" if body else "/api/v1/oida/owner-token"),
                    json={"email": body.email, "password": body.password.get_secret_value()}
                    if body
                    else None,
                    headers={"Authorization": "Bearer " + capability.get_secret_value()}
                    if body is None and capability
                    else None,
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise HTTPException(401, "Shared identity login denied")
                if response.status_code != 200:
                    raise HTTPException(502, "Shared identity service unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > 32768:
                        raise HTTPException(502, "Invalid identity response")
            import json

            result = json.loads(content)
            token = result.get("accessToken")
            ttl = result.get("expiresIn")
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 16384
                or any(c.isspace() for c in token)
                or not isinstance(ttl, int)
                or isinstance(ttl, bool)
                or not 0 < ttl <= 3600
                or not isinstance(result.get("email"), str)
                or not 3 <= len(result["email"]) <= 254
                or (body is not None and result.get("email") != body.email)
                or result.get("tokenType") != "Bearer"
            ):
                raise HTTPException(502, "Invalid identity response")
            if result.get("mustChangePassword", False) is not False:
                raise HTTPException(403, "Change your Account Again password before connecting")
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            raise HTTPException(502, "Shared identity request failed") from None
        connections[session_key(request)] = {
            "token": token,
            "expires": time.time() + ttl,
            "email": result["email"],
        }
        return {"connected": True, "email": result["email"], "expires_in": ttl}

    async def connected(request):
        prune()
        key = session_key(request)
        if key not in connections and config and config.owner_exchange_token:
            await establish(None, request)
        return connections.get(key)

    async def module_json(
        module: str, method: str, path: str, token: str, *, body=None, params=None
    ):
        if config is None:
            raise HTTPException(503, "Ecosystem orchestration is not configured")
        origin = getattr(config, f"{module}_origin")
        socket = config.module_sockets.get(module)
        target_origin = "http://localhost" if socket else origin.rstrip("/")
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=socket) if socket else transport,
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    target_origin + "/api/" + path,
                    headers={"Authorization": "Bearer " + token},
                    json=body,
                    params=params,
                )
            if response.status_code >= 500 or 300 <= response.status_code < 400:
                raise HTTPException(502, f"{module.title()} service unavailable")
            if response.status_code >= 400:
                raise HTTPException(response.status_code, f"{module.title()} rejected the request")
            value = response.json()
            if not isinstance(value, dict):
                raise TypeError("Unexpected module response")
            return value
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise HTTPException(502, f"{module.title()} service unavailable") from None

    def orchestration_view(db, orchestration_id: str):
        row = db.execute("SELECT * FROM orchestrations WHERE id=?", (orchestration_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Orchestration not found")
        targets = db.execute(
            "SELECT module,status,result,error,updated FROM orchestration_targets "
            "WHERE orchestration_id=? ORDER BY module",
            (orchestration_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "title": row["title"],
            "requirement": row["requirement"],
            "idempotency_key": row["idempotency"],
            "created": row["created"],
            "updated": row["updated"],
            "status": "COMPLETE"
            if len(targets) == 4 and all(t["status"] == "CREATED" for t in targets)
            else "PARTIAL"
            if targets
            else "PENDING",
            "targets": {
                t["module"]: {
                    "status": t["status"],
                    "result": json.loads(t["result"]) if t["result"] else None,
                    "error": t["error"],
                    "updated": t["updated"],
                }
                for t in targets
            },
        }

    @app.get("/api/v1/orchestrations", dependencies=[Depends(operator)])
    def list_orchestrations():
        if store is None:
            return []
        with store.tx() as db:
            ids = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM orchestrations ORDER BY created DESC LIMIT 20"
                ).fetchall()
            ]
            return [orchestration_view(db, item) for item in ids]

    @app.post("/api/v1/orchestrations", dependencies=[Depends(operator)])
    async def orchestrate(body: OrchestrationRequest, request: Request):
        if not config or store is None:
            raise HTTPException(503, "Ecosystem orchestration is not configured")
        connection = await connected(request)
        if not connection:
            raise HTTPException(401, "OIDA session is not connected")
        title = body.title.strip()
        requirement = body.requirement.strip()
        if not title or not requirement:
            raise HTTPException(422, "Title and requirement are required")
        request_hash = hashlib.sha256(
            json.dumps({"title": title, "requirement": requirement}, sort_keys=True).encode()
        ).hexdigest()
        now = time.time()
        with store.tx() as db:
            existing = db.execute(
                "SELECT id,request_hash FROM orchestrations WHERE idempotency=?",
                (body.idempotency_key,),
            ).fetchone()
            if existing and existing["request_hash"] != request_hash:
                raise HTTPException(409, "Idempotency key was already used for another requirement")
            orchestration_id = existing["id"] if existing else str(uuid.uuid4())
            if not existing:
                db.execute(
                    "INSERT INTO orchestrations VALUES(?,?,?,?,?,?,?)",
                    (
                        orchestration_id,
                        title,
                        requirement,
                        body.idempotency_key,
                        request_hash,
                        now,
                        now,
                    ),
                )

        async def create_target(module: str):
            with store.tx() as db:
                saved = db.execute(
                    "SELECT status,result FROM orchestration_targets WHERE orchestration_id=? AND module=?",
                    (orchestration_id, module),
                ).fetchone()
            if saved and saved["status"] == "CREATED":
                return
            partial = json.loads(saved["result"]) if saved and saved["result"] else {}
            result: dict | None
            try:
                if module == "pm":
                    remote = await module_json(
                        module,
                        "POST",
                        "projects",
                        connection["token"],
                        body={"name": title, "project_type": "simple"},
                    )
                    result = {"project_id": remote.get("id"), "slug": remote.get("slug")}
                elif module == "qa":
                    remote = await module_json(
                        module, "POST", "projects", connection["token"], body={"name": title}
                    )
                    result = {"project_id": remote.get("id"), "slug": remote.get("slug")}
                elif module == "document":
                    if "project_id" not in partial:
                        key = "OIDA-" + orchestration_id.split("-")[0].upper()
                        remote = await module_json(
                            module,
                            "POST",
                            "projects",
                            connection["token"],
                            body={
                                "key": key,
                                "name": title,
                                "description": requirement,
                                "metadata": {
                                    "source": "OIDA",
                                    "orchestration_id": orchestration_id,
                                },
                            },
                        )
                        partial = {"project_id": remote.get("id"), "key": remote.get("key")}
                        with store.tx() as db:
                            db.execute(
                                "INSERT OR REPLACE INTO orchestration_targets VALUES(?,?,?,?,?,?)",
                                (
                                    orchestration_id,
                                    module,
                                    "IN_PROGRESS",
                                    json.dumps(partial),
                                    None,
                                    time.time(),
                                ),
                            )
                    remote = await module_json(
                        module,
                        "POST",
                        "requirements",
                        connection["token"],
                        body={
                            "project_id": partial["project_id"],
                            "title": title,
                            "description": requirement,
                            "source_type": "OIDA",
                            "source_reference": orchestration_id,
                            "priority": "MUST",
                        },
                    )
                    result = {
                        **partial,
                        "requirement_id": remote.get("id"),
                        "requirement_code": remote.get("code"),
                    }
                else:
                    remote = await module_json(
                        module,
                        "POST",
                        "v1/designs",
                        connection["token"],
                        params={"name": title, "description": requirement},
                    )
                    design = remote.get("design") or {}
                    result = {"design_id": design.get("designId") or design.get("design_id")}
                if not any(result.values()):
                    raise ValueError("Missing created record identifier")
                status, error_text = "CREATED", None
            except (HTTPException, ValueError) as exc:
                result = partial or None
                status = "FAILED"
                error_text = (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else f"{module.title()} returned an invalid result"
                )
            with store.tx() as db:
                db.execute(
                    "INSERT OR REPLACE INTO orchestration_targets VALUES(?,?,?,?,?,?)",
                    (
                        orchestration_id,
                        module,
                        status,
                        json.dumps(result) if result else None,
                        error_text,
                        time.time(),
                    ),
                )
                db.execute(
                    "UPDATE orchestrations SET updated=? WHERE id=?",
                    (time.time(), orchestration_id),
                )

        for module in ("pm", "qa", "document", "infra"):
            await create_target(module)
        with store.tx() as db:
            return orchestration_view(db, orchestration_id)

    @app.post("/api/v1/identity", dependencies=[Depends(operator)])
    async def connect(body: IdentityLogin, request: Request):
        if config and config.owner_exchange_token:
            raise HTTPException(409, "Use your OIDA owner session")
        return await establish(body, request)

    @app.get("/api/v1/modules/{module}/projects", dependencies=[Depends(operator)])
    async def projects(module: str, request: Request):
        if module not in {"pm", "qa"}:
            raise HTTPException(404, "Module not supported")
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        connection = await connected(request)
        if not connection:
            raise HTTPException(401, "Connect your shared identity first")
        origin = config.pm_origin if module == "pm" else config.qa_origin
        try:
            return await ProjectReader(ModuleConfig(module, origin), transport).list_projects(
                connection["token"]
            )
        except ModuleUnavailable:
            raise HTTPException(502, "Module unavailable or identity denied") from None

    @app.post("/api/v1/modules/{module}/pair", dependencies=[Depends(operator)])
    async def pair(module: str, body: IdentityLogin, request: Request):
        if module not in {"pm", "qa"}:
            raise HTTPException(404, "Module not supported")
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        connection = await connected(request)
        if not connection:
            raise HTTPException(401, "Connect your shared identity first")
        history = attempts.setdefault("pair-" + module, [])
        if len(history) >= 5:
            raise HTTPException(429, "Please wait before retrying module pairing")
        history.append(time.time())
        origin = config.pm_origin if module == "pm" else config.qa_origin
        try:
            result = await pair_account(
                ModuleConfig(module, origin),
                body.email,
                body.password.get_secret_value(),
                connection["token"],
                transport,
            )
        except PairingDenied as error:
            raise HTTPException(error.status, error.message) from None
        if store is not None and event is not None:
            with store.tx() as db:
                event(db, "identity.paired", "operator", payload={"system": module})
        return result

    @app.api_route(
        "/api/v1/modules/{module}/proxy/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
        dependencies=[Depends(operator)],
    )
    async def proxy(module: str, path: str, request: Request):
        if module not in {"pm", "qa", "document", "infra"}:
            raise HTTPException(404, "Module not supported")
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        connection = await connected(request)
        if not connection:
            raise HTTPException(401, "Connect your shared identity first")
        origin = getattr(config, f"{module}_origin")
        if not origin:
            raise HTTPException(503, "Module service is not configured")
        return await forward_module(
            request,
            GatewayTarget(origin, config.module_sockets.get(module)),
            path,
            connection["token"],
            transport,
        )

    @app.post("/api/v1/modules/{module}/projects/{slug}/import", dependencies=[Depends(operator)])
    async def import_project(module: str, slug: str, request: Request):
        # Verify visibility using the module's real project endpoint on every import.
        remote = await projects(module, request)
        selected = next((item for item in remote if item["external_id"] == slug), None)
        if selected is None:
            raise HTTPException(404, "Module project not found")
        if store is None or event is None:
            raise HTTPException(503, "Project registry unavailable")
        with store.tx() as db:
            existing = db.execute(
                "SELECT project_id FROM ecosystem_project_links WHERE system=? AND external_id=?",
                (module, slug),
            ).fetchone()
            if existing:
                return {"project_id": existing[0], "created": False, "remote_modified": False}
            project_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO ecosystem_projects VALUES(?,?,?)",
                (project_id, selected["name"], time.time()),
            )
            db.execute(
                "INSERT INTO ecosystem_project_links VALUES(?,?,?)", (project_id, module, slug)
            )
            event(
                db,
                "project.imported",
                "operator",
                payload={"project_id": project_id, "system": module},
            )
        return {"project_id": project_id, "created": True, "remote_modified": False}
