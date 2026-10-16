import argparse
import random
from collections.abc import Callable, Sequence

from psr.choosers import RandomChooser
from psr.game import Match
from psr.moves import Move
from psr.players import Player
from psr.presentation import describe_outcome, describe_round, describe_score
from psr.rules import CLASSIC_RULES

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def parse_move(text: str, moves: Sequence[Move]) -> Move | None:
    """Match full names or any unambiguous prefix, e.g. 'r', 'pap'."""
    text = text.strip().lower()
    if not text:
        return None
    candidates = [m for m in moves if m.value.startswith(text)]
    return candidates[0] if len(candidates) == 1 else None


def parse_rounds(text: str) -> int | None:
    try:
        rounds = int(text.strip())
    except ValueError:
        return None
    return rounds if rounds >= 1 else None


class ConsoleChooser:
    """Asks a human for a move on the console until the input is valid."""

    def __init__(self, read: InputFn = input, write: OutputFn = print) -> None:
        self._read = read
        self._write = write

    def choose(self, moves: Sequence[Move]) -> Move:
        options = "/".join(m.value for m in moves)
        while True:
            move = parse_move(self._read(f"Your move ({options}): "), moves)
            if move is not None:
                return move
            self._write(f"Please enter one of: {options}")


def ask_rounds(read: InputFn, write: OutputFn) -> int:
    while True:
        rounds = parse_rounds(read("How many rounds? "))
        if rounds is not None:
            return rounds
        write("Please enter a whole number of at least 1.")


def run(match: Match, write: OutputFn) -> None:
    while not match.is_over:
        write(f"\n--- Round {match.rounds_played + 1} of {match.rounds} ---")
        write(describe_round(match.play_round()))
        write(describe_score(match))
    write(f"\n{describe_outcome(match)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play Paper Scissors Rock against the computer.")
    parser.add_argument("-n", "--rounds", type=int, help="number of rounds (asked if omitted)")
    parser.add_argument("--seed", type=int, help="seed the computer for reproducible games")
    return parser


def main(argv: Sequence[str] | None = None, read: InputFn = input, write: OutputFn = print) -> int:
    args = build_parser().parse_args(argv)
    if args.rounds is not None and args.rounds < 1:
        write("--rounds must be at least 1.")
        return 2
    try:
        rounds = args.rounds or ask_rounds(read, write)
        human = Player("You", ConsoleChooser(read, write))
        computer = Player("Computer", RandomChooser(random.Random(args.seed)))
        run(Match(CLASSIC_RULES, human, computer, rounds), write)
    except (EOFError, KeyboardInterrupt):
        write("\nGoodbye!")
        return 1
    return 0
