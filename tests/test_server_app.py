"""The app over real WebSockets: single instance, reconnects, and two instances sharing Redis."""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from psr.server.app import app_from_env, create_app, run_timers
from psr.server.engine import Timing

FAST = Timing(countdown=0.2, grace=0.0, result_pause=0.05, reconnect_grace=5.0)


def receive_until(ws: WebSocketTestSession, kind: str, limit: int = 30) -> dict[str, Any]:
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"no {kind} message")


@contextmanager
def players(alice_app: FastAPI, bob_app: FastAPI) -> Iterator[tuple[Any, Any]]:
    with ExitStack() as stack:
        alice_client = stack.enter_context(TestClient(alice_app))
        bob_client = (
            alice_client if bob_app is alice_app else stack.enter_context(TestClient(bob_app))
        )
        alice = stack.enter_context(alice_client.websocket_connect("/ws"))
        bob = stack.enter_context(bob_client.websocket_connect("/ws"))
        yield alice, bob


def play_one_round_match(alice: Any, bob: Any) -> dict[str, Any]:
    alice.send_json({"type": "create", "name": "Alice", "rounds": 1})
    code = receive_until(alice, "joined")["room"]
    bob.send_json({"type": "join", "name": "Bob", "room": code.lower()})
    assert receive_until(bob, "joined")["seat"] == 1
    receive_until(alice, "round")
    receive_until(bob, "round")

    alice.send_json({"type": "move", "move": "rock"})
    assert receive_until(bob, "ready") == {"type": "ready", "seat": 0}
    alice.send_json({"type": "move", "move": "paper"})  # changed before the deadline
    bob.send_json({"type": "move", "move": "rock"})

    reveal = receive_until(bob, "reveal")
    assert receive_until(alice, "reveal") == reveal
    return reveal


def test_full_match_on_one_instance() -> None:
    app = create_app(timing=FAST, timer_poll=0.01)
    with players(app, app) as (alice, bob):
        reveal = play_one_round_match(alice, bob)
    assert reveal["moves"] == ["paper", "rock"]
    assert reveal["winner"] == 0
    assert reveal["is_over"]


def test_full_match_across_two_instances_sharing_redis() -> None:
    server = FakeServer()
    first = create_app(redis=FakeRedis(server=server), timing=FAST, timer_poll=0.01)
    second = create_app(redis=FakeRedis(server=server), timing=FAST, timer_poll=0.01)
    with players(first, second) as (alice, bob):
        reveal = play_one_round_match(alice, bob)
    assert reveal["moves"] == ["paper", "rock"]
    assert reveal["score"] == {"wins": [1, 0], "draws": 0}


def test_player_can_resume_their_seat_after_reconnecting() -> None:
    app = create_app(timing=Timing(countdown=30.0, grace=0.0), timer_poll=0.01)
    with TestClient(app) as client, client.websocket_connect("/ws") as alice:
        alice.send_json({"type": "create", "name": "Alice", "rounds": 3})
        joined = receive_until(alice, "joined")
        with client.websocket_connect("/ws") as bob:
            bob.send_json({"type": "join", "name": "Bob", "room": joined["room"]})
            bob_seat = receive_until(bob, "joined")
            bob.send_json({"type": "move", "move": "scissors"})
            receive_until(alice, "ready")
        assert receive_until(alice, "notice")["text"] == "Bob lost connection. Waiting…"

        with client.websocket_connect("/ws") as bob_again:
            resume = {"type": "resume", "room": joined["room"], "token": bob_seat["token"]}
            bob_again.send_json(resume)
            assert receive_until(bob_again, "joined")["seat"] == 1
            sync = receive_until(bob_again, "sync")
            assert sync["phase"] == "throwing"
            assert sync["your_move"] == "scissors"
            assert receive_until(alice, "notice")["text"] == "Bob reconnected."


def test_invalid_and_out_of_order_messages_get_errors() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        assert receive_until(ws, "error")["message"] == "Invalid message"
        ws.send_json({"type": "move", "move": "rock"})
        assert receive_until(ws, "error")["message"] == "Join a room first"
        ws.send_json({"type": "join", "name": "Zed", "room": "ZZZZ"})
        assert receive_until(ws, "error")["message"] == "No room with code ZZZZ"
        ws.send_json({"type": "resume", "room": "ZZZZ", "token": "x" * 16})
        assert receive_until(ws, "error")["message"] == "No room with code ZZZZ"


