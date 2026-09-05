"""Real two-process Linux round trip. No credentials leave process memory."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from oida_next.agent import Agent
from oida_next.control import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("docs/dogfood-result.json"))
    args = parser.parse_args()
    report: dict = {
        "product": "OIDA_NEXT",
        "transport": "loopback HTTP, separate OS processes",
        "remote_tls_phone_test": "NOT_RUN",
        "jobs": [],
    }
    with tempfile.TemporaryDirectory(prefix="oida-next-dogfood-") as temp:
        root = Path(temp)
        password, phrase = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        Store(root / "control.db").initialize_password(password)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        processes = []

        def control():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "oida_next.control",
                    "--data",
                    str(root / "control.db"),
                    "--port",
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            for _ in range(100):
                try:
                    if httpx.get(url + "/ready", timeout=0.3).status_code == 200:
                        return process
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError("Control process exited")
                time.sleep(0.05)
            raise RuntimeError("Control readiness timeout")

        def runner():
            env = dict(os.environ, OIDA_AGENT_PASSPHRASE=phrase)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "oida_next.agent",
                    "--url",
                    url,
                    "--data",
                    str(root / "agent"),
                    "--allow-loopback-http",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            return process

        try:
            cp = control()
            client = httpx.Client(base_url=url, timeout=5)
            token = client.post("/api/v1/login", json={"password": password}).json()["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            pairing = client.post("/api/v1/enrollment").json()["token"]
            enrollment_agent = Agent(url, root / "agent", phrase, True)
            enrollment_agent.register(pairing)
            agent_id = enrollment_agent.agent_id
            enrollment_agent.close()
            process = runner()
            for recipe in ("system_info", "workspace_demo", "package_check"):
                response = client.post(
                    "/api/v1/goals",
                    json={
                        "goal": f"Dogfood {recipe}",
                        "recipe": recipe,
                        "target": agent_id,
                        "timeout": 60,
                        "idempotency_key": secrets.token_hex(12),
                    },
                )
                response.raise_for_status()
                job = response.json()
                if recipe == "package_check":
                    time.sleep(2.5)
                    assert (
                        client.get(f"/api/v1/jobs/{job['id']}").json()["state"]
                        == "WAITING_APPROVAL"
                    )
                    assert not (root / "agent" / job["id"]).exists()
                    approved = client.post(
                        f"/api/v1/jobs/{job['id']}/approval",
                        json={"action_hash": job["action_hash"], "approve": True},
                    )
                    approved.raise_for_status()
                    report["approval_gate"] = "PASS"
                if recipe == "workspace_demo":
                    cp.terminate()
                    cp.wait(timeout=5)
                    cp = control()
                    report["control_restart"] = "PASS"
                deadline = time.monotonic() + 75
                while time.monotonic() < deadline:
                    final = client.get(f"/api/v1/jobs/{job['id']}").json()
                    if final["state"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}:
                        break
                    time.sleep(0.3)
                assert final["state"] == "SUCCEEDED", final["state"]
                evidence = client.get(f"/api/v1/jobs/{job['id']}/evidence").json()
                assert (
                    hashlib.sha256(evidence["content"].encode()).hexdigest() == evidence["sha256"]
                )
                report["jobs"].append(
                    {
                        "recipe": recipe,
                        "state": final["state"],
                        "evidence": json.loads(evidence["content"]),
                        "sha256": evidence["sha256"],
                    }
                )
            process.terminate()
            process.wait(timeout=5)
            process = runner()
            time.sleep(2.5)
            assert all(j["state"] == "SUCCEEDED" for j in client.get("/api/v1/jobs").json())
            report["agent_restart"] = "PASS"
            report["event_count"] = len(client.get("/api/v1/events").json())
            report["status"] = "PASS"
            client.close()
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"DOGFOOD=PASS; 3 real workflows; approval, reconnect and evidence verified. Report: {args.report}"
    )


if __name__ == "__main__":
    main()
