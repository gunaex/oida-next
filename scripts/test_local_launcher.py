"""Verify owner login starts the managed encrypted Linux agent in real processes."""

import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from oida_next.control import Store


def main():
    with tempfile.TemporaryDirectory(prefix="oida-next-launcher-") as directory:
        root = Path(directory)
        password = secrets.token_urlsafe(32)
        Store(root / "control.db").initialize_password(password)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "oida_next.control",
                "--data",
                str(root / "control.db"),
                "--port",
                str(port),
                "--local-agent",
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
                for _ in range(100):
                    try:
                        if client.get("/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.05)
                response = client.post("/api/v1/login", json={"password": password})
                response.raise_for_status()
                client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
                for _ in range(100):
                    agents = client.get("/api/v1/agents").json()
                    if agents:
                        break
                    time.sleep(0.1)
                assert len(agents) == 1 and agents[0]["online"]
                assert b"ENCRYPTED PRIVATE KEY" in (root / "local-agent/identity.enc").read_bytes()
                job = client.post(
                    "/api/v1/goals",
                    json={
                        "goal": "Collect system information",
                        "target": agents[0]["id"],
                        "idempotency_key": secrets.token_hex(16),
                    },
                ).json()
                for _ in range(100):
                    state = client.get(f"/api/v1/jobs/{job['id']}").json()["state"]
                    if state == "SUCCEEDED":
                        break
                    time.sleep(0.1)
                assert state == "SUCCEEDED"
                print(
                    "MANAGED_LOCAL_AGENT=PASS; owner login -> encrypted identity -> automatic enrollment -> job execution"
                )
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
