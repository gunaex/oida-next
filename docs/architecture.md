# Architecture, contracts and developer guide

## Modules

- `control.py`: FastAPI HTTP API; operator auth, enrollment, registry, approvals, scheduler, durable events and evidence.
- `protocol.py`: Pydantic v1 contracts with unknown fields rejected; canonical JSON action hashes.
- `models.py`: provider-neutral Planner protocol and functional deterministic/no-key adapter. Unknown intents fail closed. Model registry describes capabilities/cost/privacy.
- `agent.py`: outbound signed polling, capability report, fixed-recipe executor, timeout/cancellation, execution journal and result outbox.
- `security.py`: scrypt operator hashing, encrypted Ed25519 identity, signatures, replay checks and output redaction.
- `web/`: responsive operator workspace. Session token is memory-only; no localStorage credentials. Agent cards, goal composer, plans, approval, jobs, events and evidence.

One control-plane process owns a SQLite database with WAL and immediate transactions. Each agent owns its own SQLite execution journal and isolated workspaces. No shared database, Redis, broker, PostgreSQL or Kubernetes. Fixed recipes run unprivileged without shell interpolation, in a child process group with a restricted environment. There is no Docker socket or arbitrary tool execution.

## API v1

OpenAPI schemas: `/openapi.json`, interactive documentation: `/docs`.

| Authority | Endpoints |
|---|---|
| Public | `GET /health`, `/ready`, `/api/v1/setup-status`, `POST /api/v1/login` |
| Loopback initial owner only | `POST /api/v1/setup` |
| Operator Bearer session | `/api/v1/agents`, `/models`, `/goals`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/approval`, `/jobs/{id}/cancel`, `/jobs/{id}/evidence`, `/events?after=N`, `/enrollment`, `/logout` |
| One-use enrollment token | `POST /api/v1/agents/register` |
| Agent signed request | `POST /api/v1/agents/heartbeat`, `/claim`, `/jobs/{id}/progress`, `/jobs/{id}/result`; `GET /api/v1/agents/jobs/{id}` |

Signatures cover method, path, Unix timestamp, random nonce and SHA256 of exact body bytes. The server allows 60 seconds clock skew, atomically rejects nonce reuse, and scopes jobs/results to agent identity plus execution lease. Registration binds a public key to a stable fingerprint identity. Query parameters currently carry no agent-authorized actions.

## Lifecycle

Goal is planned atomically into `QUEUED` or `WAITING_APPROVAL`; approval compares immutable action hash. Claim → `DISPATCHED`; progress → `RUNNING`; validated result → `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `CANCELLED`. Rejection/queued cancellation is terminal without execution. A dispatched cancellation is cooperative and becomes terminal when agent acknowledges. Offline agents retain pending work; the UI reports offline and durable lease metadata remains available. There is no automatic reassignment of uncertain side effects.

The agent commits STARTED **before** launching the child. Duplicate deliveries return journaled result without reexecution. After a crash with uncertain STARTED work it reports FAILED rather than repeating it. Lost result replies are retried on subsequent claim using the same job/lease/result. The same signed HTTP request is never replayed; retries use a new nonce. Progress sequence keys deduplicate events. Evidence checksum is checked before persistence and recomputed if sanitization changes its content.

## Scope and extension points

The first slice is one job per goal, FIFO per agent, one operator, no-key planning and three allowlisted recipes. Parent/child task graphs, provider selection algorithms, automatic repairs, general admin installation, multi-tenant auth, secret-vault references and arbitrary artifacts are reserved interfaces—not implemented features. Add adapters behind Planner; keep policy authoritative rather than trusting generated text. Add a recipe only with a documented risk, explicit policy and negative tests. Durable state transitions must remain transactional and idempotent.

Events are stored with timestamp, integer event ID, actor, agent, job/correlation, type, severity and payload. Polling retrieves pages by cursor; SSE/WebSocket/brokers may replace transport later without changing job semantics.
