"""The room's rules as a pure function: (state, command, now) -> outcome.

No I/O, no clocks, no sleeps, so every rule is unit-testable and any server
instance can apply a command to state it loaded from shared storage.
Rounds are judged by the core `Match`, replayed from the room's history.
"""

from dataclasses import dataclass

from psr.choosers import PresetChooser
from psr.game import Match
from psr.moves import Move
from psr.players import Player
from psr.presentation import describe_outcome
from psr.rules import CLASSIC_RULES, Rules
from psr.server.protocol import (
    Joined,
    Lobby,
    Notice,
    PlayerReady,
    RematchRequested,
    RoundRevealed,
    RoundStarted,
    Score,
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
    Outbound,
    Outcome,
    Phase,
    PlaceMove,
    PlaceSnapshot,
    ProtocolError,
    Resume,
    RoomState,
    SeatState,
    Timer,
    TimerState,
)

SEATS = 2
ROUND_TIMER = "round"
EVICT_PREFIX = "evict:"


@dataclass(frozen=True)
class Timing:
    countdown: float = 5.0  # players show their hand; the latest move counts
    grace: float = 1.0  # extra time for moves and the snapshot taken at zero
    result_pause: float = 3.0  # reveal stays up before the next round
    reconnect_grace: float = 20.0  # a dropped player keeps their seat this long
    max_replays: int = 2  # replays of a round someone missed before giving up


class Engine:
    def __init__(self, timing: Timing | None = None, rules: Rules = CLASSIC_RULES) -> None:
        self.timing = timing or Timing()
        self.rules = rules

    def new_room(self, code: str, rounds: int) -> RoomState:
        return RoomState(code=code, rounds=rounds)

    def apply(self, state: RoomState, command: Command, now: float) -> Outcome:
        turn = _Turn(self, state.model_copy(deep=True), now)
        turn.run(command)
        return turn.outcome()


