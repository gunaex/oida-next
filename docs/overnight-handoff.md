# Overnight continuation — 2026-09-05

## Newest checkpoint — 2026-09-06 after 02:30 continuation

- QA canonical source is `/home/kanphong/services-staging/qa-again` (PM-QA-Again).
  Opt-in RSA SSO verifier, password-confirmed issuer/subject→local-user mapping,
  no email auto-link, no role elevation. 46 existing QA tests + 15 integration
  tests pass. Integration tests include real QA project router/database invoked
  through OIDA's bridge; identity issuer is still a local test fixture.
- PM in OIODA now has opt-in explicit identity links and a password-confirmed
  linking endpoint; original email mapping preserved only when the new opt-in
  mode is off. One isolated integration test passes. Full PM regression remains.
- Read-only live database inspection found one active admin in each of PM/QA,
  neither requiring a password change, but different emails. Never auto-merge
  these identities. Pair through proof of existing credentials; do not ask for
  passwords in chat or modify passwords unattended.
- OIDA has a session-bound Account Again connection bridge, no stored passwords
  or refresh tokens, owner rate limits and read-only verified project import.
  Import is idempotent and does not mutate source project data. Config requires
  OIDA_ACCOUNT_ORIGIN, OIDA_PM_ORIGIN, OIDA_QA_ORIGIN (HTTPS origins). Unconfigured
  is explicit 503, not a simulated connection. No production identity config set.
- OIDA now supports secure HttpOnly owner session cookies, exact-Origin mutation
  checks, legacy Bearer compatibility and logout revocation. Frontend can resume
  owner session after navigation. Local agent still needs password re-entry to
  unlock after a service restart; cookie alone deliberately cannot decrypt it.
- OIDA Python suite 44 tests passes; Pages gateway Node suite 7 tests passes.
- PM/QA base paths /pm and /qa build, module PWA disabled only for nested builds.
  Document builds under /documents (hash routing); Infra builds under /infra.
  IMPORTANT: canonical Infra repo is `/home/kanphong/services-staging/ecosystem/INFRA-AGAIN`
  at 9a032d7. OIODA's Infra is different and is NOT the selected source. Only
  canonical Infra's vite.config.ts was edited. Document source remains OIODA.
- `scripts/build_module.py` builds in disposable storage, preserving legacy
  node_modules (Infra has tracked node_modules). `.venv-qa-integration` is an
  isolated test environment, ignored by Next Git; production dependencies untouched.
- `dist/unified-four-modules-20260906` contains all four frontend bundles plus
  OIDA. It predates the latest account-link/doc changes; always rebuild in a new
  output directory. No deployment occurred. Local Wrangler test on 8770 was
  stopped after verifying PM/QA page routes (200) and gateway disabled (503).
- Transitional Pages /modules/pm|qa gateway isolates cookies, preserves Origin,
  rejects redirects, and is DISABLED unless ENABLE_LEGACY_MODULES=true. It still
  uses existing API domain origins. Document/Infra API gateway is not implemented.
  Do not delete old API domains or enable the gateway prematurely.
- Account Again audit found administration routes without an exposed authentication
  perimeter. Do not expose it publicly as-is. Need a private deployment plus a
  narrow authenticated facade/SSO rollout, owner pairing, expiry/revocation tests,
  and public-key rotation strategy before calling unified login complete.
- No production services, DNS, user data, passwords or partitions were changed.
  Automation remains active. Work is NOT complete; no remote Git push performed.

### Remaining acceptance gates

Complete Account Again private runtime/perimeter and owner pairing UI; wire
module SSO without leaking identity tokens to pages; audit/deploy Document and
Infra behind authenticated gateway with provider mutation approval; add shared
navigation; complete browser workflow, upload/download, backup/restore and
restart checks. Only then switch production and retire old URLs with approval.

### Latest perimeter / runtime verification

Account Again now has `account_again/oida_perimeter.py`: an opt-in ASGI wrapper
with method/path-specific public login/JWKS/health, an explicit admin-token digest
for everything else, login throttling and request-size limits. Two isolated tests
pass. It is NOT wired into a deployed factory yet. Service-to-service routes need
a separately reviewed allowlist; do not pretend the blanket admin gate supports
all existing service-token flows. Never start the unwrapped app on a public port.

All four frontend bundles built successfully. A local Wrangler instance returned
200 for /documents/ and /infra/ as well as the earlier PM/QA checks. These were
HTTP route smoke tests, not browser acceptance or working module backends. The
local Wrangler process has been stopped. There is no unfinished background build.

New QA and PM pairing tests verify distinct local/central emails and preserve
VIEWER/client_viewer roles. QA's final integration test count is 15; PM has one
new isolated test. None of the production identities have been linked yet.

## User-approved target

One public OIDA Next application, preserving existing PM, live PM-QA-Again QA,
Document and Infra functionality. No link-only completion. Shared operator
identity and project context; existing services may remain internally separate.
User is sleeping; resume automatically at 02:30 Asia/Bangkok via the existing
active heartbeat. Never consume usage-reset credits without explicit permission.

## Current changes (not deployed)

- ecosystem.py: owner-authenticated work, references, project registry, unique
  per-module mappings, immutable work membership, idempotent job attachments,
  execution state and actual persisted evidence reads. Remote mappings are
  explicitly unverified; work status is operator-reported.
- module_client.py: bounded read-only PM/QA /api/projects adapter; explicit
  module credential, fixed HTTPS origin, no redirect, no browser cookie forwarding,
  timeout, bounded response, allowlisted response fields. Mock transport tests
  do not constitute real authenticated integration. No credentials configured.
- ecosystem.js now served and included in local index; projects/work controls,
  execution evidence and safe text rendering. Logout clears displayed records
  and late responses are session-checked. Browser visual/E2E tests still required.
- scripts/build_pages.py builds a fresh bundle including ecosystem.js and SHA256
  manifest, refuses to overwrite any existing destination. No live publish.
- All edits remain in staging working tree; do not lose or overwrite them.

## Actual next engineering work

1. Review Account Again existing identity implementation/tests as candidate SSO
   authority. PM supports ecosystem identity fallback; Document verifies JWKS;
   live QA currently has independent local JWT auth. Preserve inactive-user,
   forced-password-change and role checks when adding a bridge. Do not copy JWT
   secrets or pretend OIDA is CONDUCTOR_MAIN.
2. Add and test explicit account mapping/identity integration in staging; never
   auto-promote users or infer production user IDs. A self-service linking flow
   can defer actual user proof until the owner logs in without blocking coding.
3. Preserve PM/QA screens and functions while consolidating navigation/API paths.
   Inspect router base URLs, assets, cookie paths, CSRF/CORS and uploads before
   proxying. Never proxy arbitrary destinations or trust caller-supplied identity.
4. Inventory Document/Infra deployability and resource needs; infrastructure
   design is broader than host health. Keep provider mutation approval-gated.
5. Test backup/restore and an isolated full workflow. Deploy only tested slices;
   clearly separate partial staging functionality from completed production.
6. Keep old domains and protected workloads until replacement acceptance.

No claim that all modules are integrated. No changes to production data, DNS,
Docker workloads, partition layout, credentials or GitHub remote were made in
this overnight development turn.
