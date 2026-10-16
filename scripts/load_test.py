"""Simulate many concurrent matches against a running server and report reveal latency.

    uv run python scripts/load_test.py --url ws://localhost:8080/ws --rooms 200 --rounds 2

Each room is two WebSocket clients that change their move a few times per round.
"Reveal lag" is how long after the round's deadline (countdown + grace) the reveal
arrived: it measures timer pickup, Redis round-trips and fan-out under load.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

MOVES = ["rock", "paper", "scissors"]
GRACE_SECONDS = 0.5


@dataclass
class Stats:
    lags: list[float] = field(default_factory=list)
    matches: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0


async def receive(ws: Any, kind: str, timeout: float = 30.0) -> dict[str, Any]:
    async with asyncio.timeout(timeout):
        while True:
            message: dict[str, Any] = json.loads(await ws.recv())
            if message["type"] == kind:
                return message
            if message["type"] == "error":
                raise RuntimeError(message["message"])


async def play_rounds(ws: Any, rounds: int, stats: Stats, measure: bool) -> None:
    for _ in range(rounds):
        started = await receive(ws, "round")
        received_at = time.monotonic()
        countdown = started["countdown_ms"] / 1000
        for _ in range(random.randint(1, 3)):  # players change their mind
            await asyncio.sleep(random.uniform(0.2, countdown / 3))
            await ws.send(json.dumps({"type": "move", "move": random.choice(MOVES)}))
        await receive(ws, "reveal")
        if measure:
            stats.lags.append(time.monotonic() - received_at - countdown - GRACE_SECONDS)


async def match(url: str, rounds: int, stats: Stats) -> None:
    async with websockets.connect(url) as host, websockets.connect(url) as guest:
        await host.send(json.dumps({"type": "create", "name": "Host", "rounds": rounds}))
        code = (await receive(host, "joined"))["room"]
        await guest.send(json.dumps({"type": "join", "name": "Guest", "room": code}))
        await receive(guest, "joined")
        await asyncio.gather(
            play_rounds(host, rounds, stats, measure=True),
            play_rounds(guest, rounds, stats, measure=False),
        )
    stats.matches += 1


async def guarded(url: str, rounds: int, stats: Stats, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await match(url, rounds, stats)
    except Exception as error:
        stats.errors.append(f"{type(error).__name__}: {error}")


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


async def run(url: str, rooms: int, rounds: int, ramp: float) -> Stats:
    """Play `rooms` concurrent matches, spreading their starts over `ramp` seconds."""
    stats = Stats()
    started = time.monotonic()
    delays = [ramp * i / max(rooms, 1) for i in range(rooms)]
    await asyncio.gather(*(guarded(url, rounds, stats, d) for d in delays))
    stats.elapsed = time.monotonic() - started
    return stats


def report(stats: Stats, rooms: int, rounds: int) -> str:
    lines = [
        f"rooms: {rooms} ({rooms * 2} sockets), rounds each: {rounds}",
        f"completed matches: {stats.matches}, errors: {len(stats.errors)}, "
        f"took {stats.elapsed:.1f}s",
    ]
    if stats.lags:
        lags_ms = [lag * 1000 for lag in stats.lags]
        lines.append(
            "reveal lag ms: "
            f"p50={statistics.median(lags_ms):.0f} p95={percentile(lags_ms, 95):.0f} "
            f"max={max(lags_ms):.0f}"
        )
    lines += [f"  error: {error}" for error in sorted(set(stats.errors))[:5]]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws")
    parser.add_argument("--rooms", type=int, default=50, help="concurrent matches")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--ramp", type=float, default=5.0, help="seconds to spread connects over")
    args = parser.parse_args()
    stats = await run(args.url, args.rooms, args.rounds, args.ramp)
    print(report(stats, args.rooms, args.rounds))


if __name__ == "__main__":
    asyncio.run(main())
