# OIDA Next

A working personal orchestration foundation: **goal → durable job → outbound Linux agent → evidence**. Separate greenfield code; legacy OIDA and its data are not replaced.

## Start

Requires Linux, Python 3.12+, `uv`, and at least 10 GB free. No paid API key or cloud compute is needed.

```sh
uv sync --locked
uv run oida-control --data data/control.db --port 8765 --local-agent
```

Open `http://127.0.0.1:8765` **on this machine**. Choose an operator password (16+ characters), then unlock. The optional local agent is paired and started automatically. The password is stored only as a salted scrypt hash. Its derived unlock value encrypts the local agent identity; neither the password nor unlock value is written to disk. Store the password in your password manager. After a reboot or control-plane restart, log in once to unlock this agent again.

Submit “collect system information”, “create a test artifact”, or “check package in sandbox”. The package workflow waits for approval. Review its plan and approve that exact action. All three recipes are real, fixed Python executions, not mock successes. The package workflow creates a disposable virtual environment and verifies its bundled pip; it does not install or change host packages.

## Tests and real-process demo

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy oida_next scripts
uv run pytest -q
uv run python scripts/dogfood.py
```

The demo starts separate control-plane and agent OS processes, performs all three workflows, checks approval gating and evidence checksums, restarts the control plane and agent, then stops only its own processes. Credentials exist only in memory; temporary identities are encrypted. `docs/dogfood-result.json` records actual results. This is a local network demonstration, not a claim that a physical phone or remote WAN device was tested.

## Remote agent

Expose the authenticated control plane through an HTTPS reverse proxy/Tunnel. Do not expose its initial setup endpoint: setup additionally requires a loopback peer, loopback hostname and same-origin request. Obtain a single-use, five-minute pairing token from `POST /api/v1/enrollment` with an operator session. On the remote Linux machine:

```sh
uv run oida-agent --url https://YOUR-CONTROL-HOST --data data/agent --enroll
```

Enter the encrypted identity passphrase and pairing token at hidden prompts. Subsequent starts omit `--enroll`. No inbound agent port is opened. HTTP is rejected except explicit loopback-only development. The initial pairing is a one-time identity setup, not a command-transport loop. A UI pairing wizard is not yet implemented.

## Boundaries

This is **not** an unrestricted remote shell or an autonomous coding product. It supports three fixed recipes; arbitrary commands, package installation on the host, production changes, paid providers, general DAGs, Windows/Mac/mobile agents and ChatGPT integration are not implemented. Unknown goals are rejected. Do not grant root, mount Docker sockets, or extend recipes to accept arbitrary shell strings.

See `docs/architecture.md`, `docs/security.md`, `docs/operations.md`, and `docs/legacy-inventory.md` for contracts, deployment and limitations.
