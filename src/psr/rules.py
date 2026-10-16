from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from psr.moves import Move


@dataclass(frozen=True)
class Rule:
    """One edge of the game: `winner` beats `loser`, described by `verb`."""

    winner: Move
    loser: Move
    verb: str

    def describe(self) -> str:
        return f"{self.winner.label} {self.verb} {self.loser.label}"


class Rules:
    """A complete, unambiguous set of rules for a hand game.

    The rules are pure data, so variants (e.g. Rock Paper Scissors Lizard Spock)
    need only a different rule table, not different game logic.
    """

    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules: dict[frozenset[Move], Rule] = {}
        for rule in rules:
            self._add(rule)
        self._moves = tuple(m for m in Move if any(m in pair for pair in self._rules))
        self._check_complete()

    @property
    def moves(self) -> tuple[Move, ...]:
        return self._moves

    def rule_between(self, first: Move, second: Move) -> Rule | None:
        """Return the rule deciding `first` vs `second`, or None for a draw."""
        if first == second:
            return None
        try:
            return self._rules[frozenset((first, second))]
        except KeyError:
            raise ValueError(f"No rule covers {first.label} vs {second.label}") from None

    def _add(self, rule: Rule) -> None:
        if rule.winner == rule.loser:
            raise ValueError(f"{rule.winner.label} cannot beat itself")
        pair = frozenset((rule.winner, rule.loser))
        if pair in self._rules:
            raise ValueError(f"Conflicting rules for {rule.describe()}")
        self._rules[pair] = rule

    def _check_complete(self) -> None:
        missing = [
            f"{a.label} vs {b.label}"
            for a, b in combinations(self._moves, 2)
            if frozenset((a, b)) not in self._rules
        ]
        if missing:
            raise ValueError(f"Rules are incomplete, missing: {', '.join(missing)}")


CLASSIC_RULES = Rules(
    [
        Rule(Move.PAPER, Move.ROCK, "wraps"),
        Rule(Move.ROCK, Move.SCISSORS, "blunts"),
        Rule(Move.SCISSORS, Move.PAPER, "cuts"),
    ]
)
