"""Messages exchanged over the WebSocket, validated with Pydantic.

The server never tells a client the opponent's move before the round's deadline:
`PlayerReady` only says *that* a seat has a move, `RoundRevealed` carries both
moves and both camera snapshots.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from psr.moves import Move

PlayerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
RoomCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9]{4}$")
]
SeatToken = Annotated[str, StringConstraints(min_length=16, max_length=64)]
# A small JPEG frame from the player's camera, as a data URL (~20 KB at 320x240).
SnapshotImage = Annotated[
    str,
    StringConstraints(max_length=100_000, pattern=r"^data:image/jpeg;base64,[A-Za-z0-9+/]+=*$"),
]
MAX_ROUNDS = 99


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- client → server -------------------------------------------------------


class CreateRoom(Message):
    type: Literal["create"] = "create"
    name: PlayerName
    rounds: Annotated[int, Field(ge=1, le=MAX_ROUNDS)]
    public: bool = True  # listed on the homepage; private rooms are joined by code only


class JoinRoom(Message):
    type: Literal["join"] = "join"
    name: PlayerName
    room: RoomCode


class ResumeSeat(Message):
    """Reconnect to a seat after a dropped connection."""

    type: Literal["resume"] = "resume"
    room: RoomCode
    token: SeatToken


class SetMove(Message):
    """The player's current move; may change until the round's deadline."""

    type: Literal["move"] = "move"
    move: Move


class SendSnapshot(Message):
    """The player's camera frame at zero; revealed to both players with the moves."""

    type: Literal["snapshot"] = "snapshot"
    image: SnapshotImage


class RequestRematch(Message):
    type: Literal["rematch"] = "rematch"


class LeaveRoom(Message):
    type: Literal["leave"] = "leave"


class FinishedVsComputer(Message):
    """A match against the computer ended (counted once per playing connection)."""

    type: Literal["finished"] = "finished"


class Playing(Message):
    """This connection is a player outside any room (versus the computer), for the count."""

    type: Literal["playing"] = "playing"


ClientMessage = Annotated[
    CreateRoom
    | JoinRoom
    | ResumeSeat
    | SetMove
    | SendSnapshot
    | RequestRematch
    | LeaveRoom
    | Playing
    | FinishedVsComputer,
    Field(discriminator="type"),
]
CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


# --- server → client -------------------------------------------------------


class Joined(Message):
    type: Literal["joined"] = "joined"
    room: str
    seat: int
    rounds: int
    token: str  # secret; lets this client resume the seat after reconnecting


class Lobby(Message):
    type: Literal["lobby"] = "lobby"
    players: list[str]


class RoundStarted(Message):
    type: Literal["round"] = "round"
    round: int
    rounds: int
    countdown_ms: int
    replay: bool = False


class PlayerReady(Message):
    type: Literal["ready"] = "ready"
    seat: int


class Score(Message):
    wins: list[int]
    draws: int


class RoundRevealed(Message):
    type: Literal["reveal"] = "reveal"
    round: int
    rounds: int
    moves: list[Move]
    snapshots: list[str | None]
    winner: int | None
    rule: str | None
    score: Score
    is_over: bool
    summary: str | None


class RematchRequested(Message):
    type: Literal["rematch"] = "rematch"
    seat: int


class Sync(Message):
    """Snapshot sent to a client that resumed its seat."""

    type: Literal["sync"] = "sync"
    phase: str
    round: int
    rounds: int
    score: Score
    remaining_ms: int | None
    your_move: Move | None


class Notice(Message):
    type: Literal["notice"] = "notice"
    text: str


class ErrorMessage(Message):
    type: Literal["error"] = "error"
    message: str


ServerMessage = (
    Joined
    | Lobby
    | RoundStarted
    | PlayerReady
    | RoundRevealed
    | RematchRequested
    | Sync
    | Notice
    | ErrorMessage
)
