# Production security review — 2026-09-07

## Result

No high-severity issue or known vulnerable Python dependency was found. The
review covered the OIDA Python source, operational scripts, public response
headers, database permissions, secret patterns, process execution, and live
service health.

## Remediated

- Restricted current and backup SQLite databases across OIDA, Account, PM, QA,
  Document, and Infra to owner-only `0600`; protected their directories with
  `0700`. All services remained active and PM/QA remained healthy afterward.
- Added HSTS, CSP, anti-framing, MIME-sniffing, referrer, and browser permission
  headers to every Pages worker response.
- Replaced a runtime `assert` on the fixed-recipe output pipe with an explicit
  failure path.
- Escaped SQLite identifiers used by the restore drill. Table names originate
  from the database schema and cannot be supplied by an operator.

## Accepted findings

Bandit reports the Unix ingress socket mode `0660` as medium severity. This is
intentional: the socket is owned by the operator, is inside a protected service
directory, and is the local boundary used by the Cloudflare ingress process.
The OIDA user service also runs with `UMask=0077`, `NoNewPrivileges`, strict
filesystem protection, and limited writable paths.

Bandit reports low-severity subprocess use. OIDA executes only fixed recipe
strings selected from its internal allowlist, with `shell=False`, isolated
working directories, a minimal environment, and no provider-generated command.
Build and dogfood scripts likewise run fixed argument arrays.

## Evidence

- Dependency audit: no known vulnerabilities.
- Bandit: 0 high, 1 accepted medium, 17 low findings with documented fixed-command use.
- Secret-pattern review: only generated test fixtures; no credential was found.
- Database permissions: current production databases are `0600`.
- Live health after hardening: OIDA, Account, Document, and Infra active; PM and
  QA containers running and healthy.

