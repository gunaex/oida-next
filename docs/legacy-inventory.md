# Legacy reuse inventory

| Existing component | Classification | Decision |
|---|---|---|
| QA migration deployment patterns | ADAPT | Resource caps, isolated persistent directories, protected-workload discipline and backup philosophy |
| OIDA 2 Python API / SQLite approach | REFERENCE_ONLY | New control code, schema and identity protocol; no schema migration |
| OIDA model/provider concepts | REFERENCE_ONLY | New normalized Planner protocol, functional deterministic adapter |
| OIDA 2 PM/Document adapters | REFERENCE_ONLY | Not dependencies of Next execution foundation |
| OIODA monorepo BFF/account/conductor | REFERENCE_ONLY | Not inherited or deployed for Next |
| PM Again application | REUSE as independent app | Existing migrated service stays independent, not copied into Next |
| QA Again application | REUSE as independent app | Existing migrated service stays independent |
| Previous OIDA UI | REFERENCE_ONLY | New compact mission-control interface |
| Legacy Fly infrastructure | RETIRE from target design | No Fly authentication, recreation or dependency |

No legacy repository, user database, workload or Git history was deleted. “RETIRE” describes the new target architecture, not a destructive action.
