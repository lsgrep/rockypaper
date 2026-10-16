"""How many players are online, across every server instance."""

from psr.server.ports import PresenceBoard

REPORT_TTL = 15.0  # an instance that stops reporting drops out of the total after this


class Presence:
    """Counts this instance's seated players and keeps its entry on the shared board fresh."""

    def __init__(self, board: PresenceBoard, instance: str, ttl: float = REPORT_TTL) -> None:
        self._board = board
        self._instance = instance
        self.ttl = ttl
        self.count = 0

    async def change(self, delta: int) -> None:
        self.count += delta
        await self.refresh()

    async def refresh(self) -> None:
        await self._board.report(self._instance, self.count, self.ttl)

    async def total(self) -> int:
        return await self._board.total()
