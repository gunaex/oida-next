# Overnight continuation — 2026-09-05

## SSO UX correction — 2026-09-07 03:05 Bangkok

User reported `Unexpected token '<'` in the OIDA work area and that PM/QA still
showed “Continue in OIDA Next.” Investigation confirmed the OIDA cookie and
private identity were valid; the central identity showed connected. PM/QA were
correctly denying the as-yet-unlinked owner identity. The UI failed to lead the
user directly to the required one-time proof, and stale unversioned scripts made
the new behavior appear inconsistent.

Deployed https://ac79db2b.oida-next.pages.dev to the existing production Pages
project. PM/QA “Continue” now links to `/?connect=pm|qa`; OIDA opens the matching
password-confirmed pairing form and selects that module. Root scripts are
versioned to invalidate stale browser cache. API parsing now handles non-JSON
upstream failures without leaking the raw JSON parser exception. Verified in
the real browser: OIDA session is connected, PM route opens the expanded PM
pairing form, all four navigation items render, and work/project empty states
load without the earlier parser error.

No password was entered by the agent. PM and QA remain unlinked and therefore
unusable through SSO until the user enters each existing module credential once
in the displayed OIDA form. This is required because production PM/QA emails
differ and automatic merging is forbidden. After both successful link messages,
verify `/pm/` and `/qa/` authenticated workflows, uploads/downloads, and final
cross-module acceptance. Keep the heartbeat paused until the user completes
this proof and replies.

## SSO and four-module deployment — 2026-09-07 03:00 Bangkok

Deployed one OIDA entry login and unified gateway at
https://oida-next.kanphong.com. PM and QA no longer show separate login forms
after a cache-bypassing reload; they direct locked users back to OIDA. The
private owner exchange is fixed to one provisioned owner identity and accepts
no caller-selected account, tenant, email, or role. It uses a separate
server-held capability over a Unix socket. OIDA logout removes the in-memory
identity connection. No reset credit was consumed.

Private systemd services are active and enabled for Account, Document and
canonical Infra. Document and Infra listen only on Unix sockets. PM and QA run
the staged SSO-aware images with pinned public verification key and preserve
their legacy login and data on the old domains. Before activation, PM/QA online
backups were created at 20260906-120920. All four OIDA/Account/Document/Infra
SQLite databases were backed up and verified with isolated integrity checks.
All four private services restarted successfully.

Production Pages deployment: https://5d121153.oida-next.pages.dev on the
existing oida-next project and custom domain. A server-side acceptance session
verified `/api/v1/identity` 200, Document projects 200, Infra designs 200, and
PM/QA 401 because their existing accounts have not yet been password-confirmed
and linked. The temporary acceptance session was deleted. Existing user records,
roles and passwords were not changed. Next suite 53 passes; Pages gateway 9;
QA integration 16; PM identity integration 1; ruff and mypy pass. Public module
HTML titles and private SSO authorization checks pass.

Required user action: in the browser now on the OIDA root, enter the existing
OIDA operator password. Under Module identity, use “Connect an existing PM or
QA account” once for each module, entering each module's existing email/password
in the application. Never request those passwords in chat. After the user says
both are linked, verify authenticated PM/QA workflows through the public domain,
then run upload/download and final cross-module browser acceptance. The task is
not complete until those checks pass. Pause the heartbeat while this proof is
required, then resume it when the user replies.

## Schedule correction — 2026-09-06, latest user instruction

User corrected their reading of quota: resume at 19:01 Asia/Bangkok for the
five-hour reset, and continue working until the original integration succeeds.
Existing heartbeat updated in place to ACTIVE daily 19:01, same current task.
This supersedes all 08:46 scheduling below. No duplicate automation created.
If quota resets seconds after 19:01, recheck after a short wait rather than
skipping the whole day. Preserve the user-reported login failure and mandatory
OIDA-entry SSO priorities below; do not claim completion without authenticated
acceptance. Never consume reset credits without explicit permission.

## USER CORRECTION / deferred continuation — 2026-09-06 14:23 Bangkok

User reports PM/QA LOGIN DOES NOT WORK in the published OIDA release. Treat
this as unresolved production failure; earlier health/login-page checks did
NOT establish usability. User explicitly rejects separate PM/QA logins: one
SSO login at OIDA is mandatory. Do not repeat the transitional-login detour or
claim 2/4 integration complete from routing alone.

User now requests continuation after usage returns, at 08:46. Existing heartbeat
continue-oida-ecosystem-integration updated in place: ACTIVE, daily 08:46
Asia/Bangkok, same current task; no duplicate. Check usage before resuming.
At 14:22 Bangkok the account tool reported 5-hour window used 82%, reset
2026-09-06 19:01:28 Bangkok; weekly used 90%, reset 2026-09-12 08:45:41 Bangkok.
These are observations, not a guarantee or an explanation of changed times.
Never consume a reset credit without explicit authorization.

