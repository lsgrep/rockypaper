"""One WebSocket connection: translates client messages into room commands."""

import contextlib
import secrets
from collections.abc import Awaitable, Callable

from psr.server.ports import Envelope, EventBus, Subscription
from psr.server.protocol import (
    ClientMessage,
    CreateRoom,
    JoinRoom,
    LeaveRoom,
    RequestRematch,
    ResumeSeat,
    SetMove,
)
from psr.server.service import RoomService
from psr.server.state import (
    AskRematch,
    Command,
    Disconnect,
    Join,
    Leave,
    PlaceMove,
    ProtocolError,
    Resume,
)

Send = Callable[[str], Awaitable[None]]


class Gateway:
    def __init__(self, service: RoomService, bus: EventBus, send: Send) -> None:
        self._service = service
        self._bus = bus
        self._send = send
        self._room: str | None = None
        self._token: str | None = None
        self._subscription: Subscription | None = None

    async def handle(self, message: ClientMessage) -> None:
        match message:
            case CreateRoom(name=name, rounds=rounds):
                self._require_outside()
                code = await self._service.create_room(rounds)
                token = secrets.token_urlsafe(16)
                await self._enter(code, token, Join(token, name))
            case JoinRoom(name=name, room=code):
                self._require_outside()
                token = secrets.token_urlsafe(16)
                await self._enter(code, token, Join(token, name))
            case ResumeSeat(room=code, token=token):
                self._require_outside()
                await self._enter(code, token, Resume(token))
            case SetMove(move=move):
                room, token = self._seated()
                await self._service.execute(room, PlaceMove(token, move))
            case RequestRematch():
                room, token = self._seated()
                await self._service.execute(room, AskRematch(token))
            case LeaveRoom():
                room, token = self._seated()
                await self._service.execute(room, Leave(token))
                await self._forget()

    async def close(self) -> None:
        """The socket closed: keep the seat for a while so the player can resume."""
        if self._room is not None and self._token is not None:
            with contextlib.suppress(ProtocolError):  # the room may already be gone
                await self._service.execute(self._room, Disconnect(self._token))
        await self._forget()

    async def _enter(self, code: str, token: str, command: Command) -> None:
        # Subscribe first so this socket receives the events its own command produces.
        self._room, self._token = code, token
        self._subscription = await self._bus.subscribe(code, self._deliver)
        try:
            await self._service.execute(code, command)
        except Exception:
            await self._forget()
            raise

    async def _deliver(self, envelope: Envelope) -> None:
        if envelope.to is None or envelope.to == self._token:
            await self._send(envelope.payload)

    async def _forget(self) -> None:
        if self._subscription is not None:
            await self._subscription.close()
        self._room = self._token = self._subscription = None

    def _require_outside(self) -> None:
        if self._room is not None:
            raise ProtocolError("You are already in a room")

    def _seated(self) -> tuple[str, str]:
        if self._room is None or self._token is None:
            raise ProtocolError("Join a room first")
        return self._room, self._token
