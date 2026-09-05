# Integration checkpoint — 2026-09-05

## Confirmed QA target (supersedes earlier selection)

The user accepted the live qaagain.kanphong.com application as the source to
preserve. Its deployment is the PM-QA-Again build, not the standalone QA-Again
foundation. Cloudflare reported production deployment 23e4c921, commit ed39d2b,
branch feature/hybrid-mvp with commit_dirty=true. Preserve the build/source as
well as Git metadata before migration; the commit alone is not exact provenance.
Do not substitute the standalone QA-Again repository or rebuild its missing
domain features as part of this integration.

## Shared project registry implemented in staging

Operator-authenticated project APIs now maintain explicit per-module external
IDs and work membership. External identifiers remain owned by their modules;
mapping neither creates nor verifies a remote project. Duplicate identical
requests are safe. Conflicting external mappings and silent work reassignment
return 409. Audit events are emitted only for new attachments. Existing local
work records require no destructive schema conversion.

Validation: 21 tests pass, Ruff passes, mypy passes (7 source files). No public
frontend or backend deployment occurred. Shared login and remote adapters remain
unfinished; reference mapping must not be presented as completed integration.

Auth inspection: PM and deployed QA accept their own user JWTs or cookies and
resolve users from their own databases. Document supports Account Again issuer,
audience and JWKS validation. PM ecosystem intake separately requires a verified
CONDUCTOR_MAIN service identity. Do not copy signing secrets across services or
impersonate Conductor to connect OIDA. A reviewed explicit identity bridge is
required before enabling remote mutation.

## Verified source observations, not production capability claims

- PM-Again: previously compared upstream README, requirements, auth router and
  ecosystem intake router with OIODA's local PM copy; those files matched. Intake
  already uses service identity and tenant checks. Do not bypass these with the
  OIDA owner session or direct database writes.
- QA-Again: local README specifies Next.js, Workers, D1, R2 and Cloudflare Access;
  it explicitly describes a standalone application. This is not the migrated
  PM-QA-Again backend. Its existing cloud bindings require a separate preservation
  and hosting review before promising an Ubuntu-only deployment.
- Document Again: local README describes requirements, immutable confirmed
  revisions, fixed baselines, semantic identities and traceability. Preserve these
  domain concepts instead of replacing them with a generic file attachment list.
  Its production auth dependency uses Account Again and tenant identity.
- Infra Again: its own infrastructure request/result contracts are the starting
  boundary, not generic server-health cards. Provider execution and security/auth
  design need code and test review before claiming implemented capability.

## Staging implementation

OIDA work records support four explicit external-reference categories. These
references do not verify or synchronize a remote record. Authenticated operators
can now attach an existing OIDA execution job idempotently and read its current
state and persisted evidence/checksum through the work record. Attaching a job
does not start execution or bypass approval. Work completion is operator-reported,
not an assertion that QA or any remote module has accepted the work.

Tests exercise real constrained agent execution and evidence checksums in isolated
temporary storage, unauthorized access, duplicate attachment and missing jobs.
The ecosystem UI draft is not wired into the public frontend. No production
database, deployment, remote repository or protected workload was modified.

## Next implementation gates

1. Audit QA implementation against its README and identify the intended data to retain.
2. Map PM intake contract and tenant/service identity to an explicit OIDA adapter.
3. Define shared project mapping without changing module-owned identifiers.
4. Add configured, allowlisted adapters with timeouts, idempotency and contract tests;
   distinguish offline/unconfigured from success. Never transmit an OIDA login token
   to another service as a shortcut for SSO.
5. Complete browser UI and stage one end-to-end project workflow before cutover.