class _Turn:
    """One command applied to a working copy of the state, collecting its effects."""

    def __init__(self, engine: Engine, state: RoomState, now: float) -> None:
        self._engine = engine
        self._timing = engine.timing
        self.state = state
        self._now = now
        self._events: list[Outbound] = []
        self._timers: list[Timer] = []
        self._deleted = False

    def outcome(self) -> Outcome:
        return Outcome(None if self._deleted else self.state, self._events, self._timers)

    def run(self, command: Command) -> None:
        match command:
            case Join(token=token, name=name):
                self._join(token, name)
            case Resume(token=token):
                self._resume(token)
            case PlaceMove(token=token, move=move):
                self._place_move(self._seat(token), move)
            case PlaceSnapshot(token=token, image=image):
                self._require_open_round()
                self._seat(token).snapshot = image
            case AskRematch(token=token):
                self._ask_rematch(self._seat(token))
            case Leave(token=token):
                self._leave(self._seat(token), f"{self._seat(token).name} left the room.")
            case Disconnect(token=token):
                self._disconnect(self._seat(token))
            case Fire(timer=timer, token=token):
                self._fire(timer, token)

    # --- commands -------------------------------------------------------------

    def _join(self, token: str, name: str) -> None:
        if len(self.state.seats) >= SEATS:
            raise ProtocolError(f"Room {self.state.code} is full")
        seat = SeatState(token=token, name=name)
        self.state.seats.append(seat)
        self._send(seat, self._joined(seat))
        self._broadcast(self._lobby())
        if len(self.state.seats) == SEATS:
            self._start_match()

    def _resume(self, token: str) -> None:
        seat = self._seat(token)
        seat.connected = True
        self.state.timers.pop(EVICT_PREFIX + token, None)
        self._send(seat, self._joined(seat))
        self._broadcast(self._lobby())
        if self.state.phase is not Phase.LOBBY:
            self._send(seat, self._sync(seat))
        self._broadcast_others(seat, Notice(text=f"{seat.name} reconnected."))

    def _require_open_round(self) -> None:
        deadline = self.state.deadline
        if self.state.phase is not Phase.THROWING or deadline is None or self._now > deadline:
            raise ProtocolError("There is no round to play right now")

    def _place_move(self, seat: SeatState, move: Move) -> None:
        self._require_open_round()
        first = seat.move is None
        seat.move = move
        if first:
            self._broadcast(PlayerReady(seat=self._index(seat)))

    def _ask_rematch(self, seat: SeatState) -> None:
        if self.state.phase is not Phase.FINISHED:
            raise ProtocolError("The match is not over yet")
        seat.wants_rematch = True
        self._broadcast(RematchRequested(seat=self._index(seat)))
        if len(self.state.seats) == SEATS and all(s.wants_rematch for s in self.state.seats):
            self._start_match()

    def _leave(self, seat: SeatState, notice: str) -> None:
        self.state.seats.remove(seat)
        self.state.timers.pop(EVICT_PREFIX + seat.token, None)
        if not self.state.seats:
            self._deleted = True
            return
        self._reset_to_lobby()
        self._broadcast(Notice(text=notice))
        self._broadcast(self._lobby())

    def _disconnect(self, seat: SeatState) -> None:
        seat.connected = False
        self._schedule(EVICT_PREFIX + seat.token, self._now + self._timing.reconnect_grace)
        self._broadcast_others(seat, Notice(text=f"{seat.name} lost connection. Waiting…"))

    def _fire(self, name: str, token: int) -> None:
        timer = self.state.timers.get(name)
        if timer is None or timer.token != token:
            return  # superseded or already handled
        del self.state.timers[name]
        if name.startswith(EVICT_PREFIX):
            seat = self._seat(name.removeprefix(EVICT_PREFIX))
            self._leave(seat, f"{seat.name} left the room.")
        elif self.state.phase is Phase.THROWING:
            self._resolve_round()
        elif self.state.phase is Phase.REVEALED:
            self._start_round(replay=False)

    # --- transitions ------------------------------------------------------------

    def _start_match(self) -> None:
        self.state.history = []
        self.state.replays = 0
        for seat in self.state.seats:
            seat.wants_rematch = False
        self._start_round(replay=False)

    def _start_round(self, replay: bool) -> None:
        state = self.state
        for seat in state.seats:
            seat.move = None
            seat.snapshot = None
        state.phase = Phase.THROWING
        state.deadline = self._now + self._timing.countdown + self._timing.grace
        self._schedule(ROUND_TIMER, state.deadline)
        self._broadcast(
            RoundStarted(
                round=len(state.history) + 1,
                rounds=state.rounds,
                countdown_ms=round(self._timing.countdown * 1000),
                replay=replay,
            )
        )

    def _resolve_round(self) -> None:
        missing = [s.name for s in self.state.seats if s.move is None]
        if not missing:
            self._reveal()
            return
        self.state.replays += 1
        who = ", ".join(missing)
        if self.state.replays > self._timing.max_replays:
            self.state.phase = Phase.FINISHED
            self.state.deadline = None
            self._broadcast(Notice(text=f"Match abandoned: {who} showed no move."))
            return
        self._broadcast(Notice(text=f"{who} showed no move. Replaying the round."))
        self._start_round(replay=True)

    def _reveal(self) -> None:
        state = self.state
        first, second = state.seats
        assert first.move is not None and second.move is not None
        state.history.append((first.move, second.move))
        state.replays = 0
        state.deadline = None
        match, players = self._engine_match()
        result = match.results[-1]
        self._broadcast(
            RoundRevealed(
                round=result.number,
                rounds=match.rounds,
                moves=[first.move, second.move],
                snapshots=[first.snapshot, second.snapshot],
                winner=None if result.winner is None else players.index(result.winner),
                rule=None if result.rule is None else result.rule.describe(),
                score=self._score(match, players),
                is_over=match.is_over,
                summary=describe_outcome(match) if match.is_over else None,
            )
        )
        if match.is_over:
            state.phase = Phase.FINISHED
            state.timers.pop(ROUND_TIMER, None)
        else:
            state.phase = Phase.REVEALED
            self._schedule(ROUND_TIMER, self._now + self._timing.result_pause)

    def _reset_to_lobby(self) -> None:
        state = self.state
        state.phase = Phase.LOBBY
        state.history = []
        state.replays = 0
        state.deadline = None
        state.timers.pop(ROUND_TIMER, None)
        for seat in state.seats:
            seat.move = None
            seat.snapshot = None
            seat.wants_rematch = False

    # --- the core game, rebuilt from history ------------------------------------

    def _engine_match(self) -> tuple[Match, list[Player]]:
        choosers = [PresetChooser(), PresetChooser()]
        players = [Player(s.name, c) for s, c in zip(self.state.seats, choosers, strict=True)]
        match = Match(self._engine.rules, players[0], players[1], self.state.rounds)
        for first, second in self.state.history:
            choosers[0].submit(first)
            choosers[1].submit(second)
            match.play_round()
        return match, players

    def _score(self, match: Match, players: list[Player]) -> Score:
        board = match.scoreboard
        return Score(wins=[board.wins(p) for p in players], draws=board.draws)

    # --- messages ---------------------------------------------------------------

    def _joined(self, seat: SeatState) -> Joined:
        return Joined(
            room=self.state.code, seat=self._index(seat), rounds=self.state.rounds, token=seat.token
        )

    def _lobby(self) -> Lobby:
        return Lobby(players=[s.name for s in self.state.seats])

    def _sync(self, seat: SeatState) -> Sync:
        match, players = self._engine_match() if len(self.state.seats) == SEATS else (None, [])
        # Clients count down to the end of the throw window, not the grace period.
        deadline = self.state.deadline
        countdown_end = None if deadline is None else deadline - self._timing.grace
        return Sync(
            phase=self.state.phase.value,
            round=len(self.state.history) + (1 if self.state.phase is Phase.THROWING else 0),
            rounds=self.state.rounds,
            score=self._score(match, players) if match else Score(wins=[0, 0], draws=0),
            remaining_ms=None
            if countdown_end is None
            else max(0, round((countdown_end - self._now) * 1000)),
            your_move=seat.move,
        )

    def _send(self, seat: SeatState, message: ServerMessage) -> None:
        self._events.append(Outbound(seat.token, message))

    def _broadcast(self, message: ServerMessage) -> None:
        self._events.append(Outbound(None, message))

    def _broadcast_others(self, seat: SeatState, message: ServerMessage) -> None:
        for other in self.state.seats:
            if other is not seat:
                self._send(other, message)

    def _schedule(self, name: str, at: float) -> None:
        self.state.next_timer_token += 1
        token = self.state.next_timer_token
        self.state.timers[name] = TimerState(token=token, at=at)
        self._timers.append(Timer(self.state.code, name, token, at))

    def _seat(self, token: str) -> SeatState:
        for seat in self.state.seats:
            if seat.token == token:
                return seat
        raise ProtocolError("You are not seated in this room")

    def _index(self, seat: SeatState) -> int:
        return self.state.seats.index(seat)
