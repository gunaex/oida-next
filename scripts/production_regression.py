"""Run the authenticated, read-only OIDA production acceptance loop."""

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any

import httpx


def require(response: httpx.Response) -> Any:
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://oida-next.kanphong.com/api/v1")
    parser.add_argument("--project-title", default="DeepSeek Full Loop Acceptance")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    token = os.environ.get("OIDA_SESSION_TOKEN")
    with httpx.Client(base_url=args.base_url, timeout=45, trust_env=False) as client:
        if not token:
            password = getpass.getpass("OIDA password: ")
            token = require(client.post("/login", json={"password": password}))["access_token"]
        client.headers["Authorization"] = "Bearer " + token

        settings = require(client.get("/ai/settings"))
        provider = require(client.post("/ai/settings/test"))
        drafts = require(client.get("/ai/drafts"))
        draft = next(
            (item for item in drafts if item["title"] == args.project_title),
            None,
        )
        if not draft or draft["status"] != "APPROVED":
            raise SystemExit("Approved acceptance project was not found")
        verification = require(client.post(f"/ai/drafts/{draft['id']}/verify"))
        agents = require(client.get("/agents"))

    report = {
        "healthy": bool(provider["healthy"] and verification["healthy"]),
        "provider": {
            "name": settings["provider"],
            "model": settings["model"],
            "key_saved": settings["has_api_key"],
            "connection": provider["healthy"],
        },
        "project": args.project_title,
        "status": draft["status"],
        "modules": verification["modules"],
        "online_agents": [item["name"] for item in agents if item.get("online")],
    }
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        args.output.chmod(0o600)
    print(output, end="")
    if not report["healthy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
