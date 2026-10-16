"""The room rules, tested as a pure function with an explicit clock."""

import pytest

from psr.moves import Move
from psr.server.engine import Engine, Timing
from psr.server.protocol import (
    Joined,
    Lobby,
    Notice,
    PlayerReady,
    RematchRequested,
    RoundRevealed,
    RoundStarted,
    ServerMessage,
    Sync,
)
from psr.server.state import (
    AskRematch,
    Command,
    Disconnect,
    Fire,
    Join,
    Leave,
    Outcome,
    Phase,
    PlaceMove,
    PlaceSnapshot,
    ProtocolError,
    Resume,
    RoomState,
)

TIMING = Timing(countdown=5.0, grace=0.5, result_pause=3.0, reconnect_grace=20.0, max_replays=2)
A, B = "a" * 16, "b" * 16


class Table:
    """Drives one room through the engine, firing timers by advancing a fake clock."""

    def __init__(self, rounds: int = 3) -> None:
        self.engine = Engine(TIMING)
        self.state: RoomState | None = self.engine.new_room("ROOM", rounds)
        self.now = 1000.0
        self.sent: list[tuple[str | None, ServerMessage]] = []

    def do(self, command: Command) -> Outcome:
        assert self.state is not None
        outcome = self.engine.apply(self.state, command, self.now)
        self.state = outcome.state
        self.sent += [(e.to, e.message) for e in outcome.events]
        return outcome

    def advance(self, seconds: float) -> None:
        """Move the clock and fire every timer that came due, as the server's poller would."""
        self.now += seconds
        while self.state is not None:
            due = [(n, t) for n, t in self.state.timers.items() if t.at <= self.now]
            if not due:
                return
            name, timer = min(due, key=lambda item: item[1].at)
            self.do(Fire(name, timer.token))

    def seated(self) -> "Table":
        self.do(Join(A, "Alice"))
        self.do(Join(B, "Bob"))
        return self

    def of_type[T](self, kind: type[T], to: str | None = None) -> list[T]:
        return [m for t, m in self.sent if isinstance(m, kind) and (to is None or t in (to, None))]


def test_joining_seats_players_and_starts_when_full() -> None:
    table = Table()
    table.do(Join(A, "Alice"))
    assert table.of_type(Joined, A) == [Joined(room="ROOM", seat=0, rounds=3, token=A)]
    assert table.of_type(RoundStarted) == []

    outcome = table.do(Join(B, "Bob"))
    assert table.of_type(Lobby)[-1].players == ["Alice", "Bob"]
    assert table.of_type(RoundStarted) == [RoundStarted(round=1, rounds=3, countdown_ms=5000)]
    assert outcome.timers[0].at == table.now + 5.5  # countdown + grace


def test_joined_message_goes_only_to_the_joiner() -> None:
    table = Table().seated()
    assert [to for to, m in table.sent if isinstance(m, Joined)] == [A, B]


def test_third_player_is_rejected() -> None:
    table = Table().seated()
    with pytest.raises(ProtocolError, match="full"):
        table.do(Join("c" * 16, "Carol"))


def test_moves_stay_hidden_and_latest_counts_until_the_deadline() -> None:
    table = Table(rounds=1).seated()
    table.do(PlaceMove(A, Move.ROCK))
    table.do(PlaceMove(A, Move.PAPER))
    table.do(PlaceMove(B, Move.ROCK))

    assert table.of_type(PlayerReady) == [PlayerReady(seat=0), PlayerReady(seat=1)]
    assert table.of_type(RoundRevealed) == []  # both moved, but the clock decides

    table.advance(5.5)
    (reveal,) = table.of_type(RoundRevealed)
    assert reveal.moves == [Move.PAPER, Move.ROCK]
    assert reveal.winner == 0
    assert reveal.rule == "Paper wraps Rock"
    assert reveal.score.wins == [1, 0]
    assert reveal.is_over
    assert reveal.summary == "Match winner: Alice. Final score: Alice 1 - 0 Bob (draws: 0)"


def test_no_message_reveals_a_move_before_the_deadline() -> None:
    table = Table().seated()
    table.do(PlaceMove(A, Move.SCISSORS))
    table.do(PlaceMove(B, Move.PAPER))
    for _, message in table.sent:
        assert "scissors" not in message.model_dump_json()


def test_moves_after_the_deadline_are_rejected() -> None:
    table = Table().seated()
    table.now += 5.6
    with pytest.raises(ProtocolError, match="no round"):
        table.do(PlaceMove(A, Move.ROCK))


def test_grace_period_still_accepts_moves() -> None:
    table = Table().seated()
    table.now += 5.4
    table.do(PlaceMove(A, Move.ROCK))
    assert table.of_type(PlayerReady) == [PlayerReady(seat=0)]


def test_plays_n_rounds_with_pauses_between() -> None:
    table = Table(rounds=2).seated()
    for _ in range(2):
        table.do(PlaceMove(A, Move.ROCK))
        table.do(PlaceMove(B, Move.SCISSORS))
        table.advance(5.5)
        table.advance(3.0)

    reveals = table.of_type(RoundRevealed)
    assert [r.round for r in reveals] == [1, 2]
    assert reveals[-1].score.wins == [2, 0]
    assert reveals[-1].is_over
    assert [r.round for r in table.of_type(RoundStarted)] == [1, 2]
    assert table.state is not None and table.state.phase is Phase.FINISHED


