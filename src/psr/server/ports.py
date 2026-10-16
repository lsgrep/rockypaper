"""What the room service needs from infrastructure. In-memory and Redis implement these."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from psr.server.directory import RoomSummary
from psr.server.state import RoomState, Timer


@dataclass(frozen=True)
class Envelope:
    """A serialized server message for one seat (`to` = its token) or the whole room."""

    to: str | None
    payload: str


Handler = Callable[[Envelope], Awaitable[None]]


class RoomStore(Protocol):
    """Room state with optimistic concurrency: writes succeed only on the expected version."""

    async def load(self, code: str) -> RoomState | None: ...

    async def create(self, state: RoomState) -> bool: ...

    async def save(self, state: RoomState, expected_version: int) -> bool: ...

    async def delete(self, code: str, expected_version: int) -> bool: ...


class Subscription(Protocol):
    async def close(self) -> None: ...


class EventBus(Protocol):
    """Delivers room events to every server instance holding a socket in that room."""

    async def publish(self, room: str, envelope: Envelope) -> None: ...

    async def subscribe(self, room: str, handler: Handler) -> Subscription: ...


class TimerQueue(Protocol):
    """Shared timers. A claimed timer is leased: if its claimer dies, it comes due again."""

    async def schedule(self, timer: Timer) -> None: ...

    async def claim_due(self, now: float, lease: float, limit: int) -> list[Timer]: ...

    async def complete(self, timer: Timer) -> None: ...


class PresenceBoard(Protocol):
    """Per-instance player counts that expire unless refreshed, summed across instances."""

    async def report(self, instance: str, count: int, ttl: float) -> None: ...

    async def total(self) -> int: ...


class RoomDirectory(Protocol):
    """The public room list, shared by all instances."""

    async def put(self, summary: RoomSummary) -> None: ...

    async def remove(self, code: str) -> None: ...

    async def list(self, now: float) -> list[RoomSummary]: ...


@dataclass(frozen=True)
class Backend:
    store: RoomStore
    bus: EventBus
    timers: TimerQueue
    presence: PresenceBoard
    directory: RoomDirectory
