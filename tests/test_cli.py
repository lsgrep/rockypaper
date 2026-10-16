import pytest

from psr.cli import main, parse_move, parse_rounds
from psr.moves import Move
from psr.rules import CLASSIC_RULES


class FakeConsole:
    def __init__(self, *inputs: str) -> None:
        self._inputs = list(inputs)
        self.lines: list[str] = []

    def read(self, prompt: str) -> str:
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def write(self, text: str) -> None:
        self.lines.append(text)

    @property
    def output(self) -> str:
        return "\n".join(self.lines)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("rock", Move.ROCK),
        ("R", Move.ROCK),
        ("  pap ", Move.PAPER),
        ("s", Move.SCISSORS),
        ("", None),
        ("lizard", None),
    ],
)
def test_parse_move(text: str, expected: Move | None) -> None:
    assert parse_move(text, CLASSIC_RULES.moves) is expected


@pytest.mark.parametrize(("text", "expected"), [("3", 3), (" 1 ", 1), ("0", None), ("x", None)])
def test_parse_rounds(text: str, expected: int | None) -> None:
    assert parse_rounds(text) == expected


def test_plays_n_rounds_then_exits() -> None:
    console = FakeConsole("rock", "paper", "scissors")
    code = main(["--rounds", "3", "--seed", "1"], console.read, console.write)
    assert code == 0
    assert "Round 3 of 3" in console.output
    assert "Round 4" not in console.output
    assert "Final score" in console.output


def test_asks_for_rounds_and_reprompts_on_bad_input() -> None:
    console = FakeConsole("zero", "1", "banana", "r")
    assert main(["--seed", "1"], console.read, console.write) == 0
    assert "Please enter a whole number" in console.output
    assert "Please enter one of: rock/paper/scissors" in console.output
    assert "Round 1 of 1" in console.output


def test_end_of_input_exits_cleanly() -> None:
    console = FakeConsole()
    assert main(["--rounds", "2"], console.read, console.write) == 1
    assert "Goodbye" in console.output


def test_rejects_non_positive_rounds_flag() -> None:
    console = FakeConsole()
    assert main(["--rounds", "0"], console.read, console.write) == 2
