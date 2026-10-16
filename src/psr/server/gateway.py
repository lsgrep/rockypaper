"""One WebSocket connection: translates client messages into room commands."""

import contextlib
import secrets
from collections.abc import Awaitable, Callable

from psr.server.ports import Envelope, EventBus, Subscription
from psr.server.presence import Presence
from psr.server.protocol import (
    ClientMessage,
    CreateRoom,
    FinishedVsComputer,
    JoinRoom,
    LeaveRoom,
    Playing,
    RequestRematch,
    ResumeSeat,
    SendSnapshot,
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
    PlaceSnapshot,
    ProtocolError,
    Resume,
)

Send = Callable[[str], Awaitable[None]]


class Gateway:
    def __init__(
        self, service: RoomService, bus: EventBus, send: Send, presence: Presence | None = None
    ) -> None:
        self._service = service
        self._bus = bus
        self._send = send
        self._presence = presence
        self._counted = False
        self._playing_computer = False
        self._reported_match = False
        self._room: str | None = None
        self._token: str | None = None
        self._subscription: Subscription | None = None

    async def handle(self, message: ClientMessage) -> None:
        match message:
            case CreateRoom(name=name, rounds=rounds, public=public):
                self._require_outside()
                code = await self._service.create_room(rounds, public)
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
            case SendSnapshot(image=image):
                room, token = self._seated()
                await self._service.execute(room, PlaceSnapshot(token, image))
            case RequestRematch():
                room, token = self._seated()
                await self._service.execute(room, AskRematch(token))
            case LeaveRoom():
                room, token = self._seated()
                await self._service.execute(room, Leave(token))
                await self._forget()
            case Playing():
                self._playing_computer = True
                await self._count()
            case FinishedVsComputer():
                if self._playing_computer and not self._reported_match:
                    self._reported_match = True
                    await self._service.record_computer_match()

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
        await self._count()

    async def _count(self) -> None:
        """Count this connection as one online player (at most once)."""
        if self._presence is not None and not self._counted:
            self._counted = True
            await self._presence.change(+1)

    async def _deliver(self, envelope: Envelope) -> None:
        if envelope.to is None or envelope.to == self._token:
            await self._send(envelope.payload)

    async def _forget(self) -> None:
        if self._counted and self._presence is not None:
            self._counted = False
            await self._presence.change(-1)
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
