# Security model and limitations

## Implemented

- Operator password: random salt + scrypt hash; one-hour random session tokens stored hashed. Login throttling (10 failures/minute per direct peer). No cookies, so state mutations require explicit Bearer authorization rather than ambient browser credentials.
- Initial setup is loopback-only, same-origin, one-time and cannot overwrite an existing owner.
- Agent: unique Ed25519 identity, PKCS8 encryption at rest with user passphrase, public key only at control plane. Five-minute single-use enrollment tokens stored hashed.
- Signed timestamp/nonce/body requests prevent replay and tampering. Jobs and result leases are identity-scoped.
- Exact-plan approvals; forbidden arbitrary arguments; fixed Python `-I` recipes, no shell=True, no root.
- Workspace ID validation, no reuse of unexpected directories/symlinks, 10 GB disk floor, child process-group cancellation/timeouts, limited outputs.
- Plaintext secrets are not persisted by OIDA Next. Passwords and unlock values necessarily exist in process memory while authenticating/running. An optional local-agent launcher passes its unlock value through an ephemeral child environment; it is not stored in Compose, systemd files, databases or logs. Other processes running as the same Unix user are within the trust boundary.
- UI uses textContent rather than HTML injection; no credential browser storage; CSP and anti-framing headers.
- Agent result validation includes checksum and exit status, not independent attestation of a hostile agent's execution. Only enroll machines you trust.

## Honest limitations

This is a personal foundation, not a sandbox for hostile code or an enterprise security product. Fixed recipes are the security boundary. A working directory and unprivileged account alone do not sandbox arbitrary Python. No arbitrary command upload is accepted. Run a separate OS user/container before adding untrusted executors.

The agent rejects remote HTTP and verifies HTTPS certificates. Local demo intentionally uses loopback HTTP. TLS is terminated by a separately managed reverse proxy/Tunnel in a remote deployment; mTLS is not implemented. No production OIDA Next public hostname is assumed by this repository.

There is no password-reset workflow yet: keep the owner password securely. Losing it also prevents unlocking the managed local agent key. Do not delete the database as a reset workaround. Implement a backup-preserving recovery procedure before changing credentials. Boot starts the control plane but requires one owner login to unlock the agent; unattended encrypted-keystore startup needs a future TPM/OS-keyring integration.

Application audit tables are not tamper-proof against the OS/database owner. Per-peer login throttling resets on control restart. Full revocation UI, per-job secret injection, remote agent auto-update, artifact signing/large uploads, log streaming across a prolonged network outage and process-tree crash containment for future complex executors are not implemented. Final bounded output survives temporary network failure through the agent journal. A permanently disconnected execution stays pending and is not silently declared successful.

Never add a root shell, exposed Docker socket, blanket filesystem permissions, or a provider-generated command without a new explicit execution security design.
