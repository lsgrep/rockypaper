"""Assemble the static site in dist/: web assets plus the psr package for Pyodide."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from fetch_models import fetch_models

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PACKAGE = ROOT / "src" / "psr"
DIST = ROOT / "dist"
EXCLUDED = {"__main__.py", "cli.py"}  # console-only modules are not needed in the browser


def build(
    web: Path = WEB,
    package: Path = PACKAGE,
    dist: Path = DIST,
    fetch: Callable[[], object] = fetch_models,
) -> list[str]:
    """Rebuild `dist` from scratch; returns the Python modules shipped to the browser."""
    fetch()
    shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(web, dist, ignore=shutil.ignore_patterns("tests"))
    target = dist / "py" / "psr"
    target.mkdir(parents=True)
    modules = sorted(p.name for p in package.glob("*.py") if p.name not in EXCLUDED)
    for name in modules:
        shutil.copy2(package / name, target / name)
    (dist / "py" / "manifest.json").write_text(json.dumps({"package": "psr", "modules": modules}))
    return modules


if __name__ == "__main__":
    shipped = build()
    print(f"Built {DIST.relative_to(ROOT)}/ with {len(shipped)} Python modules")
