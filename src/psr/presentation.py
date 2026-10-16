"""Human-readable text for game events, shared by every front end."""

from psr.game import Match, RoundResult


def describe_round(result: RoundResult) -> str:
    first, second = result.first, result.second
    shown = f"{first.player.name}: {first.move.label}  |  {second.player.name}: {second.move.label}"
    if result.rule is None or result.winner is None:
        return f"{shown}\nDraw."
    return f"{shown}\n{result.rule.describe()}. Winner: {result.winner.name}."


def describe_score(match: Match) -> str:
    first, second = match.players
    board = match.scoreboard
    return (
        f"{first.name} {board.wins(first)} - {board.wins(second)} {second.name}"
        f" (draws: {board.draws})"
    )


def describe_outcome(match: Match) -> str:
    leader = match.scoreboard.leader()
    verdict = "The match is a draw." if leader is None else f"Match winner: {leader.name}."
    return f"{verdict} Final score: {describe_score(match)}"
