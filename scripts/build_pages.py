"""Build the Pages asset bundle from explicit sources, without deploying."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def build(destination: Path, modules: dict[str, Path] | None = None, shell: bool = False,
          web_source: Path | None = None):
    root = Path(__file__).resolve().parents[1]
    modules = modules or {}
    web_source = web_source or root / "oida_next" / "web"
    routes = {"pm": "pm", "qa": "qa", "document": "documents", "infra": "infra"}
    for name, source in modules.items():
        if name not in routes or not (source / "index.html").is_file():
            raise ValueError("Expected a supported module bundle")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("Symlinks are not allowed in a module bundle")
    # Require a fresh target so an old artifact or unrelated directory is never overwritten.
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for name in ("index.html", "app.js", "setup.js", "ecosystem.js", "style.css"):
        source = web_source / name
        if name == "ecosystem.js" and not source.exists():
            continue
        shutil.copyfile(source, destination / name)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    worker = root / "deployment" / "pages-worker.js"
    shutil.copyfile(worker, destination / "_worker.js")
    manifest["_worker.js"] = hashlib.sha256(worker.read_bytes()).hexdigest()
    for name, source in modules.items():
        shutil.copytree(source, destination / routes[name])
        for file in (destination / routes[name]).rglob("*"):
            if file.is_file():
                manifest[str(file.relative_to(destination))] = hashlib.sha256(
                    file.read_bytes()
                ).hexdigest()
    if shell:
        for name in ("shell.js", "shell.css"):
            source = root / "oida_next" / "web" / name
            shutil.copyfile(source, destination / name)
            manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        for page in [destination / "index.html", *(destination / routes[name] / "index.html" for name in modules)]:
            html = page.read_text()
            if "</head>" not in html:
                raise ValueError("Module HTML is missing a head element")
            enabled = ",".join(routes[name] for name in modules)
            html = html.replace("</head>", f'<link rel="stylesheet" href="/shell.css"><script src="/shell.js" data-modules="{enabled}" defer></script></head>', 1)
            page.write_text(html)
            manifest[str(page.relative_to(destination))] = hashlib.sha256(page.read_bytes()).hexdigest()
    (destination / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, help="Fresh output directory")
    parser.add_argument("--pm", type=Path, help="Built PM bundle")
    parser.add_argument("--qa", type=Path, help="Built QA bundle")
    parser.add_argument("--document", type=Path, help="Built Document bundle")
    parser.add_argument("--infra", type=Path, help="Built Infra bundle")
    parser.add_argument("--shell", action="store_true", help="Include shared application navigation")
    parser.add_argument("--web-source", type=Path, help="Existing root UI matching the deployed backend")
    args = parser.parse_args()
    modules = {
        name: value for name in ("pm", "qa", "document", "infra") if (value := getattr(args, name))
    }
    print(json.dumps(build(args.destination, modules, args.shell, args.web_source), indent=2))
