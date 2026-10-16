# Paper Scissors Rock

Play *n* rounds against the computer or against a friend online. Every rule,
decision and piece of scoring lives in one Python package. Three front ends use it:

- **Console**: `uv run psr`
- **Browser vs computer**: the same Python modules run in the page via [Pyodide](https://pyodide.org);
  you throw at the webcam.
- **Browser vs friend**: a FastAPI WebSocket server runs the match with the same `Match`
  class. Players throw their hand at the webcam; MediaPipe reads the gesture in the browser.

## Running

```sh
uv sync                     # Python 3.12+, dev tools
uv run psr                  # asks how many rounds
uv run psr --rounds 5       # or pass them in; --seed N makes the computer reproducible

uv run python scripts/build_web.py     # build the site into dist/
uv run psr-server --port 8000          # site + WebSocket at http://localhost:8000
uv run psr-server --redis redis://localhost:6379/0   # shared state, run as many as you like
```

On a public host, put the server behind HTTPS (e.g. a reverse proxy that forwards
WebSocket upgrades to `/ws`). Browsers only allow the camera on `https://` or
`localhost`, and the page connects with `wss://` when served over HTTPS.

## Testing

```sh
uv run pytest                               # Python: 118 tests (+9 need real Redis), ~5 s
node --test web/tests/*.test.js             # browser logic: 39 tests, no dependencies
uv run ruff check . && uv run ruff format --check . && uv run mypy   # lint + strict types

uv run pytest --cov=psr --cov=scripts --cov-report=term-missing     # 97% line coverage
PSR_TEST_REDIS_URL=redis://localhost:6379/15 uv run pytest          # also run against real Redis
```

The code is split so that logic never depends on I/O, clocks or the DOM, and the
I/O-bound parts take their dependencies as arguments:

| Seam | How it is made testable |
|---|---|
| Room rules (`server/engine.py`) | Pure `(state, command, now) -> outcome`; tests drive a fake clock and fire timers by advancing it, so no test sleeps |
| Storage, pub/sub, timers (`server/ports.py`) | Three protocols with in-memory and Redis implementations; one contract suite runs against both |
| Room service (`server/service.py`) | Takes a backend and a clock; tests inject a store that loses races on purpose |
| App (`server/app.py`) | `create_app(backend=…, redis=…, timing=…, clock=…)`; two apps share one fake Redis to play a match across instances |
| CLI (`cli.py`) | `main(argv, read, write)` with injected input/output |
| Browser logic (`web/gesture.js`, `web/views.js`) | Pure modules: gesture classification, debounce and "held steady" timing with `now` passed in, and the mapping from server messages to what the board shows |
| Scripts | `build(web, package, dist, fetch)`, `fetch_models(vendor, files, open_url)`, `load_test.run(url, …)` |

| Test file | Covers |
|---|---|
| `test_rules.py`, `test_game.py`, `test_presentation.py` | Rule table validation, rounds, scoring, choosers (incl. the computer committing first), text |
| `test_cli.py`, `test_web.py` | Console game end to end with fake I/O; the Pyodide session adapter |
| `test_engine.py` | Every room rule: hidden moves and photos, latest move counts, deadline and grace, replay/abandon, rematch, leave, disconnect/resume, stale timers |
| `test_backends.py` | Store compare-and-set, pub/sub routing, timer leases, presence expiry, room directory, stats counters, for memory, fakeredis and (optionally) Redis |
| `test_directory.py` | Which rooms are listed (open, live, private, finished) and their score |
| `test_service.py` | Two instances sharing a room, timer takeover after a crash, retry on conflict, giving up under contention |
| `test_server_app.py` | Real WebSockets: full match, a match split across two instances, photos, online count across instances, matches played, resume, leave, rematch, errors, health checks |
| `test_scripts.py` | Site build, model download (incl. interrupted downloads), and the load test playing real matches against a live server |
| `web/tests/*.test.js` | Gesture classification and fallback, debounce, hold detection, reveal/score/match-result views from each seat, room list wording, countdown, reconnect backoff, sound definitions and mute |

Not automated: the camera itself and the DOM. Those were checked in headless
Chrome with a fake camera fed a hand photo (`--use-file-for-fake-video-capture`).

## Versus the computer

Each round the computer commits its move first (`CommittedChooser`), before
yours exists, and the page only shows 🔒. A 5-second countdown follows, during
which your move tracks the camera live (or your latest tap). Whatever is showing
at zero is played, your camera frame freezes, and the computer's move is revealed. If nothing was read the
round replays and the computer keeps its committed move.

## Online match

1. One player creates a room and shares the link (`/?room=K7QX`); the other joins.
2. Each round the server starts a 5-second countdown. Both players see their own
   camera; each browser streams its current move whenever the reading changes.
3. The server only tells the opponent *that* a move exists (✓), never which.
4. At zero each browser grabs one camera frame (320 px JPEG, mirrored like the
   preview) and sends it with the final move.
5. At the server's deadline (countdown + 1 s grace) it takes each player's latest
   move, judges the round with the core `Match`, and sends both moves and both
   photos at once, so each player sees the other as they were at zero.
   Late moves are rejected; if someone showed nothing the round replays (twice max).
6. A dropped player keeps their seat for 20 s and the client resumes automatically.

The homepage lists **open lobbies** (one player waiting, with a Join button) and
**live matches** (names, round and score), from `GET /api/rooms`. Rooms are public
by default; untick "List in public lobby" to make one joinable by code only. The
service updates a small shared directory of room summaries whenever a room
changes and removes it when the room closes.

Sound effects (countdown ticks, the throw, round and match results, an opponent
joining) are synthesized with the Web Audio API, so there are no audio files; the
header button mutes them.

Photos only ever go to the opponent in the same room. The server keeps them in
the room's state until the next round starts and stores them nowhere else; the
on-screen prompt says a photo is taken at zero. Without a camera the reveal just
shows the move.

## Scaling

```
 players ─ WS ─► Traefik ─► app × N (stateless) ─► Redis
                                                   ├ room:{code}  state, compare-and-set
                                                   ├ events:*     pub/sub fan-out
                                                   ├ timers       leased sorted set
                                                   ├ online:{app} expiring player count
                                                   ├ rooms        public room summaries
                                                   └ stats        lifetime match counters
```

- `server/engine.py` is the room's rules as a pure function `(state, command, now)
  -> (state, events, timers)`: no I/O, unit-tested with a fake clock.
- `server/service.py` loads a room, applies a command and saves it only if the
  version is unchanged, retrying on conflict, so any instance can handle any player.
- Round deadlines live in a Redis sorted set. Claiming a timer leases it; if the
  instance dies, the timer comes due again and another instance fires it.
- The header's "N players online · M matches played" comes from `GET /api/stats`.
  Online matches are counted by the server right after the final round commits
  (so exactly once); a finished game against the computer reports itself once
  over its "playing" socket. Totals live in a Redis hash, and Redis runs with an
  append-only file on a volume so they survive restarts.
- The online count: each instance
  keeps an expiring count of its players in Redis and the endpoint sums them, so
  a crashed instance drops out of the total within 15 s. Players count while in
  a room, or while playing the computer: that game runs in the browser, so it
  keeps one WebSocket open saying `{"type": "playing"}`.
- Without `PSR_REDIS_URL` the same code runs in memory as a single instance.

Measured on a laptop, one in-memory instance: 1,500 concurrent matches (3,000
sockets), 0 errors, reveal lag p50 26 ms / p95 50 ms after the deadline
(`scripts/load_test.py`).

## Deploying

```sh
docker-compose up --build --scale app=3            # local: Traefik on :8080
PSR_DOMAIN=psr.example.com scripts/deploy.sh ubuntu@HOST   # HTTPS via Let's Encrypt
```

The host needs ports 80/443 open and a DNS A record pointing at it (DNS only,
not proxied, so Let's Encrypt can reach Traefik).

## Design

| Module | Responsibility |
|---|---|
| `moves.py` | `Move` enum: the symbols a hand can show |
| `rules.py` | `Rule` (winner, loser, verb) and `Rules`, a checked, data-driven rule table |
| `choosers.py` | `MoveChooser` protocol: `RandomChooser` (seedable), `PresetChooser` (event-driven input) |
| `players.py` | `Player`: a name plus a chooser |
| `game.py` | `Match` (runs *n* rounds), `RoundResult`, `Scoreboard` |
| `presentation.py` | Text descriptions shared by all front ends |
| `cli.py` / `web.py` | Adapters for the console and the in-browser game |
| `server/` | Protocol (Pydantic), pure room engine, service, Redis/memory backends, FastAPI app |

### Trade-offs

- **Rules are data, not `if` chains.** `Rules` checks that its table is
  complete and has no conflicts. Adding Lizard/Spock means adding enum members
  and rows to a table; `Match` stays the same.
- **Move selection is a strategy (`MoveChooser`).** Human and computer players
  are the same `Player` type with different choosers, so a smarter computer
  (e.g. one that adapts to how often the human plays each move) or a second
  human just needs a new chooser.
- **Pull model with an event-driven adapter.** `Match.play_round()` asks each
  player for a move. The console blocks on `input()`. The browser cannot block,
  so `PresetChooser` holds the move the user clicked and then the round runs.
  Both front ends go through the same code path.
- **I/O is injected.** The CLI takes `read`/`write` functions, so tests can run
  whole games without patching stdin/stdout.
- **Two players only.** A `Match` is for exactly two players, as the game is.
  Supporting more would mean changing how a round is judged, and nothing here
  needs that yet.