def test_health_check_reports_the_instance() -> None:
    with TestClient(create_app()) as client:
        body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["instance"]


def test_serves_static_site(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    with TestClient(create_app(static_dir=tmp_path)) as client:
        assert client.get("/").text == "<h1>hi</h1>"


def test_leaving_tells_the_other_player_and_frees_the_seat() -> None:
    app = create_app(timing=FAST, timer_poll=0.01)
    with players(app, app) as (alice, bob):
        alice.send_json({"type": "create", "name": "Alice", "rounds": 3})
        code = receive_until(alice, "joined")["room"]
        bob.send_json({"type": "join", "name": "Bob", "room": code})
        receive_until(bob, "round")

        bob.send_json({"type": "leave"})
        assert receive_until(alice, "notice")["text"] == "Bob left the room."
        assert receive_until(alice, "lobby")["players"] == ["Alice"]
        bob.send_json({"type": "move", "move": "rock"})
        assert receive_until(bob, "error")["message"] == "Join a room first"


def test_rematch_over_websockets() -> None:
    app = create_app(timing=FAST, timer_poll=0.01)
    with players(app, app) as (alice, bob):
        play_one_round_match(alice, bob)
        alice.send_json({"type": "rematch"})
        assert receive_until(bob, "rematch") == {"type": "rematch", "seat": 0}
        bob.send_json({"type": "rematch"})
        assert receive_until(alice, "round")["round"] == 1


def test_cannot_join_two_rooms_from_one_socket() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create", "name": "Alice", "rounds": 1})
        receive_until(ws, "joined")
        ws.send_json({"type": "create", "name": "Alice", "rounds": 1})
        assert receive_until(ws, "error")["message"] == "You are already in a room"


def test_app_from_env_uses_memory_and_serves_the_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("<h1>env</h1>")
    monkeypatch.delenv("PSR_REDIS_URL", raising=False)
    monkeypatch.setenv("PSR_STATIC_DIR", str(tmp_path))
    with TestClient(app_from_env()) as client:
        assert client.get("/").text == "<h1>env</h1>"
        assert client.get("/healthz").json()["status"] == "ok"


def test_health_check_fails_when_redis_is_down() -> None:
    class DeadRedis(FakeRedis):
        async def ping(self, **kwargs: object) -> bool:
            raise ConnectionError("down")

    with TestClient(create_app(redis=DeadRedis(server=FakeServer()))) as client:
        response = client.get("/healthz")
    assert response.status_code == 503


def test_timer_loop_survives_errors() -> None:
    class FlakyService:
        calls = 0

        async def fire_due_timers(self) -> int:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("redis blip")
            if self.calls >= 3:
                raise asyncio.CancelledError
            return 0

    service = FlakyService()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_timers(service, poll=0.001))  # type: ignore[arg-type]
    assert service.calls == 3


def test_reveal_carries_both_players_photos() -> None:
    app = create_app(timing=FAST, timer_poll=0.01)
    photo = "data:image/jpeg;base64,/9j/4AAQ"
    with players(app, app) as (alice, bob):
        alice.send_json({"type": "create", "name": "Alice", "rounds": 1})
        code = receive_until(alice, "joined")["room"]
        bob.send_json({"type": "join", "name": "Bob", "room": code})
        receive_until(alice, "round")
        alice.send_json({"type": "move", "move": "rock"})
        alice.send_json({"type": "snapshot", "image": photo})
        bob.send_json({"type": "move", "move": "rock"})
        assert receive_until(bob, "reveal")["snapshots"] == [photo, None]


def test_snapshots_must_be_small_jpeg_data_urls() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        for image in (
            "data:image/png;base64,AAAA",
            "javascript:alert(1)",
            "data:image/jpeg;base64," + "A" * 200_000,
        ):
            ws.send_json({"type": "snapshot", "image": image})
            assert receive_until(ws, "error")["message"] == "Invalid message"


