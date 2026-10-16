import pytest

from psr.game import MatchOverError
from psr.web import WebSession


def test_session_exposes_moves_and_plays_to_the_end() -> None:
    session = WebSession(rounds=2, seed=3)
    assert session.moves == ["rock", "paper", "scissors"]

    first = session.play("rock")
    assert first["round"] == 1
    assert first["human_move"] == "rock"
    assert first["outcome"] in {"win", "lose", "draw"}
    assert not first["is_over"]
    assert first["summary"] is None

    last = session.play("paper")
    assert last["is_over"]
    assert "Final score" in last["summary"]
    score = last["score"]
    assert score["human"] + score["computer"] + score["draws"] == 2

    with pytest.raises(MatchOverError):
        session.play("rock")


def test_session_rejects_unknown_move() -> None:
    with pytest.raises(ValueError):
        WebSession(rounds=1).play("lizard")


def test_computer_commits_before_the_human_moves() -> None:
    session = WebSession(rounds=1, seed=3)
    started = session.start_round()
    assert started == {"round": 1, "rounds": 1}

    committed = session._computer_chooser.committed  # white-box: fixed before play
    assert committed is not None
    assert session.start_round() == started  # replaying keeps the committed move
    assert session._computer_chooser.committed is committed

    result = session.play("rock")
    assert result["computer_move"] == committed.value


def test_play_commits_on_demand_when_round_not_started() -> None:
    result = WebSession(rounds=1, seed=3).play("paper")
    assert result["round"] == 1
