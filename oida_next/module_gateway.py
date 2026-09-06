"""Authenticated PM/QA gateway with fixed upstreams and bounded payloads."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request, Response

from .module_client import ModuleConfig

MAX_UPLOAD = 8 * 1024 * 1024
MAX_DOWNLOAD = 32 * 1024 * 1024


@dataclass(frozen=True)
class GatewayTarget:
    origin: str
    socket: str | None = None

    def __post_init__(self):
        ModuleConfig("pm", self.origin)
        if self.socket:
            path = PurePosixPath(self.socket)
            if not path.is_absolute() or ".." in path.parts or str(path) == "/":
                raise ValueError("Module socket must be an explicit absolute file path")


async def forward_module(
    request: Request, config: ModuleConfig | GatewayTarget, path: str, identity_token: str, transport=None
):
    if (
        not path
        or len(path) > 2000
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(ord(c) < 32 for c in path)
        or any(c in path for c in "\\%?#")
    ):
        raise HTTPException(400, "Invalid module path")
    if path.startswith("auth/") and path.split("/")[1] not in {"me", "users", "change-password"}:
        raise HTTPException(403, "Manage the shared session from OIDA")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPLOAD:
            raise HTTPException(413, "Module upload exceeds the 8 MiB gateway limit")
    headers = {"Authorization": "Bearer " + identity_token}
    for name in ("accept", "content-type", "range", "if-none-match"):
        if value := request.headers.get(name):
            headers[name] = value
    socket = config.socket if isinstance(config, GatewayTarget) else None
    origin = "http://localhost" if socket else config.origin.rstrip("/")
    url = origin + "/api/" + quote(path, safe="/-_.~")
    if request.url.query:
        url += "?" + request.url.query
    try:
        async with (
            httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=socket) if socket else transport,
                timeout=30, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(request.method, url, headers=headers, content=bytes(body)) as upstream,
        ):
            if 300 <= upstream.status_code < 400 and upstream.status_code != 304:
                raise HTTPException(502, "Unexpected module redirect")
            if upstream.status_code >= 500:
                raise HTTPException(502, "Module service unavailable")
            result = bytearray()
            async for chunk in upstream.aiter_bytes(chunk_size=65536):
                result.extend(chunk)
                if len(result) > MAX_DOWNLOAD:
                    raise HTTPException(502, "Module download exceeds the 32 MiB gateway limit")
            output = {
                name: upstream.headers[name]
                for name in (
                    "content-type",
                    "content-disposition",
                    "etag",
                    "content-range",
                    "accept-ranges",
                )
                if name in upstream.headers
            }
            output.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
            # Module cookies, redirects and identity headers never reach the browser.
            return Response(bytes(result), status_code=upstream.status_code, headers=output)
    except httpx.HTTPError:
        raise HTTPException(502, "Module request failed") from None
