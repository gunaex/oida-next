"""Session-bound Account Again connection; secrets stay out of browser/storage.

This is a transitional linking flow, not a replacement for OIDA owner login.
Module authorization remains module-owned. Connections deliberately expire and
are lost on restart rather than retaining account passwords or refresh tokens.
"""

import os
import time
import uuid
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import Field, SecretStr

from .module_client import ModuleConfig, ModuleUnavailable, ProjectReader
from .protocol import StrictModel


@dataclass(frozen=True)
class IdentityConfig:
    origin: str
    pm_origin: str
    qa_origin: str

    def __post_init__(self):
        ModuleConfig("pm", self.origin)
        ModuleConfig("pm", self.pm_origin)
        ModuleConfig("qa", self.qa_origin)


def configured_identity() -> IdentityConfig | None:
    values = [
        os.environ.get(name, "")
        for name in ("OIDA_ACCOUNT_ORIGIN", "OIDA_PM_ORIGIN", "OIDA_QA_ORIGIN")
    ]
    if not any(values):
        return None
    if not all(values):
        raise ValueError("All three identity/module origins must be configured together")
    return IdentityConfig(*values)


class IdentityLogin(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=256)


def install_identity(
    app, operator, config: IdentityConfig | None, transport=None, store=None, event=None
):
    connections: dict[str, dict] = {}
    attempts: dict[str, list[float]] = {}

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
    def status(request: Request):
        prune()
        connection = connections.get(session_key(request))
        return {
            "configured": config is not None,
            "connected": bool(connection),
            "email": connection["email"] if connection else None,
            "expires": connection["expires"] if connection else None,
        }

    @app.delete("/api/v1/identity", dependencies=[Depends(operator)])
    def disconnect(request: Request):
        connections.pop(session_key(request), None)
        return {"disconnected": True}

    @app.post("/api/v1/identity", dependencies=[Depends(operator)])
    async def connect(body: IdentityLogin, request: Request):
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        prune()
        # Global owner-level limit: issuing a fresh OIDA session cannot bypass it.
        history = attempts.setdefault("operator", [])
        if len(history) >= 5:
            raise HTTPException(429, "Please wait before retrying identity login")
        history.append(time.time())
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport, timeout=10, follow_redirects=False, trust_env=False
                ) as client,
                client.stream(
                    "POST",
                    config.origin.rstrip("/") + "/api/v1/auth/ecosystem-token",
                    json={"email": body.email, "password": body.password.get_secret_value()},
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
                or result.get("email") != body.email
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
            "email": body.email,
        }
        return {"connected": True, "email": body.email, "expires_in": ttl}

    @app.get("/api/v1/modules/{module}/projects", dependencies=[Depends(operator)])
    async def projects(module: str, request: Request):
        if module not in {"pm", "qa"}:
            raise HTTPException(404, "Module not supported")
        if not config:
            raise HTTPException(503, "Shared identity is not configured")
        prune()
        connection = connections.get(session_key(request))
        if not connection:
            raise HTTPException(401, "Connect your shared identity first")
        origin = config.pm_origin if module == "pm" else config.qa_origin
        try:
            return await ProjectReader(ModuleConfig(module, origin), transport).list_projects(
                connection["token"]
            )
        except ModuleUnavailable:
            raise HTTPException(502, "Module unavailable or identity denied") from None

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
