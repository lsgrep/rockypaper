"""Public room summaries: what the homepage lists, derived purely from room state."""

from psr.moves import Move
from psr.server.directory import RoomSummary, summarize
from psr.server.state import Phase, RoomState, SeatState

A, B = "a" * 16, "b" * 16


def room(
    seats: int,
    phase: Phase = Phase.LOBBY,
    public: bool = True,
    history: list[tuple[Move, Move]] | None = None,
) -> RoomState:
    names = ["Alice", "Bob"][:seats]
    return RoomState(
        code="K7QX",
        rounds=5,
        public=public,
        phase=phase,
        seats=[SeatState(token=t, name=n) for t, n in zip([A, B], names, strict=False)],
        history=history or [],
    )


def test_a_waiting_room_is_an_open_lobby() -> None:
    assert summarize(room(1), now=50.0) == RoomSummary(
        code="K7QX",
        status="open",
        players=["Alice"],
        rounds=5,
        round=0,
        wins=[0, 0],
        draws=0,
        updated_at=50.0,
    )


def test_a_match_in_progress_shows_round_and_score() -> None:
    history = [(Move.ROCK, Move.SCISSORS), (Move.PAPER, Move.PAPER)]
    summary = summarize(room(2, Phase.THROWING, history=history), now=1.0)
    assert summary is not None
    assert summary.status == "live"
    assert summary.players == ["Alice", "Bob"]
    assert summary.round == 3
    assert (summary.wins, summary.draws) == ([1, 0], 1)


def test_private_empty_and_finished_rooms_are_not_listed() -> None:
    assert summarize(room(1, public=False), now=0) is None
    assert summarize(room(0), now=0) is None
    assert summarize(room(2, Phase.FINISHED), now=0) is None
