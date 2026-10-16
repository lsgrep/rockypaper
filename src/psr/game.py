from dataclasses import dataclass

from psr.moves import Move
from psr.players import Player
from psr.rules import Rule, Rules


@dataclass(frozen=True)
class Play:
    player: Player
    move: Move


@dataclass(frozen=True)
class RoundResult:
    number: int
    first: Play
    second: Play
    rule: Rule | None

    @property
    def winner(self) -> Player | None:
        if self.rule is None:
            return None
        return self.first.player if self.first.move == self.rule.winner else self.second.player

    @property
    def is_draw(self) -> bool:
        return self.rule is None


class Scoreboard:
    """Running tally of wins per player and draws."""

    def __init__(self, first: Player, second: Player) -> None:
        self._wins: dict[Player, int] = {first: 0, second: 0}
        self._draws = 0

    @property
    def draws(self) -> int:
        return self._draws

    def wins(self, player: Player) -> int:
        return self._wins[player]

    def record(self, result: RoundResult) -> None:
        winner = result.winner
        if winner is None:
            self._draws += 1
        else:
            self._wins[winner] += 1

    def leader(self) -> Player | None:
        """The player with the most wins, or None if tied."""
        (a, a_wins), (b, b_wins) = self._wins.items()
        if a_wins == b_wins:
            return None
        return a if a_wins > b_wins else b


class MatchOverError(RuntimeError):
    pass


class Match:
    """A fixed number of rounds between two players under a set of rules."""

    def __init__(self, rules: Rules, first: Player, second: Player, rounds: int) -> None:
        if rounds < 1:
            raise ValueError("A match needs at least one round")
        if first is second:
            raise ValueError("A player cannot play against themselves")
        self._rules = rules
        self._first = first
        self._second = second
        self._rounds = rounds
        self._results: list[RoundResult] = []
        self._scoreboard = Scoreboard(first, second)

    @property
    def rules(self) -> Rules:
        return self._rules

    @property
    def players(self) -> tuple[Player, Player]:
        return self._first, self._second

    @property
    def rounds(self) -> int:
        return self._rounds

    @property
    def rounds_played(self) -> int:
        return len(self._results)

    @property
    def is_over(self) -> bool:
        return self.rounds_played >= self._rounds

    @property
    def scoreboard(self) -> Scoreboard:
        return self._scoreboard

    @property
    def results(self) -> tuple[RoundResult, ...]:
        return tuple(self._results)

    def play_round(self) -> RoundResult:
        if self.is_over:
            raise MatchOverError(f"All {self._rounds} rounds have been played")
        moves = self._rules.moves
        first = Play(self._first, self._first.choose_move(moves))
        second = Play(self._second, self._second.choose_move(moves))
        result = RoundResult(
            number=self.rounds_played + 1,
            first=first,
            second=second,
            rule=self._rules.rule_between(first.move, second.move),
        )
        self._results.append(result)
        self._scoreboard.record(result)
        return result
