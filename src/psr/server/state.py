"""Serializable room state, the commands that change it, and what a change produces."""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel

from psr.moves import Move
from psr.server.protocol import ServerMessage


class ProtocolError(Exception):
    """A client asked for something the room's current state doesn't allow."""


class Phase(StrEnum):
    LOBBY = "lobby"
    THROWING = "throwing"
    REVEALED = "revealed"
    FINISHED = "finished"


class SeatState(BaseModel):
    token: str
    name: str
    move: Move | None = None
    wants_rematch: bool = False
    connected: bool = True


class TimerState(BaseModel):
    token: int
    at: float


class RoomState(BaseModel):
    """Everything about a room. Stored as JSON so any server instance can pick it up."""

    code: str
    rounds: int
    version: int = 0
    phase: Phase = Phase.LOBBY
    seats: list[SeatState] = []
    history: list[tuple[Move, Move]] = []
    replays: int = 0
    deadline: float | None = None
    timers: dict[str, TimerState] = {}
    next_timer_token: int = 0


# --- commands ---------------------------------------------------------------


@dataclass(frozen=True)
class Join:
    token: str
    name: str


@dataclass(frozen=True)
class Resume:
    token: str


@dataclass(frozen=True)
class PlaceMove:
    token: str
    move: Move


@dataclass(frozen=True)
class AskRematch:
    token: str


@dataclass(frozen=True)
class Leave:
    token: str


@dataclass(frozen=True)
class Disconnect:
    token: str


@dataclass(frozen=True)
class Fire:
    """A scheduled timer is due. Stale timers (token mismatch) are ignored."""

    timer: str
    token: int


Command = Join | Resume | PlaceMove | AskRematch | Leave | Disconnect | Fire


# --- outcome ----------------------------------------------------------------


@dataclass(frozen=True)
class Outbound:
    """A message for one seat (`to` = its token) or everyone in the room (`to` = None)."""

    to: str | None
    message: ServerMessage


@dataclass(frozen=True)
class Timer:
    room: str
    name: str
    token: int
    at: float


@dataclass
class Outcome:
    state: RoomState | None  # None: the room is empty and should be deleted
    events: list[Outbound] = field(default_factory=list)
    timers: list[Timer] = field(default_factory=list)
