from psr.choosers import PresetChooser
from psr.game import Match
from psr.moves import Move
from psr.players import Player
from psr.presentation import describe_outcome, describe_round
from psr.rules import CLASSIC_RULES


def test_describes_win_and_draw() -> None:
    a_in, b_in = PresetChooser(), PresetChooser()
    match = Match(CLASSIC_RULES, Player("You", a_in), Player("Computer", b_in), rounds=2)

    a_in.submit(Move.ROCK)
    b_in.submit(Move.SCISSORS)
    assert describe_round(match.play_round()) == (
        "You: Rock  |  Computer: Scissors\nRock blunts Scissors. Winner: You."
    )

    a_in.submit(Move.PAPER)
    b_in.submit(Move.PAPER)
    assert describe_round(match.play_round()).endswith("Draw.")

    assert describe_outcome(match) == (
        "Match winner: You. Final score: You 1 - 0 Computer (draws: 1)"
    )
