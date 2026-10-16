import random

import pytest

from psr.choosers import PresetChooser, RandomChooser
from psr.game import Match, MatchOverError
from psr.moves import Move
from psr.players import Player
from psr.rules import CLASSIC_RULES


class ScriptedChooser:
    def __init__(self, *moves: Move) -> None:
        self._moves = list(moves)

    def choose(self, moves: object) -> Move:
        return self._moves.pop(0)


def make_match(human: list[Move], computer: list[Move]) -> tuple[Match, Player, Player]:
    alice = Player("Alice", ScriptedChooser(*human))
    bot = Player("Bot", ScriptedChooser(*computer))
    return Match(CLASSIC_RULES, alice, bot, rounds=len(human)), alice, bot


def test_round_reports_winner_and_rule() -> None:
    match, alice, _ = make_match([Move.PAPER], [Move.ROCK])
    result = match.play_round()
    assert result.number == 1
    assert result.winner is alice
    assert result.rule is not None and result.rule.verb == "wraps"


def test_second_player_can_win() -> None:
    match, _, bot = make_match([Move.SCISSORS], [Move.ROCK])
    assert match.play_round().winner is bot


def test_draw_has_no_winner() -> None:
    match, _, _ = make_match([Move.ROCK], [Move.ROCK])
    result = match.play_round()
    assert result.is_draw
    assert result.winner is None


def test_plays_exactly_n_rounds_and_keeps_score() -> None:
    match, alice, bot = make_match(
        [Move.PAPER, Move.ROCK, Move.SCISSORS, Move.ROCK],
        [Move.ROCK, Move.PAPER, Move.SCISSORS, Move.SCISSORS],
    )
    while not match.is_over:
        match.play_round()

    assert match.rounds_played == 4
    assert [r.number for r in match.results] == [1, 2, 3, 4]
    assert match.scoreboard.wins(alice) == 2
    assert match.scoreboard.wins(bot) == 1
    assert match.scoreboard.draws == 1
    assert match.scoreboard.leader() is alice
    with pytest.raises(MatchOverError):
        match.play_round()


def test_leader_is_none_when_tied() -> None:
    match, _, _ = make_match([Move.PAPER, Move.ROCK], [Move.ROCK, Move.PAPER])
    match.play_round()
    match.play_round()
    assert match.scoreboard.leader() is None


@pytest.mark.parametrize("rounds", [0, -1])
def test_match_needs_at_least_one_round(rounds: int) -> None:
    a = Player("A", PresetChooser())
    b = Player("B", PresetChooser())
    with pytest.raises(ValueError):
        Match(CLASSIC_RULES, a, b, rounds)


def test_player_cannot_play_themselves() -> None:
    a = Player("A", PresetChooser())
    with pytest.raises(ValueError):
        Match(CLASSIC_RULES, a, a, 1)


def test_random_chooser_is_reproducible_with_seed() -> None:
    moves = CLASSIC_RULES.moves
    a, b = RandomChooser(random.Random(7)), RandomChooser(random.Random(7))
    assert [a.choose(moves) for _ in range(20)] == [b.choose(moves) for _ in range(20)]
    assert all(a.choose(moves) in moves for _ in range(20))


def test_preset_chooser_requires_a_submission() -> None:
    chooser = PresetChooser()
    with pytest.raises(RuntimeError):
        chooser.choose(CLASSIC_RULES.moves)
    chooser.submit(Move.ROCK)
    assert chooser.choose(CLASSIC_RULES.moves) is Move.ROCK
    with pytest.raises(RuntimeError):
        chooser.choose(CLASSIC_RULES.moves)


def test_preset_chooser_rejects_moves_outside_the_game() -> None:
    chooser = PresetChooser()
    chooser.submit(Move.ROCK)
    with pytest.raises(ValueError):
        chooser.choose([Move.PAPER, Move.SCISSORS])


def test_committed_chooser_fixes_its_move_before_choosing() -> None:
    from psr.choosers import CommittedChooser

    moves = CLASSIC_RULES.moves
    chooser = CommittedChooser(RandomChooser(random.Random(5)))
    assert not chooser.is_committed
    with pytest.raises(RuntimeError):
        chooser.choose(moves)

    committed = chooser.commit(moves)
    assert chooser.commit(moves) is committed  # re-committing keeps the same move
    assert chooser.choose(moves) is committed
    assert not chooser.is_committed