def test_online_count_follows_seated_players_across_instances() -> None:
    server = FakeServer()
    first = create_app(redis=FakeRedis(server=server), timing=FAST, instance="app-1")
    second = create_app(redis=FakeRedis(server=server), timing=FAST, instance="app-2")
    with TestClient(first) as one, TestClient(second) as two:
        assert one.get("/api/online").json() == {"players": 0}
        with one.websocket_connect("/ws") as alice, two.websocket_connect("/ws") as bob:
            alice.send_json({"type": "create", "name": "Alice", "rounds": 1})
            code = receive_until(alice, "joined")["room"]
            assert two.get("/api/online").json() == {"players": 1}
            bob.send_json({"type": "join", "name": "Bob", "room": code})
            receive_until(bob, "joined")
            assert one.get("/api/online").json() == {"players": 2}

            bob.send_json({"type": "leave"})
            receive_until(alice, "notice")
            assert one.get("/api/online").json() == {"players": 1}
        assert two.get("/api/online").json() == {"players": 0}


def test_failed_join_is_not_counted() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "join", "name": "Zed", "room": "ZZZZ"})
        receive_until(ws, "error")
        assert client.get("/api/online").json() == {"players": 0}


def test_players_vs_the_computer_are_counted_while_connected() -> None:
    with TestClient(create_app(timing=FAST)) as client:
        with client.websocket_connect("/ws") as solo:
            solo.send_json({"type": "playing"})
            solo.send_json({"type": "playing"})  # repeated announcements count once
            solo.send_json({"type": "move", "move": "rock"})  # round-trip so both are handled
            receive_until(solo, "error")
            assert client.get("/api/online").json() == {"players": 1}
        assert client.get("/api/online").json() == {"players": 0}


def test_a_solo_player_who_joins_a_room_is_counted_once() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "playing"})
        ws.send_json({"type": "create", "name": "Alice", "rounds": 1})
        receive_until(ws, "joined")
        assert client.get("/api/online").json() == {"players": 1}


def test_site_files_are_revalidated_but_the_model_is_cached(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "model.task").write_bytes(b"weights")
    with TestClient(create_app(static_dir=tmp_path)) as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
        assert client.get("/api/online").headers["cache-control"] == "no-cache"
        assert "max-age=86400" in client.get("/vendor/model.task").headers["cache-control"]


def test_homepage_lists_open_lobbies_then_live_matches_across_instances() -> None:
    server = FakeServer()
    first = create_app(redis=FakeRedis(server=server), timing=FAST, timer_poll=0.01)
    second = create_app(redis=FakeRedis(server=server), timing=FAST, timer_poll=0.01)
    with TestClient(first) as one, TestClient(second) as two:
        assert two.get("/api/rooms").json() == {"open": [], "live": []}
        with one.websocket_connect("/ws") as alice, two.websocket_connect("/ws") as bob:
            alice.send_json({"type": "create", "name": "Alice", "rounds": 3})
            code = receive_until(alice, "joined")["room"]
            assert two.get("/api/rooms").json() == {
                "open": [
                    {
                        "code": code,
                        "status": "open",
                        "players": ["Alice"],
                        "rounds": 3,
                        "round": 0,
                        "wins": [0, 0],
                        "draws": 0,
                    }
                ],
                "live": [],
            }

            bob.send_json({"type": "join", "name": "Bob", "room": code})
            receive_until(alice, "round")
            listing = one.get("/api/rooms").json()
            assert listing["open"] == []
            assert listing["live"][0]["players"] == ["Alice", "Bob"]
            assert listing["live"][0]["round"] == 1

            alice.send_json({"type": "move", "move": "rock"})
            bob.send_json({"type": "move", "move": "scissors"})
            receive_until(alice, "reveal")
            assert one.get("/api/rooms").json()["live"][0]["wins"] == [1, 0]

            alice.send_json({"type": "leave"})
            bob.send_json({"type": "leave"})
            receive_until(bob, "lobby")
        assert two.get("/api/rooms").json() == {"open": [], "live": []}


def test_private_rooms_are_not_listed() -> None:
    with TestClient(create_app(timing=FAST)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create", "name": "Alice", "rounds": 1, "public": False})
        code = receive_until(ws, "joined")["room"]
        assert client.get("/api/rooms").json() == {"open": [], "live": []}
        with client.websocket_connect("/ws") as bob:  # still joinable by code
            bob.send_json({"type": "join", "name": "Bob", "room": code})
            assert receive_until(bob, "joined")["seat"] == 1
