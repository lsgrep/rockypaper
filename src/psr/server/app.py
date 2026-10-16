"""FastAPI app: the WebSocket gateway, a timer loop, health checks, and the static site.

Every instance is stateless apart from its own sockets. With PSR_REDIS_URL set,
rooms, events and timers live in Redis, so instances can be added behind any
load balancer; without it, everything stays in memory (one instance).
"""

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from redis.asyncio import Redis

from psr.server.engine import Engine, Timing
from psr.server.gateway import Gateway
from psr.server.memory import memory_backend
from psr.server.ports import Backend
from psr.server.presence import Presence
from psr.server.protocol import CLIENT_MESSAGE, ErrorMessage
from psr.server.redis_backend import RedisEventBus, redis_backend
from psr.server.service import ConflictError, RoomService
from psr.server.state import ProtocolError

log = logging.getLogger(__name__)
TIMER_POLL_SECONDS = 0.05
VENDOR_CACHE = "public, max-age=86400"  # the 26 MB model rarely changes
INSTANCE = os.environ.get("PSR_INSTANCE", socket.gethostname())


async def run_timers(service: RoomService, poll: float) -> None:
    while True:
        try:
            claimed = await service.fire_due_timers()
        except Exception:
            log.exception("Timer loop failed; retrying")
            claimed = 0
        if claimed == 0:
            await asyncio.sleep(poll)


async def keep_presence_fresh(presence: Presence) -> None:
    while True:
        try:
            await presence.refresh()
        except Exception:
            log.exception("Presence refresh failed; retrying")
        await asyncio.sleep(presence.ttl / 3)


async def send_error(websocket: WebSocket, text: str) -> None:
    await websocket.send_text(ErrorMessage(message=text).model_dump_json())


def create_app(
    *,
    backend: Backend | None = None,
    redis: Redis | None = None,
    timing: Timing | None = None,
    static_dir: Path | None = None,
    clock: Callable[[], float] = time.time,
    timer_poll: float = TIMER_POLL_SECONDS,
    instance: str = INSTANCE,
) -> FastAPI:
    """Pass `redis` for a shared multi-instance backend, `backend` to inject one, or neither."""
    redis_bus: RedisEventBus | None = None
    if backend is None and redis is not None:
        backend, redis_bus = redis_backend(redis)
    backend = backend or memory_backend()
    service = RoomService(backend, Engine(timing), clock)
    presence = Presence(backend.presence, instance)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if redis_bus is not None:
            await redis_bus.start()
        tasks = [
            asyncio.create_task(run_timers(service, timer_poll)),
            asyncio.create_task(keep_presence_fresh(presence)),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if redis_bus is not None:
                await redis_bus.stop()

    app = FastAPI(title="Paper Scissors Rock", lifespan=lifespan)

    @app.middleware("http")
    async def cache_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        """Revalidate pages and code on every load (cheap 304s), so a deploy shows up at once."""
        response: Response = await call_next(request)
        vendor = request.url.path.startswith("/vendor/")
        response.headers.setdefault("Cache-Control", VENDOR_CACHE if vendor else "no-cache")
        return response

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        if redis is not None:
            try:
                await redis.ping()
            except Exception:
                return JSONResponse({"status": "redis unavailable"}, status_code=503)
        return JSONResponse({"status": "ok", "instance": instance})

    @app.get("/api/online")
    async def online() -> JSONResponse:
        """Players in a room or playing the computer, summed over all instances."""
        return JSONResponse({"players": await presence.total()})

    @app.websocket("/ws")
    async def play(websocket: WebSocket) -> None:
        await websocket.accept()
        gateway = Gateway(service, backend.bus, websocket.send_text, presence)
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    await gateway.handle(CLIENT_MESSAGE.validate_json(raw))
                except ValidationError:
                    await send_error(websocket, "Invalid message")
                except (ProtocolError, ConflictError) as error:
                    await send_error(websocket, str(error))
        except WebSocketDisconnect:
            pass
        finally:
            await gateway.close()

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="site")
    return app


def app_from_env() -> FastAPI:
    """Factory for uvicorn/containers, configured by PSR_REDIS_URL and PSR_STATIC_DIR."""
    url = os.environ.get("PSR_REDIS_URL")
    static = Path(os.environ.get("PSR_STATIC_DIR", "dist"))
    return create_app(
        redis=Redis.from_url(url) if url else None,
        static_dir=static if static.is_dir() else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the game and its multiplayer WebSocket.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--static", type=Path, default=Path("dist"), help="built site directory")
    parser.add_argument("--redis", default=os.environ.get("PSR_REDIS_URL"), help="redis:// URL")
    args = parser.parse_args()
    if not (args.static / "index.html").is_file():
        parser.error(f"{args.static}/index.html not found; run scripts/build_web.py first")
    logging.basicConfig(level=logging.INFO)
    app = create_app(
        redis=Redis.from_url(args.redis) if args.redis else None, static_dir=args.static
    )
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True)
