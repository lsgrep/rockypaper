"""One contract, every backend: in-memory, fakeredis, and real Redis when configured."""

import asyncio

import pytest
from conftest import BACKENDS, BackendFactory, run, wait_until

from psr.server.ports import Envelope
from psr.server.state import RoomState, Timer

pytestmark = pytest.mark.parametrize("make_backend", BACKENDS)


def test_store_creates_once_and_saves_only_on_expected_version(
    make_backend: BackendFactory,
) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            store = backend.store
            room = RoomState(code="ABCD", rounds=3)
            assert await store.create(room)
            assert not await store.create(room)

            loaded = await store.load("ABCD")
            assert loaded == room
            updated = room.model_copy(update={"version": 1, "replays": 2})
            assert await store.save(updated, expected_version=0)
            assert not await store.save(updated, expected_version=0)  # stale writer loses
            assert await store.load("ABCD") == updated

    run(scenario)


def test_store_deletes_only_on_expected_version(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            store = backend.store
            await store.create(RoomState(code="ABCD", rounds=1, version=3))
            assert not await store.delete("ABCD", expected_version=2)
            assert await store.delete("ABCD", expected_version=3)
            assert await store.load("ABCD") is None
            assert await store.load("NOPE") is None

    run(scenario)


def test_bus_delivers_to_room_subscribers_only(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            received: list[tuple[str, Envelope]] = []

            async def on(room: str, envelope: Envelope) -> None:
                received.append((room, envelope))

            sub_a = await backend.bus.subscribe("AAAA", lambda e: on("AAAA", e))
            await backend.bus.subscribe("BBBB", lambda e: on("BBBB", e))
            await backend.bus.publish("AAAA", Envelope(None, '{"x":1}'))
            await backend.bus.publish("BBBB", Envelope("tok", '{"y":2}'))
            await wait_until(lambda: len(received) == 2)
            assert received == [
                ("AAAA", Envelope(None, '{"x":1}')),
                ("BBBB", Envelope("tok", '{"y":2}')),
            ]

            await sub_a.close()
            await backend.bus.publish("AAAA", Envelope(None, "{}"))
            await asyncio.sleep(0.05)
            assert len(received) == 2

    run(scenario)


def test_timers_are_claimed_once_and_come_back_after_the_lease(
    make_backend: BackendFactory,
) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            timers = backend.timers
            early = Timer("ABCD", "round", 1, at=100.0)
            late = Timer("WXYZ", "round", 7, at=200.0)
            await timers.schedule(late)
            await timers.schedule(early)

            assert await timers.claim_due(now=150.0, lease=5.0, limit=10) == [early]
            assert await timers.claim_due(now=151.0, lease=5.0, limit=10) == []  # leased
            assert await timers.claim_due(now=156.0, lease=5.0, limit=10) == [early]  # expired

            await timers.complete(early)
            assert await timers.claim_due(now=999.0, lease=5.0, limit=10) == [late]

    run(scenario)