Next run: diagnose actual PM/QA authentication failure, implement secure OIDA
entry-point SSO and one-time explicit account pairing preserving module roles,
then finish Document/Infra real runtime integration and authenticated acceptance.
User wants economical work and periodic concrete progress/remaining updates.
No further production changes were made after the user's pause request.

## Live PM/QA release — 2026-09-06 14:17 Bangkok

Owner task remains 01a0758c-b175-7ef2-9396-4c058ffe382b. User asked for faster
visible results and periodic updates including remaining progress. Continue
working toward the full original integration; this release is only incremental.

DEPLOYED to existing Cloudflare Pages project oida-next, production main:
https://47719f99.oida-next.pages.dev (custom domain oida-next.kanphong.com).
Previous deployment for rollback: cf76232f-b353-4ce8-ba76-8921ce5659b8.
Bundle: dist/live-pm-qa-20260906. Fresh PM/QA builds use ORIGINAL module logins,
not --unified. Root UI copied from the LIVE runtime to match its deployed API;
staging identity/ecosystem UI/backend have NOT been deployed. Shared shell lists
only included modules. ENABLE_LEGACY_MODULES=true, ENABLE_UNIFIED_MODULES=false
in wrangler.toml. This is functional same-origin proxying, not shared login.

Production changes: added https://oida-next.kanphong.com to ALLOWED_ORIGINS in
PM/QA .env, preserved original domains, recreated ONLY those backend containers
with existing images. Both healthy. Original settings backed up as
.env.before-oida-origin-20260906 in each service root (private; do not print).
PM online database backup: backups/20260906-071520 (integrity verified by script).
QA full backup: backups/20260906-071521. No credentials or user records changed.
Protected workloads and old domains remain untouched.

Verified: real browser shows PM and QA login pages with same-origin navigation;
both /modules/{pm,qa}/api/health 200 and unauthenticated projects 401. Invalid
login returns 401 for both (use example.com, not reserved .invalid rejected by
QA email validation). PM cross-origin login rejected 403. Gateway tests 9 pass;
builder test passes. Authenticated end-to-end acceptance still needs actual
owner login; do not claim it passed. No temporary production accounts created.

Remaining: authenticated workflow acceptance; restricted owner exchange/shared
login with explicit module pairing; actual Document/Infra runtimes and gateway;
upload/download/cross-module/restore checks. Progress: 2/4 modules publicly
routed to real backends, 0/4 full authenticated acceptance verified.

## Ownership transferred — 2026-09-06, new chat

Current implementation task: `01a0758c-b175-7ef2-9396-4c058ffe382b`.
The user explicitly requested continuation from OIDA-CONTINUE.md, no rebuild.
Read the previous STOP/HANDOFF below for the implementation baseline.
The old task was confirmed idle before taking ownership.
Existing automation `continue-oida-ecosystem-integration` was updated through
Codex to target this task; ACTIVE, daily 19:05 Asia/Bangkok, same prompt and
safeguards. No duplicate automation was created. Earlier old-task targeting
statements below are historical and superseded by this section.

Verified baseline: Next HEAD dce2078, clean working tree before this checkpoint;
full Next pytest suite rerun: 51 passed (two dependency deprecation warnings).
Inspected current identity bridge, pairing and project reader. Private Account
socket and module gateway are implemented; PM/QA pairing and project reads
still use HTTPS origins. Restricted owner-token exchange is still unimplemented.
No production changes or new authentication authority have been provisioned.
Next engineering work remains private runtime/owner onboarding and secure
shared login, followed by actual backend and public workflow acceptance.

## STOP / HANDOFF — user requested a fresh chat, 2026-09-06 14:08 Bangkok

User asked to move chats and schedule continuation after their reported quota
reset at 19:05. Automation continue-oida-ecosystem-integration is now ACTIVE at
19:05 Asia/Bangkok, still targeting thread 01a06ce7-75fb-7300-8f9c-6e2d8a6114ae.
Retarget that EXISTING automation when a new task takes ownership; no duplicates
or concurrent repository edits. The exact reset time was supplied by the user,
not independently verified. Never redeem usage-reset credits without permission.

All current implementation was committed locally, not pushed or deployed:
- Next acb847a (plus this handoff update)
- QA dbb6848
- OIODA 3c77851 (Account factory earlier a828082)
- canonical Infra ea1a644

Final checks: Next 51 passed + lint/type checks; Pages 9 passed; PM 44 existing
tests passed; QA 16 integration tests passed with real Account issuer included;
Document 230 passed before pinned-key/factory additions, then 13 dedicated tests
passed including real private app and tenant isolation; Infra 39 unit/contract/
perimeter tests passed. Provider-mutating integration suites were NOT run.
No test/build processes left running. Root has 14 GiB free; /data does not exist.
Docker Compose is now v5.5.1 (read-only observation, not installed this turn).

