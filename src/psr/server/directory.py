"""The public room list on the homepage: open lobbies to join and matches in progress."""

from typing import Literal

from pydantic import BaseModel

from psr.moves import Move
from psr.rules import CLASSIC_RULES, Rules
from psr.server.state import Phase, RoomState

STALE_SECONDS = 30 * 60  # entries not refreshed for this long are dropped from the list


class RoomSummary(BaseModel):
    code: str
    status: Literal["open", "live"]
    players: list[str]
    rounds: int
    round: int
    wins: list[int]
    draws: int
    updated_at: float


def summarize(state: RoomState, now: float, rules: Rules = CLASSIC_RULES) -> RoomSummary | None:
    """What the homepage shows for a room, or None if it shouldn't be listed."""
    if not state.public or not state.seats or state.phase is Phase.FINISHED:
        return None
    wins, draws = _tally(state.history, rules)
    status: Literal["open", "live"] = "open" if len(state.seats) == 1 else "live"
    playing = state.phase is Phase.THROWING
    return RoomSummary(
        code=state.code,
        status=status,
        players=[seat.name for seat in state.seats],
        rounds=state.rounds,
        round=len(state.history) + (1 if playing else 0),
        wins=wins,
        draws=draws,
        updated_at=now,
    )


def _tally(history: list[tuple[Move, Move]], rules: Rules) -> tuple[list[int], int]:
    wins, draws = [0, 0], 0
    for first, second in history:
        rule = rules.rule_between(first, second)
        if rule is None:
            draws += 1
        else:
            wins[0 if rule.winner == first else 1] += 1
    return wins, draws
