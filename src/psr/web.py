"""Adapter between the browser UI (via Pyodide) and the game.

Browser input is event-driven: `start_round` makes the computer commit its move
first, then `play` submits the human's move and plays the round. Results are
returned as plain dicts for JavaScript; the committed move is never exposed early.
"""

import random
from typing import Any

from psr.choosers import CommittedChooser, PresetChooser, RandomChooser
from psr.game import Match, RoundResult
from psr.moves import Move
from psr.players import Player
from psr.presentation import describe_outcome
from psr.rules import CLASSIC_RULES, Rules


class WebSession:
    def __init__(self, rounds: int, rules: Rules = CLASSIC_RULES, seed: int | None = None) -> None:
        self._input = PresetChooser()
        self._human = Player("You", self._input)
        self._computer_chooser = CommittedChooser(RandomChooser(random.Random(seed)))
        self._computer = Player("Computer", self._computer_chooser)
        self._match = Match(rules, self._human, self._computer, rounds)

    @property
    def moves(self) -> list[str]:
        return [m.value for m in self._match.rules.moves]

    def start_round(self) -> dict[str, int]:
        """Commit the computer's move for the coming round (kept if the round is replayed)."""
        self._computer_chooser.commit(self._match.rules.moves)
        return {"round": self._match.rounds_played + 1, "rounds": self._match.rounds}

    def play(self, move: str) -> dict[str, Any]:
        self._input.submit(Move(move))
        self._computer_chooser.commit(self._match.rules.moves)
        return self._snapshot(self._match.play_round())

    def _snapshot(self, result: RoundResult) -> dict[str, Any]:
        board = self._match.scoreboard
        return {
            "round": result.number,
            "rounds": self._match.rounds,
            "human_move": result.first.move.value,
            "computer_move": result.second.move.value,
            "outcome": self._outcome_for_human(result),
            "rule": None if result.rule is None else result.rule.describe(),
            "score": {
                "human": board.wins(self._human),
                "computer": board.wins(self._computer),
                "draws": board.draws,
            },
            "is_over": self._match.is_over,
            "summary": describe_outcome(self._match) if self._match.is_over else None,
        }

    def _outcome_for_human(self, result: RoundResult) -> str:
        if result.winner is None:
            return "draw"
        return "win" if result.winner is self._human else "lose"
