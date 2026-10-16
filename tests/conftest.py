import asyncio
import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis

from psr.server.memory import memory_backend
from psr.server.ports import Backend
from psr.server.redis_backend import redis_backend

REAL_REDIS_URL = os.environ.get("PSR_TEST_REDIS_URL")
BackendFactory = Callable[[], AbstractAsyncContextManager[Backend]]


def run(test: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(test())


async def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


@asynccontextmanager
async def _memory() -> AsyncIterator[Backend]:
    yield memory_backend()


@asynccontextmanager
async def _redis(client: Redis) -> AsyncIterator[Backend]:
    backend, bus = redis_backend(client)
    await bus.start()
    try:
        yield backend
    finally:
        await bus.stop()
        await client.aclose()


@asynccontextmanager
async def _fakeredis() -> AsyncIterator[Backend]:
    async with _redis(FakeRedis(server=FakeServer())) as backend:
        yield backend


@asynccontextmanager
async def _real_redis() -> AsyncIterator[Backend]:
    assert REAL_REDIS_URL is not None
    client = Redis.from_url(REAL_REDIS_URL)
    await client.flushdb()
    async with _redis(client) as backend:
        yield backend


BACKENDS = [
    pytest.param(_memory, id="memory"),
    pytest.param(_fakeredis, id="fakeredis"),
    pytest.param(
        _real_redis,
        id="redis",
        marks=pytest.mark.skipif(not REAL_REDIS_URL, reason="set PSR_TEST_REDIS_URL"),
    ),
]
