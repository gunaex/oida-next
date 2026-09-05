"""Bounded read-only adapter for existing PM/QA project APIs.

Credentials are explicitly supplied by a server-side identity provider, never
copied from OIDA request headers. No automatic login or authority escalation.
"""

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class ModuleUnavailable(Exception):
    """Sanitized failure safe to report to operators."""


@dataclass(frozen=True)
class ModuleConfig:
    name: str
    origin: str

    def __post_init__(self):
        if self.name not in {"pm", "qa"}:
            raise ValueError("Unsupported module")
        url = urlsplit(self.origin)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("An explicit HTTPS origin without credentials is required")


class ProjectReader:
    def __init__(self, config: ModuleConfig, transport=None):
        self.config = config
        self.transport = transport

    async def list_projects(self, module_access_token: str) -> list[dict]:
        if not module_access_token or any(c.isspace() for c in module_access_token):
            raise ModuleUnavailable("Module identity is not configured")
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=10,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "GET",
                    self.config.origin.rstrip("/") + "/api/projects",
                    headers={
                        "Authorization": "Bearer " + module_access_token,
                        "Accept": "application/json",
                    },
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise ModuleUnavailable("Module identity denied")
                if response.status_code != 200:
                    raise ModuleUnavailable("Module project API unavailable")
                chunks = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    chunks.extend(chunk)
                    if len(chunks) > 1_000_000:
                        raise ModuleUnavailable("Module response exceeds safe limit")
            data = json.loads(chunks)
            if not isinstance(data, list) or len(data) > 2000:
                raise ModuleUnavailable("Unexpected module project contract")
            projects = []
            for item in data:
                if not isinstance(item, dict):
                    raise ModuleUnavailable("Unexpected module project contract")
                slug, name = item.get("slug"), item.get("name")
                if (
                    not isinstance(slug, str)
                    or not slug
                    or len(slug) > 200
                    or not isinstance(name, str)
                    or not name
                    or len(name) > 500
                ):
                    raise ModuleUnavailable("Unexpected module project contract")
                # Only public project display fields cross the module boundary.
                projects.append({"system": self.config.name, "external_id": slug, "name": name})
            return projects
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ModuleUnavailable("Module request failed") from None
