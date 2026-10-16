"""Redis implementations of the ports, so any number of server instances share rooms.

- Room state: a hash {v: version, s: JSON}, written by a Lua compare-and-set.
- Events: one pattern subscription per instance; handlers filter by room.
- Presence: one expiring counter key per instance, summed on read.
- Timers: a sorted set scored by due time; claiming re-scores a timer to now + lease
  in one Lua call, so exactly one instance runs it, and it reappears if that one dies.
"""

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from typing import Any

from redis.asyncio import Redis

from psr.server.ports import Backend, Envelope, Handler
from psr.server.state import RoomState, Timer

log = logging.getLogger(__name__)

ROOM_PREFIX = "psr:room:"
EVENTS_PREFIX = "psr:events:"
TIMERS_KEY = "psr:timers"
PRESENCE_PREFIX = "psr:online:"
ROOM_TTL_SECONDS = 6 * 60 * 60  # idle rooms disappear on their own

SAVE_IF_VERSION = """
local current = redis.call('HGET', KEYS[1], 'v')
if ARGV[1] == '' then
  if current then return 0 end
elseif current ~= ARGV[1] then
  return 0
end
redis.call('HSET', KEYS[1], 'v', ARGV[2], 's', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""

DELETE_IF_VERSION = """
if redis.call('HGET', KEYS[1], 'v') == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""

CLAIM_DUE = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[3])
for _, member in ipairs(due) do
  redis.call('ZADD', KEYS[1], ARGV[2], member)
end
return due
"""


class RedisRoomStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._save = redis.register_script(SAVE_IF_VERSION)
        self._delete = redis.register_script(DELETE_IF_VERSION)

    async def load(self, code: str) -> RoomState | None:
        raw = await self._redis.hget(ROOM_PREFIX + code, "s")
        return None if raw is None else RoomState.model_validate_json(raw)

    async def create(self, state: RoomState) -> bool:
        return await self._write(state, expected="")

    async def save(self, state: RoomState, expected_version: int) -> bool:
        return await self._write(state, expected=str(expected_version))

    async def delete(self, code: str, expected_version: int) -> bool:
        return bool(await self._delete(keys=[ROOM_PREFIX + code], args=[str(expected_version)]))

    async def _write(self, state: RoomState, expected: str) -> bool:
        args: list[str | int] = [
            expected,
            str(state.version),
            state.model_dump_json(),
            ROOM_TTL_SECONDS,
        ]
        return bool(await self._save(keys=[ROOM_PREFIX + state.code], args=args))


class _RedisSubscription:
    def __init__(self, bus: "RedisEventBus", room: str, handler: Handler) -> None:
        self._bus = bus
        self._room = room
        self._handler = handler

    async def close(self) -> None:
        self._bus.remove(self._room, self._handler)


class RedisEventBus:
    """Publishes to `psr:events:{room}`; one listener per instance dispatches locally."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._listener: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    async def start(self) -> None:
        if self._listener is None:
            self._listener = asyncio.create_task(self._listen())
            await self._ready.wait()

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None

    async def publish(self, room: str, envelope: Envelope) -> None:
        data = json.dumps({"to": envelope.to, "payload": envelope.payload})
        await self._redis.publish(EVENTS_PREFIX + room, data)

    async def subscribe(self, room: str, handler: Handler) -> _RedisSubscription:
        await self.start()
        self._handlers[room].append(handler)
        return _RedisSubscription(self, room, handler)

    def remove(self, room: str, handler: Handler) -> None:
        handlers = self._handlers.get(room, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(room, None)

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(EVENTS_PREFIX + "*")
        self._ready.set()
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    await self._dispatch(message)
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def _dispatch(self, message: dict[str, Any]) -> None:
        channel = _text(message["channel"])
        handlers = self._handlers.get(channel.removeprefix(EVENTS_PREFIX), [])
        if not handlers:
            return
        data = json.loads(_text(message["data"]))
        envelope = Envelope(to=data["to"], payload=data["payload"])
        for handler in list(handlers):
            try:
                await handler(envelope)
            except Exception:
                log.exception("Event handler failed")


class RedisTimerQueue:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._claim = redis.register_script(CLAIM_DUE)

    async def schedule(self, timer: Timer) -> None:
        await self._redis.zadd(TIMERS_KEY, {_encode(timer): timer.at})

    async def claim_due(self, now: float, lease: float, limit: int) -> list[Timer]:
        members = await self._claim(keys=[TIMERS_KEY], args=[now, now + lease, limit])
        return [_decode(_text(m)) for m in members]

    async def complete(self, timer: Timer) -> None:
        await self._redis.zrem(TIMERS_KEY, _encode(timer))


class RedisPresenceBoard:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def report(self, instance: str, count: int, ttl: float) -> None:
        await self._redis.set(PRESENCE_PREFIX + instance, count, px=max(1, round(ttl * 1000)))

    async def total(self) -> int:
        keys = [key async for key in self._redis.scan_iter(match=PRESENCE_PREFIX + "*")]
        if not keys:
            return 0
        return sum(int(value) for value in await self._redis.mget(keys) if value is not None)


def _encode(timer: Timer) -> str:
    return json.dumps([timer.room, timer.name, timer.token, timer.at])


def _decode(member: str) -> Timer:
    room, name, token, at = json.loads(member)
    return Timer(room, name, int(token), float(at))


def _text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def redis_backend(redis: Redis) -> tuple[Backend, RedisEventBus]:
    bus = RedisEventBus(redis)
    backend = Backend(RedisRoomStore(redis), bus, RedisTimerQueue(redis), RedisPresenceBoard(redis))
    return backend, bus
