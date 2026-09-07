import hashlib
import importlib.util
from pathlib import Path

import pytest


def test_pages_bundle_is_complete_and_never_overwrites(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/build_pages.py"
    spec = importlib.util.spec_from_file_location("pages_builder", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / "pages"
    manifest = module.build(destination)
    assert "ecosystem.js" in manifest
    assert "_worker.js" in manifest
    for name, checksum in manifest.items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == checksum
    with pytest.raises(FileExistsError):
        module.build(destination)
    qa = tmp_path / "qa"
    qa.mkdir()
    qa.joinpath("index.html").write_text(
        '<html><head><link rel="stylesheet" href="/shell.css">'
        '<script src="/shell.js" data-modules="qa" defer></script>'
        "</head><body>QA</body></html>"
    )
    combined = tmp_path / "combined"
    manifest = module.build(combined, {"qa": qa}, shell=True)
    for page in ["index.html", "qa/index.html"]:
        html = (combined / page).read_text()
        assert "/shell.js?v=20260907k" in html
        assert "/shell.css?v=20260907k" in html
        assert html.count("/shell.js") == 1
    shell_js = (combined / "shell.js").read_text()
    for guide in ["คู่มือ OIDA Next", "คู่มือ PM", "คู่มือ QA", "คู่มือ Document", "คู่มือ Infra"]:
        assert guide in shell_js
    assert 'aria-haspopup", "dialog"' in shell_js
    for name, checksum in manifest.items():
        assert hashlib.sha256((combined / name).read_bytes()).hexdigest() == checksum
