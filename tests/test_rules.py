import pytest

from psr.moves import Move
from psr.rules import CLASSIC_RULES, Rule, Rules


@pytest.mark.parametrize(
    ("winner", "loser", "verb"),
    [
        (Move.PAPER, Move.ROCK, "wraps"),
        (Move.ROCK, Move.SCISSORS, "blunts"),
        (Move.SCISSORS, Move.PAPER, "cuts"),
    ],
)
def test_classic_rules_decide_each_pairing_in_both_orders(
    winner: Move, loser: Move, verb: str
) -> None:
    expected = Rule(winner, loser, verb)
    assert CLASSIC_RULES.rule_between(winner, loser) == expected
    assert CLASSIC_RULES.rule_between(loser, winner) == expected


@pytest.mark.parametrize("move", list(Move))
def test_same_moves_draw(move: Move) -> None:
    assert CLASSIC_RULES.rule_between(move, move) is None


def test_classic_rules_use_all_three_moves() -> None:
    assert set(CLASSIC_RULES.moves) == {Move.ROCK, Move.PAPER, Move.SCISSORS}


def test_describe_rule() -> None:
    assert Rule(Move.PAPER, Move.ROCK, "wraps").describe() == "Paper wraps Rock"


def test_rejects_move_beating_itself() -> None:
    with pytest.raises(ValueError, match="cannot beat itself"):
        Rules([Rule(Move.ROCK, Move.ROCK, "smashes")])


def test_rejects_conflicting_rules() -> None:
    with pytest.raises(ValueError, match="Conflicting"):
        Rules([Rule(Move.ROCK, Move.PAPER, "x"), Rule(Move.PAPER, Move.ROCK, "y")])


def test_rejects_incomplete_rules() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        Rules([Rule(Move.PAPER, Move.ROCK, "wraps"), Rule(Move.ROCK, Move.SCISSORS, "blunts")])


def test_unknown_pairing_raises() -> None:
    rules = Rules([Rule(Move.PAPER, Move.ROCK, "wraps")])
    with pytest.raises(ValueError, match="No rule"):
        rules.rule_between(Move.PAPER, Move.SCISSORS)
