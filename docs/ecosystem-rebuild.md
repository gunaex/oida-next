# Unified home-server ecosystem — revised direction

Superseding user decision: preserve PM, QA, Document and Infra capabilities and
integrate them through OIDA Next, without Fly.io. A unified experience does not
require rewriting modules or merging their databases. Existing applications and
data remain intact. New integration code is not deployed.

## Proposed foundation

- One responsive Cloudflare Pages frontend, in the owner's account.
- OIDA coordination backend and independently owned module APIs on Ubuntu behind
  the existing outbound Cloudflare Tunnel; consolidate runtimes only after audit.
- One owner identity/session and permission policy shared by all five modules.
- Shared project/work identifiers, audit events, job queue and artifact metadata.
- OIDA plans and coordinates; PM owns tasks; QA owns checks and results;
  Document owns versioned documents; Infra owns inventory and diagnostics.
- The existing constrained agent remains the execution boundary. Destructive
  or privileged actions require explicit approval; no unrestricted shell.
- Keep OIDA's existing SQLite store for coordination only. Keep
  module boundaries and migration scripts explicit. Do not introduce PostgreSQL
  or additional services without a demonstrated requirement.
- Shared file storage and backups belong under a verified persistent /data
  mount when available. No assumption that /data is ready; no partition changes.
- Legacy application databases are not directly shared or overwritten.

## Implementation order and acceptance

1. Inventory actual production resource usage, existing schemas and data ownership.
2. Define shared schema, transactional migrations, authentication and permissions.
3. Implement project → task → agent execution → QA result → document evidence.
4. Add Infra read-only health/storage reporting and approval-gated maintenance.
5. Test authorization, retry safety, restore, resource limits and end-to-end flow.
6. Stage deployment alongside legacy apps; confirm owner login and workflows.
7. Migrate selected legacy data with backups and reconcile counts/relationships.
8. Retire legacy services only with explicit approval; never delete Fly resources
   or alter Hermes, Open WebUI, Ollama or Jellyfin as a side effect.

No claim of completion: unified modules, automatic migration and remote sync
are not yet implemented. No paid services, new DNS changes, partition writes,
or production database mutation are part of this design document.
