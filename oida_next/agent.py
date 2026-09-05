"""Small Linux agent: signed outbound polling, fixed recipes, durable execution journal."""

import argparse
import hashlib
import json
import os
import platform
import re
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .protocol import action_plan, canonical, digest
from .security import load_key, public_key, redact, signed_headers

RECIPES = {
    "system_info": "import json,platform,os; print(json.dumps({'os':platform.system(),'architecture':platform.machine(),'python':platform.python_version(),'cpu_count':os.cpu_count()}))",
    "workspace_demo": "import pathlib,hashlib,json; p=pathlib.Path('artifact.txt'); p.write_text('OIDA Next: goal to agent to verified evidence.\\n'); print(json.dumps({'artifact':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'content':p.read_text()}))",
    "package_check": "import venv,subprocess,json; venv.create('sandbox',with_pip=True); p=subprocess.run(['sandbox/bin/python','-I','-m','pip','--version'],capture_output=True,text=True,check=True); print(json.dumps({'scope':'disposable virtualenv','package':'pip','check':p.stdout.strip(),'host_packages_modified':False}))",
}


def capabilities() -> dict:
    usage = shutil.disk_usage(Path.cwd())
    return {
        "os": platform.system(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "version": "0.1.0",
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "disk_free_bytes": usage.free,
        "git": bool(shutil.which("git")),
        "docker": bool(shutil.which("docker")),
        "node": bool(shutil.which("node")),
        "codex": bool(shutil.which("codex")),
        "policy": "fixed-recipes-only; no-root; isolated-workspaces",
    }


class Agent:
    def __init__(self, url: str, root: Path, passphrase: str, allow_loopback: bool = False):
        parsed = urlparse(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Control URL cannot contain credentials, query, or fragment")
        if parsed.scheme != "https" and not (
            allow_loopback
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("TLS required; explicit loopback-only development exception available")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ValueError("Agent must not run as root")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve()
        self.key = load_key(self.root / "identity.enc", passphrase)
        self.agent_id = hashlib.sha256(public_key(self.key).encode()).hexdigest()[:32]
        self.client = httpx.Client(
            base_url=url.rstrip("/"), timeout=8, follow_redirects=False, trust_env=False
        )
        self.journal = sqlite3.connect(self.root / "journal.db")
        self.journal.execute(
            "CREATE TABLE IF NOT EXISTS executions(job TEXT PRIMARY KEY, action_hash TEXT, state TEXT, result TEXT)"
        )
        self.journal.commit()
        os.chmod(self.root / "journal.db", 0o600)

    def close(self):
        self.client.close()
        self.journal.close()

    def call(self, method: str, path: str, value=None):
        body = canonical(value) if value is not None else b""
        response = self.client.request(
            method,
            path,
            content=body,
            headers=signed_headers(self.key, self.agent_id, method, path, body),
        )
        response.raise_for_status()
        return response.json()

    def register(self, token: str):
        response = self.client.post(
            "/api/v1/agents/register",
            json={
                "name": platform.node(),
                "public_key": public_key(self.key),
                "capabilities": capabilities(),
            },
            headers={"Authorization": "Bearer " + token},
        )
        response.raise_for_status()
        if response.json()["agent_id"] != self.agent_id:
            raise ValueError("Unexpected registration identity")

    def tick(self):
        self.call("POST", "/api/v1/agents/heartbeat", {"capabilities": capabilities()})
        job = self.call("POST", "/api/v1/agents/claim")
        if job:
            result = self.execute(job)
            self.call("POST", f"/api/v1/agents/jobs/{job['id']}/result", result)
        return job

    def execute(self, job: dict) -> dict:
        job_id, plan = job["id"], job["action"]
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid workspace/job identifier")
        recipe = plan.get("recipe")
        if recipe not in RECIPES or plan.get("target") != self.agent_id:
            raise ValueError("Unsupported recipe or wrong target")
        if (
            plan != action_plan(recipe, self.agent_id, plan["timeout"])
            or not 1 <= plan["timeout"] <= 120
        ):
            raise ValueError("Local policy rejected modified plan")
        if job["action_hash"] != digest(plan) or job["state"] not in {"DISPATCHED", "RUNNING"}:
            raise ValueError("Unapproved or tampered job")
        old = self.journal.execute(
            "SELECT action_hash,state,result FROM executions WHERE job=?", (job_id,)
        ).fetchone()
        if old:
            if old[0] != job["action_hash"]:
                raise ValueError("Replay changed an existing action")
            if old[2]:
                return json.loads(old[2])
            # A crash can leave execution uncertain. Never repeat the side effect.
            return self.record_result(
                job, "FAILED", "Interrupted execution; not automatically repeated.", -1
            )
        workspace = self.root / job_id
        if shutil.disk_usage(self.root).free < 10_000_000_000:
            raise ValueError("STORAGE_CAPACITY_BLOCKER: keep 10 GB free before execution")
        if workspace.exists() or workspace.is_symlink():
            raise ValueError("Workspace already exists without matching execution journal")
        self.journal.execute(
            "INSERT INTO executions VALUES(?,?,?,NULL)", (job_id, job["action_hash"], "STARTED")
        )
        self.journal.commit()
        workspace.mkdir(mode=0o700)
        output, sequence = "", 0
        process = subprocess.Popen(
            [sys.executable, "-I", "-u", "-c", RECIPES[recipe]],
            cwd=workspace,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(workspace)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        started, last_check = time.monotonic(), 0.0
        state = "SUCCEEDED"
        try:
            while True:
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(process.stdout.fileno(), 4096).decode(errors="replace")
                    if chunk:
                        chunk = redact(chunk)
                        output = (output + chunk)[-16000:]
                        try:
                            self.call(
                                "POST",
                                f"/api/v1/agents/jobs/{job_id}/progress",
                                {"lease": job["lease"], "sequence": sequence, "output": chunk},
                            )
                        except httpx.HTTPError:
                            pass  # Final durable result carries output even when streaming is disconnected.
                        sequence += 1
                    else:
                        selector.unregister(process.stdout)
                now = time.monotonic()
                if now - started > plan["timeout"]:
                    state = "TIMED_OUT"
                    break
                if now - last_check > 1:
                    last_check = now
                    try:
                        current = self.call("GET", f"/api/v1/agents/jobs/{job_id}")
                        if current["cancel_requested"]:
                            state = "CANCELLED"
                            break
                    except httpx.HTTPError:
                        pass
                if process.poll() is not None and not selector.get_map():
                    if process.returncode != 0:
                        state = "FAILED"
                    break
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            process.stdout.close()
        return self.record_result(job, state, output, process.returncode)

    def record_result(self, job: dict, state: str, output: str, code: int) -> dict:
        evidence = json.dumps(
            {
                "job": job["id"],
                "recipe": job["action"]["recipe"],
                "output": redact(output),
                "scope": "isolated-workspace",
                "exit_code": code,
            },
            sort_keys=True,
        )
        result = {
            "lease": job["lease"],
            "state": state,
            "output": redact(output),
            "evidence": evidence,
            "checksum": hashlib.sha256(evidence.encode()).hexdigest(),
            "exit_code": code,
        }
        self.journal.execute(
            "UPDATE executions SET state=?,result=? WHERE job=?",
            (state, json.dumps(result), job["id"]),
        )
        self.journal.commit()
        return result


def main():
    import getpass

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--data", type=Path, default=Path("data/agent"))
    parser.add_argument("--allow-loopback-http", action="store_true")
    parser.add_argument("--enroll", action="store_true")
    args = parser.parse_args()
    phrase = os.environ.pop("OIDA_AGENT_PASSPHRASE", "") or getpass.getpass(
        "Unlock encrypted agent identity: "
    )
    agent = Agent(args.url, args.data, phrase, args.allow_loopback_http)
    if args.enroll:
        enrollment = os.environ.pop("OIDA_ENROLLMENT_TOKEN", "") or getpass.getpass(
            "One-time enrollment token: "
        )
        agent.register(enrollment)
    try:
        while True:
            try:
                agent.tick()
            except httpx.HTTPError:
                print(
                    "Control plane unavailable; keeping durable state and reconnecting.", flush=True
                )
            time.sleep(2)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
