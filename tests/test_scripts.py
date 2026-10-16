"""The build, model download and load-test scripts."""

import asyncio
import io
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from build_web import build
from fastapi import FastAPI
from fetch_models import fetch_models
from load_test import Stats, percentile, report, run

from psr.server.app import create_app
from psr.server.engine import Timing

# --- build_web ---------------------------------------------------------------------


def _source_tree(root: Path) -> tuple[Path, Path]:
    web = root / "web"
    (web / "tests").mkdir(parents=True)
    (web / "index.html").write_text("<html>")
    (web / "tests" / "x.test.js").write_text("test")
    package = root / "psr"
    package.mkdir()
    for name in ("__init__.py", "game.py", "cli.py", "__main__.py"):
        (package / name).write_text("# module")
    return web, package


def test_build_ships_site_and_browser_modules_only(tmp_path: Path) -> None:
    web, package = _source_tree(tmp_path)
    dist = tmp_path / "dist"
    fetched: list[bool] = []

    modules = build(web, package, dist, fetch=lambda: fetched.append(True))

    assert fetched == [True]
    assert modules == ["__init__.py", "game.py"]  # console-only modules stay out
    assert (dist / "index.html").is_file()
    assert not (dist / "tests").exists()
    manifest = json.loads((dist / "py" / "manifest.json").read_text())
    assert manifest == {"package": "psr", "modules": ["__init__.py", "game.py"]}


def test_build_replaces_stale_output(tmp_path: Path) -> None:
    web, package = _source_tree(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "stale.js").write_text("old")
    build(web, package, dist, fetch=lambda: None)
    assert not (dist / "stale.js").exists()


# --- fetch_models ------------------------------------------------------------------


def test_fetch_downloads_only_missing_files(tmp_path: Path) -> None:
    (tmp_path / "have.bin").write_bytes(b"cached")
    requested: list[str] = []

    def opener(url: str) -> io.BytesIO:
        requested.append(url)
        return io.BytesIO(f"from {url}".encode())

    files = {"have.bin": "https://x/have", "wasm/new.bin": "https://x/new"}
    assert fetch_models(tmp_path, files, opener) == ["wasm/new.bin"]
    assert requested == ["https://x/new"]
    assert (tmp_path / "wasm" / "new.bin").read_bytes() == b"from https://x/new"
    assert (tmp_path / "have.bin").read_bytes() == b"cached"


def test_failed_download_leaves_no_file_behind(tmp_path: Path) -> None:
    class Broken(io.BytesIO):
        def read(self, *args: object) -> bytes:
            raise ConnectionError("dropped")

    with pytest.raises(ConnectionError):
        fetch_models(tmp_path, {"model.task": "https://x/m"}, lambda url: Broken())
    assert not (tmp_path / "model.task").exists()  # a retry will download it again


# --- load_test ---------------------------------------------------------------------


def test_percentile_picks_the_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 51
    assert percentile(values, 95) == 95
    assert percentile([7.0], 95) == 7


def test_report_summarises_stats() -> None:
    stats = Stats(lags=[0.01, 0.02, 0.05], matches=3, errors=["Boom: x", "Boom: x"], elapsed=2.0)
    text = report(stats, rooms=3, rounds=1)
    assert "completed matches: 3, errors: 2, took 2.0s" in text
    assert "p50=20" in text
    assert text.count("Boom: x") == 1


@contextmanager
def live_server(app: FastAPI) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    try:
        yield f"ws://127.0.0.1:{port}/ws"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_load_test_plays_real_matches_against_a_server() -> None:
    app = create_app(timing=Timing(countdown=1.5, grace=0.3, result_pause=0.05), timer_poll=0.01)
    with live_server(app) as url:
        stats = asyncio.run(run(url, rooms=5, rounds=1, ramp=0.1))
    assert stats.errors == []
    assert stats.matches == 5
    assert len(stats.lags) == 5
