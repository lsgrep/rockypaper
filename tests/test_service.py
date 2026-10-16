"""RoomService across instances: shared storage, compare-and-set retries, timer takeover."""

import json

import pytest
from conftest import BACKENDS, BackendFactory, run, wait_until

from psr.moves import Move
from psr.server.engine import Engine, Timing
from psr.server.memory import (
    MemoryEventBus,
    MemoryPresenceBoard,
    MemoryRoomDirectory,
    MemoryRoomStore,
    MemoryTimerQueue,
)
from psr.server.ports import Backend, Envelope
from psr.server.service import MAX_ATTEMPTS, TIMER_LEASE, ConflictError, RoomService
from psr.server.state import Join, PlaceMove, ProtocolError, RoomState, Timer

TIMING = Timing(countdown=5.0, grace=0.5, result_pause=3.0)
A, B = "a" * 16, "b" * 16


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Inbox:
    """Collects everything published to a room, as a connected socket would see it."""

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.messages.append(json.loads(envelope.payload))

    def types(self) -> list[object]:
        return [m["type"] for m in self.messages]


async def _seated_room(service: RoomService) -> str:
    code = await service.create_room(rounds=1)
    await service.execute(code, Join(A, "Alice"))
    await service.execute(code, Join(B, "Bob"))
    return code


@pytest.mark.parametrize("make_backend", BACKENDS)
def test_two_instances_share_a_room(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            clock = Clock()
            first, second = (RoomService(backend, Engine(TIMING), clock) for _ in range(2))
            code = await first.create_room(rounds=1)
            inbox = Inbox()
            await backend.bus.subscribe(code, inbox)

            await first.execute(code, Join(A, "Alice"))  # Alice's socket is on instance 1
            await second.execute(code, Join(B, "Bob"))  # Bob's is on instance 2
            await first.execute(code, PlaceMove(A, Move.ROCK))
            await second.execute(code, PlaceMove(B, Move.SCISSORS))

            clock.now += 5.5
            assert await second.fire_due_timers() == 1
            await wait_until(lambda: "reveal" in inbox.types())
            reveal = next(m for m in inbox.messages if m["type"] == "reveal")
            assert reveal["moves"] == ["rock", "scissors"]
            assert reveal["winner"] == 0

    run(scenario)


@pytest.mark.parametrize("make_backend", BACKENDS)
def test_a_crashed_instances_timer_is_taken_over(make_backend: BackendFactory) -> None:
    async def scenario() -> None:
        async with make_backend() as backend:
            clock = Clock()
            survivor = RoomService(backend, Engine(TIMING), clock)
            code = await _seated_room(survivor)
            await survivor.execute(code, PlaceMove(A, Move.PAPER))
            await survivor.execute(code, PlaceMove(B, Move.ROCK))
            inbox = Inbox()
            await backend.bus.subscribe(code, inbox)

            clock.now += 5.5
            claimed = await backend.timers.claim_due(clock.now, TIMER_LEASE, 10)
            assert len(claimed) == 1  # the doomed instance claims it, then dies

            assert await survivor.fire_due_timers() == 0  # still leased
            clock.now += TIMER_LEASE
            assert await survivor.fire_due_timers() == 1
            await wait_until(lambda: "reveal" in inbox.types())

    run(scenario)


def test_concurrent_writers_retry_instead_of_losing_updates() -> None:
    async def scenario() -> None:
        backend, store = _racing_backend()
        service = RoomService(backend, Engine(TIMING), Clock())
        code = await _seated_room(service)

        store.race_next_save = PlaceMove(B, Move.PAPER)  # another instance sneaks in
        await service.execute(code, PlaceMove(A, Move.ROCK))

        state = await store.load(code)
        assert state is not None
        assert [s.move for s in state.seats] == [Move.ROCK, Move.PAPER]
        assert store.conflicts == 1

    run(scenario)


def test_unknown_room_is_a_protocol_error() -> None:
    async def scenario() -> None:
        service = RoomService(_racing_backend()[0], Engine(TIMING), Clock())
        with pytest.raises(ProtocolError, match="No room"):
            await service.execute("NOPE", Join(A, "Alice"))

    run(scenario)


# --- helpers -------------------------------------------------------------------------


class RacingStore:
    """A memory store that lets one competing write land between a load and a save."""

    def __init__(self, engine: Engine, clock: Clock) -> None:
        self._inner = MemoryRoomStore()
        self._engine = engine
        self._clock = clock
        self.race_next_save: PlaceMove | None = None
        self.conflicts = 0

    async def load(self, code: str) -> RoomState | None:
        return await self._inner.load(code)

    async def create(self, state: RoomState) -> bool:
        return await self._inner.create(state)

    async def delete(self, code: str, expected_version: int) -> bool:
        return await self._inner.delete(code, expected_version)

    async def save(self, state: RoomState, expected_version: int) -> bool:
        if self.race_next_save is not None:
            command, self.race_next_save = self.race_next_save, None
            current = await self._inner.load(state.code)
            assert current is not None
            rival = self._engine.apply(current, command, self._clock()).state
            assert rival is not None
            rival.version = current.version + 1
            await self._inner.save(rival, current.version)
        saved = await self._inner.save(state, expected_version)
        self.conflicts += not saved
        return saved


def _racing_backend() -> tuple[Backend, RacingStore]:
    store = RacingStore(Engine(TIMING), Clock())
    return Backend(
        store, MemoryEventBus(), MemoryTimerQueue(), MemoryPresenceBoard(), MemoryRoomDirectory()
    ), store


class AlwaysStaleStore(RacingStore):
    """Every write loses to some other instance."""

    async def save(self, state: RoomState, expected_version: int) -> bool:
        self.conflicts += 1
        return False


def test_gives_up_under_constant_contention_and_retries_the_timer_later() -> None:
    async def scenario() -> None:
        clock = Clock()
        store = AlwaysStaleStore(Engine(TIMING), clock)
        timers = MemoryTimerQueue()
        service = RoomService(
            Backend(store, MemoryEventBus(), timers, MemoryPresenceBoard(), MemoryRoomDirectory()),
            Engine(TIMING),
            clock,
        )
        code = await service.create_room(rounds=1)

        with pytest.raises(ConflictError):
            await service.execute(code, Join(A, "Alice"))
        assert store.conflicts == MAX_ATTEMPTS

        await timers.schedule(Timer(code, "round", 1, at=clock.now))
        assert await service.fire_due_timers() == 1
        clock.now += TIMER_LEASE
        assert await timers.claim_due(clock.now, TIMER_LEASE, 10) != []  # still pending

    run(scenario)


def test_timer_for_a_deleted_room_is_dropped() -> None:
    async def scenario() -> None:
        clock = Clock()
        backend = Backend(
            MemoryRoomStore(),
            MemoryEventBus(),
            MemoryTimerQueue(),
            MemoryPresenceBoard(),
            MemoryRoomDirectory(),
        )
        service = RoomService(backend, Engine(TIMING), clock)
        await backend.timers.schedule(Timer("GONE", "round", 1, at=clock.now))
        assert await service.fire_due_timers() == 1
        clock.now += 60
        assert await backend.timers.claim_due(clock.now, TIMER_LEASE, 10) == []

    run(scenario)
