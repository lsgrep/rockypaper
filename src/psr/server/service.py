"""Applies commands to rooms in shared storage. Safe to run on many instances at once."""

import logging
import secrets
import string
import time
from collections.abc import Callable

from psr.server.directory import RoomSummary, summarize
from psr.server.engine import Engine
from psr.server.ports import Backend, Envelope
from psr.server.protocol import RoundRevealed
from psr.server.state import Command, Fire, Outcome, ProtocolError

log = logging.getLogger(__name__)

CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1L")
CODE_LENGTH = 4
MAX_ATTEMPTS = 10
TIMER_LEASE = 5.0  # a claimed timer comes due again if its instance dies mid-way
TIMER_BATCH = 100
ONLINE_MATCHES = "online"
COMPUTER_MATCHES = "computer"


class ConflictError(RuntimeError):
    """The room kept changing underneath us; give up rather than spin."""


class RoomService:
    def __init__(
        self,
        backend: Backend,
        engine: Engine,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._backend = backend
        self._engine = engine
        self._clock = clock

    async def create_room(self, rounds: int, public: bool = True) -> str:
        for _ in range(MAX_ATTEMPTS):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if await self._backend.store.create(self._engine.new_room(code, rounds, public)):
                return code
        raise ConflictError("Could not allocate a room code")

    async def execute(self, code: str, command: Command) -> None:
        """Load, apply, and compare-and-set; retry if another instance changed the room first."""
        store = self._backend.store
        for _ in range(MAX_ATTEMPTS):
            state = await store.load(code)
            if state is None:
                raise ProtocolError(f"No room with code {code}")
            outcome = self._engine.apply(state, command, self._clock())
            if outcome.state is None:
                committed = await store.delete(code, state.version)
            else:
                outcome.state.version = state.version + 1
                committed = await store.save(outcome.state, state.version)
            if committed:
                await self._publish(code, outcome)
                await self._update_directory(code, outcome)
                await self._count_finished_match(outcome)
                return
        raise ConflictError(f"Room {code} is too busy")

    async def record_computer_match(self) -> None:
        """A match against the computer finished (it runs in the browser)."""
        await self._backend.stats.increment(COMPUTER_MATCHES)

    async def match_counts(self) -> dict[str, int]:
        counts = await self._backend.stats.read()
        return {name: counts.get(name, 0) for name in (ONLINE_MATCHES, COMPUTER_MATCHES)}

    async def list_rooms(self) -> list[RoomSummary]:
        return await self._backend.directory.list(self._clock())

    async def fire_due_timers(self) -> int:
        """Run timers that came due; returns how many were claimed."""
        timers = self._backend.timers
        due = await timers.claim_due(self._clock(), TIMER_LEASE, TIMER_BATCH)
        for timer in due:
            try:
                await self.execute(timer.room, Fire(timer.name, timer.token))
            except ProtocolError:
                pass  # the room is gone
            except ConflictError:
                log.warning("Timer %s in room %s hit contention; retrying", timer.name, timer.room)
                continue  # leave it leased so it comes due again
            await timers.complete(timer)
        return len(due)

    async def _count_finished_match(self, outcome: Outcome) -> None:
        # Counted after the commit, so each match is counted exactly once.
        if any(isinstance(e.message, RoundRevealed) and e.message.is_over for e in outcome.events):
            await self._backend.stats.increment(ONLINE_MATCHES)

    async def _update_directory(self, code: str, outcome: Outcome) -> None:
        directory = self._backend.directory
        summary = None if outcome.state is None else summarize(outcome.state, self._clock())
        if summary is None:
            await directory.remove(code)
        else:
            await directory.put(summary)

    async def _publish(self, code: str, outcome: Outcome) -> None:
        for timer in outcome.timers:
            await self._backend.timers.schedule(timer)
        for event in outcome.events:
            envelope = Envelope(event.to, event.message.model_dump_json())
            await self._backend.bus.publish(code, envelope)
