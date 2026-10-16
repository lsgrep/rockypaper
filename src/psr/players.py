from collections.abc import Sequence
from dataclasses import dataclass

from psr.choosers import MoveChooser
from psr.moves import Move


@dataclass(frozen=True, eq=False)
class Player:
    """A named participant. How the move is chosen is delegated to a `MoveChooser`.

    Players compare by identity, so two players may share a display name.
    """

    name: str
    chooser: MoveChooser

    def choose_move(self, moves: Sequence[Move]) -> Move:
        return self.chooser.choose(moves)
