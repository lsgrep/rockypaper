"""One contract, every backend: in-memory, fakeredis, and real Redis when configured."""

import asyncio

import pytest
from conftest import BACKENDS, BackendFactory, run, wait_until

from psr.server.directory import STALE_SECONDS, RoomSummary
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


def test_presence_sums_live_instances_and_forgets_dead_ones(
    make_backend: BackendFactory,
) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            board = backend.presence
            assert await board.total() == 0
            await board.report("app-1", 3, ttl=0.2)
            await board.report("app-2", 2, ttl=30)
            assert await board.total() == 5
            await board.report("app-1", 1, ttl=0.2)  # a newer report replaces the old one
            assert await board.total() == 3
            await asyncio.sleep(0.3)  # app-1 stopped reporting (crashed)
            assert await board.total() == 2

    run(scenario)


def test_directory_lists_newest_first_and_drops_stale_rooms(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            directory = backend.directory

            def summary(code: str, at: float) -> RoomSummary:
                return RoomSummary(
                    code=code,
                    status="open",
                    players=["A"],
                    rounds=3,
                    round=0,
                    wins=[0, 0],
                    draws=0,
                    updated_at=at,
                )

            await directory.put(summary("OLD1", at=3500.0))
            await directory.put(summary("NEW1", at=5000.0))
            await directory.put(summary("MID1", at=4000.0))
            assert [r.code for r in await directory.list(now=5000.0)] == ["NEW1", "MID1", "OLD1"]

            await directory.remove("MID1")
            later = 3500.0 + STALE_SECONDS + 1  # OLD1 has not been refreshed since
            assert [r.code for r in await directory.list(now=later)] == ["NEW1"]

    run(scenario)


def test_stats_counters_add_up(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            assert await backend.stats.read() == {}
            await backend.stats.increment("online")
            await backend.stats.increment("online")
            await backend.stats.increment("computer")
            assert await backend.stats.read() == {"online": 2, "computer": 1}

    run(scenario)
