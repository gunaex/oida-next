# Operator and deployment guide

## Daily use

Open the operator UI, unlock, select an online agent, state a supported goal or choose a workflow. Review MEDIUM-risk package-check plans, then approve. Observe jobs/events and open Plan & evidence. Cancel requests stop a running fixed recipe's process group when the agent is connected. Offline work is durable; do not submit a duplicate to “fix” an unknown state.

`uv run oida-control --data data/control.db --port 8765 --local-agent` starts local operation without copying commands to an agent for each job. Separate `oida-agent` supports remote machines over HTTPS. API credentials are never placed in source files or command arguments.

## Reproducible checks

`uv sync --locked`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy oida_next scripts`; `uv run pytest -q`; `uv run python scripts/dogfood.py`.

`docs/dogfood-result.json` is real evidence from separate processes. The temporary demo is isolated from production databases. A physical phone and remote TLS path must still be exercised before claiming WAN/mobile acceptance.

## Host service

The installed home-server service uses a user-level systemd unit, loopback listener, restart-on-failure, explicit memory/CPU/task limits, read-only system paths and only its own writable data path. It does not modify Docker, protected workloads, firewall or partitions. Stop only this service with `systemctl --user stop oida-next.service`.

After restart, log in to unlock the managed local agent. A forgotten password cannot be recovered from the stored hash. Keep encrypted identity and database backups together with a separately managed password-manager entry.

## Backup / restore

Use SQLite's online backup API for the control DB and agent journal; do not copy live main database files without WAL. Encrypted identity files can be copied as ciphertext. No plaintext private key or passphrase belongs in a backup. Before restore, stop only OIDA Next, preserve the current DB and its WAL/SHM plus encrypted identities, verify integrity of a restored copy in an isolated directory, and restart. No automatic production restore is performed by the demo.

## Troubleshooting

- Agent offline: verify HTTPS reachability/time sync and unlock after restart; preserve identity and journal.
- Job pending: confirm agent online and approval; never erase journal to force retry.
- Evidence rejected: inspect checksum/lease mismatch, not secret values.
- Storage blocker: add capacity or approve cleanup separately; the agent preserves a 10 GB floor.
- No goal match: select one of the three workflows. General autonomous administration is deliberately not implemented.
- Owner setup forbidden: use the local machine's `http://127.0.0.1:8765`, not a proxy/Tunnel or another hostname.

Future Mac/Windows agents need platform-specific process cancellation, capability probes and policy tests. Mobile is currently an operator browser concept, not a native agent. Multi-provider orchestration needs real adapters and explicit keys/cost budgets. ChatGPT-to-OIDA integration is not installed or implied.
