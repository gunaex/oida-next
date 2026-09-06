"""Build in disposable storage without modifying a legacy repo's node_modules."""

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def build(source: Path, destination: Path, module: str, unified: bool = False):
    routes = {"pm": "/pm/", "qa": "/qa/", "document": "/documents/", "infra": "/infra/"}
    if module not in routes or destination.exists():
        raise ValueError("Use a supported module and a fresh destination")
    source, destination = source.resolve(), destination.resolve()
    if not (source / "package-lock.json").is_file():
        raise ValueError("A committed package lock is required")
    with tempfile.TemporaryDirectory(prefix="oida-module-build-") as temporary:
        work = Path(temporary) / "source"
        shutil.copytree(
            source,
            work,
            ignore=shutil.ignore_patterns(
                "node_modules", "dist", ".git", ".env", ".env.*", "*.tsbuildinfo"
            ),
        )
        subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=work, check=True
        )
        env = os.environ.copy()
        env.update(
            {
                "VITE_APP_BASE": routes[module],
                "VITE_API_BASE_URL": f"/modules/{module}",
                "VITE_API_URL": f"/modules/{module}",
                "VITE_OIDA_UNIFIED": "true" if unified else "false",
            }
        )
        subprocess.run(["npm", "run", "build"], cwd=work, env=env, check=True)
        if not (work / "dist/index.html").is_file():
            raise ValueError("Module did not produce an index page")
        shutil.copytree(work / "dist", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("module", choices=["pm", "qa", "document", "infra"])
    parser.add_argument("--unified", action="store_true", help="Use the OIDA shared login gateway")
    args = parser.parse_args()
    build(args.source, args.destination, args.module, args.unified)