def test_missed_round_replays_then_abandons() -> None:
    table = Table().seated()
    for _ in range(3):
        table.do(PlaceMove(A, Move.ROCK))  # moves reset on every replay
        table.advance(5.5)

    assert [n.text for n in table.of_type(Notice)] == [
        "Bob showed no move. Replaying the round.",
        "Bob showed no move. Replaying the round.",
        "Match abandoned: Bob showed no move.",
    ]
    assert [r.replay for r in table.of_type(RoundStarted)] == [False, True, True]
    assert table.state is not None and table.state.phase is Phase.FINISHED


def test_rematch_needs_both_players() -> None:
    table = Table(rounds=1).seated()
    with pytest.raises(ProtocolError, match="not over"):
        table.do(AskRematch(A))
    table.do(PlaceMove(A, Move.ROCK))
    table.do(PlaceMove(B, Move.ROCK))
    table.advance(5.5)

    table.do(AskRematch(A))
    assert table.of_type(RematchRequested) == [RematchRequested(seat=0)]
    assert len(table.of_type(RoundStarted)) == 1
    table.do(AskRematch(B))
    assert table.of_type(RoundStarted)[-1].round == 1
    assert len(table.of_type(RoundStarted)) == 2


def test_leaving_resets_to_lobby_and_last_one_out_deletes_the_room() -> None:
    table = Table().seated()
    table.do(PlaceMove(A, Move.ROCK))
    table.do(Leave(B))
    assert table.of_type(Notice)[-1].text == "Bob left the room."
    assert table.state is not None and table.state.phase is Phase.LOBBY
    assert "round" not in table.state.timers

    outcome = table.do(Leave(A))
    assert outcome.state is None


def test_disconnected_player_is_evicted_after_grace() -> None:
    table = Table().seated()
    table.do(Disconnect(B))
    assert table.of_type(Notice, A)[-1].text == "Bob lost connection. Waiting…"
    table.advance(20.0)
    assert table.state is not None
    assert [s.name for s in table.state.seats] == ["Alice"]


def test_resume_keeps_the_seat_and_syncs_the_round() -> None:
    table = Table().seated()
    table.do(PlaceMove(B, Move.PAPER))
    table.do(Disconnect(B))
    table.now += 2.0
    table.do(Resume(B))
    table.advance(30.0)  # the eviction timer must be gone

    assert table.state is not None and len(table.state.seats) == 2
    sync = table.of_type(Sync, B)[0]
    assert sync.phase == "throwing"
    assert sync.round == 1
    assert sync.remaining_ms == 3000
    assert sync.your_move is Move.PAPER


def test_stale_timers_are_ignored() -> None:
    table = Table().seated()
    assert table.state is not None
    old = table.state.timers["round"].token
    table.do(Leave(B))
    table.do(Join(B, "Bob"))  # a new round timer replaces the old one
    before = list(table.sent)
    table.do(Fire("round", old))
    assert table.sent == before


def test_strangers_cannot_act_in_the_room() -> None:
    table = Table().seated()
    with pytest.raises(ProtocolError, match="not seated"):
        table.do(PlaceMove("z" * 16, Move.ROCK))


def test_apply_does_not_mutate_the_input_state() -> None:
    table = Table().seated()
    assert table.state is not None
    original = table.state.model_dump()
    table.engine.apply(table.state, PlaceMove(A, Move.ROCK), table.now)
    assert table.state.model_dump() == original


PHOTO_A = "data:image/jpeg;base64,QUFB"
PHOTO_B = "data:image/jpeg;base64,QkJC"


def test_snapshots_stay_hidden_until_the_reveal() -> None:
    table = Table(rounds=2).seated()
    table.do(PlaceMove(A, Move.ROCK))
    table.do(PlaceSnapshot(A, PHOTO_A))
    table.do(PlaceMove(B, Move.PAPER))
    table.do(PlaceSnapshot(B, PHOTO_B))
    assert all("base64" not in m.model_dump_json() for _, m in table.sent)

    table.advance(5.5)
    (reveal,) = table.of_type(RoundRevealed)
    assert reveal.snapshots == [PHOTO_A, PHOTO_B]


def test_missing_snapshot_reveals_as_none_and_resets_next_round() -> None:
    table = Table(rounds=2).seated()
    table.do(PlaceMove(A, Move.ROCK))
    table.do(PlaceSnapshot(A, PHOTO_A))
    table.do(PlaceMove(B, Move.ROCK))
    table.advance(5.5)
    assert table.of_type(RoundRevealed)[0].snapshots == [PHOTO_A, None]

    table.advance(3.0)  # next round starts
    table.do(PlaceMove(A, Move.PAPER))
    table.do(PlaceMove(B, Move.ROCK))
    table.advance(5.5)
    assert table.of_type(RoundRevealed)[1].snapshots == [None, None]


def test_snapshot_after_the_deadline_is_rejected() -> None:
    table = Table().seated()
    table.now += 5.6
    with pytest.raises(ProtocolError, match="no round"):
        table.do(PlaceSnapshot(A, PHOTO_A))