The LAST proposed next step was replacing the transitional double login with a
restricted private owner-token exchange, relying on OIDA's existing verified
owner session. This was DISCUSSED ONLY, NOT IMPLEMENTED. It must never become
an arbitrary token-minting endpoint or impersonate CONDUCTOR_MAIN. Preserve
explicit PM/QA password-confirmed linking and module-owned roles. No production
Account owner, keys, token exchange, or identity pairing has been provisioned.

Continue engineering from the existing code, not a fresh rebuild. Deployment,
owner onboarding, backup/restore/restart validation and public end-to-end
acceptance are still outstanding. Do not call this complete from test counts.

## Latest continuation — 2026-09-06, 14:00 heartbeat received during active work

User explicitly said continue now, with 80% remaining. Do not treat the schedule
as a reason to stop implementation. No production changes in this slice.

- Next now has password-confirmed PM/QA pairing from its UI. Local module login
  cookies stay in a request-scoped client; the temporary refresh session is
  revoked in finally. Server identity never goes to browser or logs. Existing
  explicit issuer/subject mappings and module roles remain authoritative.
- New fixed-upstream gateway supports all four module API namespaces. Owner
  session + connected central identity are mandatory. Browser cookies/actor
  headers are not forwarded to modules; only server-held central Bearer token.
  Upload cap 8 MiB, download cap 32 MiB, no redirects, no response cookies.
  API paths /api/v1/modules/{module}/proxy/{path} intentionally omitted from
  OpenAPI to avoid duplicate operation IDs for multi-method proxy routes.
- IdentityConfig supports private Account Unix socket, optional Document/Infra
  origins, and per-module sockets. OIDA_ACCOUNT_SOCKET, OIDA_DOCUMENT_ORIGIN,
  OIDA_INFRA_ORIGIN, OIDA_DOCUMENT_SOCKET, OIDA_INFRA_SOCKET are new deployment
  inputs. Account socket has a real Unix-socket transport test, without DNS/TCP.
  PM/QA pairing/project reader still use their HTTPS origins (not module sockets).
- Pages has ENABLE_UNIFIED_MODULES opt-in mode forwarding only the owner cookie
  to Next's fixed API gateway. Default remains disabled; legacy mode remains.
  PM/QA --unified frontend builds use OIDA login/lock behavior. No live enablement.
- Shared navigation is built with build_pages.py --shell; scripts/shell assets
  only added to generated bundles, preserving all original module applications.
  Latest bundle dist/unified-identity-shell-20260906 predates the final four-module
  gateway extension; rebuild a fresh destination before any deployment.
- Real Account Again factory + real QA routes + Next bridge test now covers
  login, different-email pairing, revoked temporary refresh token, existing
  VIEWER role, forbidden project creation, project reading/import, disabled user.
  Run QA integration with PYTHONPATH containing backend, Next and Account roots.
  All 16 integration tests passed together. PM original tests: 44 passed.
- Document original tests + initial new security tests: 230 passed. Subsequent
  private-key-pinning/factory tests: 13 passed, including real app bootstrap in a
  temporary directory, authenticated project creation and cross-tenant isolation.
  New app.oida_app:create_app requires explicit data/db/issuer/public key and
  AUTH_MODE=ecosystem; disallows DATABASE_URL override. Human identity requires
  exp/iat/sub/email/tenantId and <=1h lifetime, rejects forced-password-change.
  Optional pinned PUBLIC key avoids needing a public Account JWKS endpoint.
- Canonical Infra now has infra_again.oida_app:create_app: explicit dedicated
  working/data directory, persistent RSA public key and allowed OWNER SUBJECT.
  Signed identity mandatory; provider execution/runner writes/test routes denied.
  Two tests pass, including real app in a temporary directory (no provider calls).
  This is a design-only perimeter, not complete execution integration. The legacy
  API includes demo generation and incomplete provider flows; don't label those
  production-ready. Full canonical Infra regression remains to run.
- Next full suite passed 50 before the last extra four-module routing test; that
  new test passed separately. Node gateway suite: 9 passed. All lint/type checks
  passed before the final checkpoint. No browser acceptance performed.

Remaining: complete private runtime/owner provisioning and actual module config,
PM trust transport/pinned key rollout, production backups + restore/restart test,
all-module end-to-end public acceptance, larger-file handling if required, Infra
approval-bound execution and remaining workflow preservation. No auto-linking
production users; owner credential proof must occur through the app, never chat.
Old URLs, services and databases remain untouched. No GitHub push yet.

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
