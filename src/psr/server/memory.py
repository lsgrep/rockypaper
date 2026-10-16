"""Single-process implementations of the ports: for one instance and for tests."""

import time
from collections import defaultdict
from collections.abc import Callable

from psr.server.directory import STALE_SECONDS, RoomSummary
from psr.server.ports import Backend, Envelope, Handler
from psr.server.state import RoomState, Timer


class MemoryRoomStore:
    def __init__(self) -> None:
        self._rooms: dict[str, str] = {}

    async def load(self, code: str) -> RoomState | None:
        raw = self._rooms.get(code)
        return None if raw is None else RoomState.model_validate_json(raw)

    async def create(self, state: RoomState) -> bool:
        if state.code in self._rooms:
            return False
        self._rooms[state.code] = state.model_dump_json()
        return True

    async def save(self, state: RoomState, expected_version: int) -> bool:
        current = await self.load(state.code)
        if current is None or current.version != expected_version:
            return False
        self._rooms[state.code] = state.model_dump_json()
        return True

    async def delete(self, code: str, expected_version: int) -> bool:
        current = await self.load(code)
        if current is None or current.version != expected_version:
            return False
        del self._rooms[code]
        return True


class _MemorySubscription:
    def __init__(self, bus: "MemoryEventBus", room: str, handler: Handler) -> None:
        self._bus = bus
        self._room = room
        self._handler = handler

    async def close(self) -> None:
        self._bus.remove(self._room, self._handler)


class MemoryEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    async def publish(self, room: str, envelope: Envelope) -> None:
        for handler in list(self._handlers.get(room, [])):
            await handler(envelope)

    async def subscribe(self, room: str, handler: Handler) -> _MemorySubscription:
        self._handlers[room].append(handler)
        return _MemorySubscription(self, room, handler)

    def remove(self, room: str, handler: Handler) -> None:
        handlers = self._handlers.get(room, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(room, None)


class MemoryTimerQueue:
    def __init__(self) -> None:
        self._due: dict[Timer, float] = {}

    async def schedule(self, timer: Timer) -> None:
        self._due[timer] = timer.at

    async def claim_due(self, now: float, lease: float, limit: int) -> list[Timer]:
        due = sorted((t for t, at in self._due.items() if at <= now), key=self._due.__getitem__)
        claimed = due[:limit]
        for timer in claimed:
            self._due[timer] = now + lease
        return claimed

    async def complete(self, timer: Timer) -> None:
        self._due.pop(timer, None)


class MemoryPresenceBoard:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._reports: dict[str, tuple[int, float]] = {}

    async def report(self, instance: str, count: int, ttl: float) -> None:
        self._reports[instance] = (count, self._clock() + ttl)

    async def total(self) -> int:
        now = self._clock()
        return sum(count for count, expires in self._reports.values() if expires > now)


class MemoryRoomDirectory:
    def __init__(self) -> None:
        self._rooms: dict[str, RoomSummary] = {}

    async def put(self, summary: RoomSummary) -> None:
        self._rooms[summary.code] = summary

    async def remove(self, code: str) -> None:
        self._rooms.pop(code, None)

    async def list(self, now: float) -> list[RoomSummary]:
        for code, summary in list(self._rooms.items()):
            if summary.updated_at < now - STALE_SECONDS:
                del self._rooms[code]
        return sorted(self._rooms.values(), key=lambda s: s.updated_at, reverse=True)


def memory_backend() -> Backend:
    return Backend(
        MemoryRoomStore(),
        MemoryEventBus(),
        MemoryTimerQueue(),
        MemoryPresenceBoard(),
        MemoryRoomDirectory(),
    )
