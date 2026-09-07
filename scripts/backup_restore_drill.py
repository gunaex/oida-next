"""Create protected online SQLite backups and verify isolated restores."""

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

SOURCES = {
    "oida-control": ["/home/kanphong/services/oida-next/data/control.db"],
    "oida-agent-journal": ["/home/kanphong/services/oida-next/data/local-agent/journal.db"],
    "account": ["/home/kanphong/services/oida-account/data/account.db"],
    "pm": [
        "/home/kanphong/services/pm-again/data/master.db",
        "/home/kanphong/services/pm-again/data/projects/*.db",
    ],
    "qa": [
        "/home/kanphong/services/qa-again/data/master.db",
        "/home/kanphong/services/qa-again/data/projects/*.db",
    ],
    "document": ["/home/kanphong/services/oida-document/data/document.db"],
    "infra": ["/home/kanphong/services/oida-infra/data/.ai/infra-again.db"],
}


def inventory() -> list[tuple[str, Path]]:
    result = []
    for service, patterns in SOURCES.items():
        for pattern in patterns:
            for value in sorted(glob.glob(pattern)):
                result.append((service, Path(value)))
    return result


def facts(path: Path) -> dict:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        # SQLite cannot bind identifiers. Names are read from sqlite_master and
        # escaped as identifiers before this read-only query.
        rows = {
            name: db.execute(
                f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"'  # nosec B608
            ).fetchone()[0]
            for name in tables
        }
    return {"integrity": integrity, "tables": len(tables), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/home/kanphong/services/oida-next/backups"),
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    run = args.output_root / f"restore-drill-{time.strftime('%Y%m%d-%H%M%S')}"
    backup_dir, restore_dir = run / "backup", run / "restored"
    backup_dir.mkdir(parents=True, mode=0o700)
    restore_dir.mkdir(mode=0o700)
    os.chmod(run, 0o700)

    records = []
    for index, (service, source) in enumerate(inventory(), 1):
        name = f"{index:02d}-{service}-{source.name}"
        backup, restored = backup_dir / name, restore_dir / name
        source_facts = facts(source)
        with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        with sqlite3.connect(backup) as src, sqlite3.connect(restored) as dst:
            src.backup(dst)
        os.chmod(backup, 0o600)
        os.chmod(restored, 0o600)
        restored_facts = facts(restored)
        records.append(
            {
                "database": name,
                "service": service,
                "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "integrity": restored_facts["integrity"],
                "tables": restored_facts["tables"],
                "row_counts_match": source_facts["rows"] == restored_facts["rows"],
            }
        )
    report = {
        "healthy": all(item["integrity"] == "ok" and item["row_counts_match"] for item in records),
        "run_directory": str(run),
        "database_count": len(records),
        "databases": records,
    }
    output = json.dumps(report, indent=2) + "\n"
    report_path = args.report or run / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(output)
    report_path.chmod(0o600)
    print(output, end="")
    if not report["healthy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
