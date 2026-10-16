import random
from collections.abc import Sequence
from typing import Protocol

from psr.moves import Move


class MoveChooser(Protocol):
    """Decides which move a player shows. Human input and AI strategies both fit here."""

    def choose(self, moves: Sequence[Move]) -> Move: ...


class RandomChooser:
    """Picks uniformly at random; inject a seeded `Random` for reproducible play."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def choose(self, moves: Sequence[Move]) -> Move:
        return self._rng.choice(moves)


class PresetChooser:
    """Plays a move supplied ahead of time.

    Used where input is event-driven rather than blocking (the web UI),
    and to script players in tests.
    """

    def __init__(self) -> None:
        self._pending: Move | None = None

    def submit(self, move: Move) -> None:
        self._pending = move

    def choose(self, moves: Sequence[Move]) -> Move:
        move, self._pending = self._pending, None
        if move is None:
            raise RuntimeError("No move has been submitted")
        if move not in moves:
            raise ValueError(f"{move.label} is not allowed in this game")
        return move


class CommittedChooser:
    """Fixes its move up front (via an inner chooser), before the opponent has moved.

    `commit` is idempotent until the move is played, so a replayed round keeps it.
    """

    def __init__(self, inner: MoveChooser) -> None:
        self._inner = inner
        self._committed: Move | None = None

    @property
    def committed(self) -> Move | None:
        return self._committed

    @property
    def is_committed(self) -> bool:
        return self._committed is not None

    def commit(self, moves: Sequence[Move]) -> Move:
        if self._committed is None:
            self._committed = self._inner.choose(moves)
        return self._committed

    def choose(self, moves: Sequence[Move]) -> Move:
        move, self._committed = self._committed, None
        if move is None:
            raise RuntimeError("No move has been committed")
        return move
