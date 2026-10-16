from enum import Enum


class Move(Enum):
    """A hand symbol a player can show."""

    ROCK = "rock"
    PAPER = "paper"
    SCISSORS = "scissors"

    @property
    def label(self) -> str:
        return self.value.capitalize()
