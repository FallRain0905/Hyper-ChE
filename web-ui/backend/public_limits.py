"""Atomic Redis budgets for anonymous model queries, including streaming leases."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)
_client = None
_LEASE_SECONDS = 180

_ACQUIRE = """
local now, token = tonumber(ARGV[1]), ARGV[2]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[5], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {1, math.max(1, math.ceil(tonumber(first[2]) + 60 - now))}
end
if tonumber(redis.call('GET', KEYS[2]) or '0') >= tonumber(ARGV[4]) then return {2, tonumber(ARGV[8])} end
if tonumber(redis.call('GET', KEYS[3]) or '0') >= tonumber(ARGV[5]) then return {3, tonumber(ARGV[8])} end
if redis.call('ZCARD', KEYS[4]) >= tonumber(ARGV[6]) then return {4, 10} end
if redis.call('ZCARD', KEYS[5]) >= tonumber(ARGV[7]) then return {5, 10} end
redis.call('ZADD', KEYS[1], now, token)
redis.call('EXPIRE', KEYS[1], 120)
for i = 2, 3 do
  redis.call('INCR', KEYS[i])
  redis.call('EXPIRE', KEYS[i], tonumber(ARGV[8]))
end
for i = 4, 5 do
  redis.call('ZADD', KEYS[i], now + tonumber(ARGV[9]), token)
  redis.call('EXPIRE', KEYS[i], tonumber(ARGV[9]) + 60)
end
return {0, 0}
"""
_RENEW = """
for i = 1, 2 do
  if not redis.call('ZSCORE', KEYS[i], ARGV[1]) then return 0 end
end
for i = 1, 2 do
  redis.call('ZADD', KEYS[i], tonumber(ARGV[2]) + tonumber(ARGV[3]), ARGV[1])
  redis.call('EXPIRE', KEYS[i], tonumber(ARGV[3]) + 60)
end
return 1
"""
_RELEASE = """
for i = 1, 2 do redis.call('ZREM', KEYS[i], ARGV[1]) end
return 1
"""


def _limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def client_ip(request: Request) -> str:
    """Trust only the explicitly configured reverse-proxy peers, not client headers."""
    peer = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return "unknown"
    trusted = os.getenv("HYPERCHE_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
    networks = []
    for value in trusted.split(","):
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError:
            continue
    if any(address in network for network in networks):
        forwarded = request.headers.get("x-real-ip", "").strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return str(address)


def _redis():
    global _client
    if _client is None:
        from redis.asyncio import Redis
        _client = Redis.from_url(
            os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            socket_connect_timeout=3, socket_timeout=3, decode_responses=True,
        )
    return _client


def _keys(ip: str, now: float) -> tuple[list[str], int]:
    secret = os.getenv("APP_SECRET_KEY", "local-development-public-limits").encode()
    identity = hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()[:32]
    moment = datetime.fromtimestamp(now, ZoneInfo("Asia/Taipei"))
    midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    remaining = max(1, int(midnight.timestamp() - now) + 1)
    prefix = "hyperche:public:{query}"
    day = moment.strftime("%Y%m%d")
    return [f"{prefix}:minute:{identity}", f"{prefix}:day:{day}:{identity}",
            f"{prefix}:day:{day}:global", f"{prefix}:active:{identity}",
            f"{prefix}:active:global"], remaining


class PublicQueryLease:
    def __init__(self):
        self.owner = asyncio.current_task()

    def bind_owner(self):
        """SSE moves from its endpoint task into the response generator task."""
        self.owner = asyncio.current_task()


@asynccontextmanager
async def public_query_slot(request: Request):
    """Reserve once before response headers, and release after JSON/SSE completion.

    Missing Redis fails closed. Accepted attempts consume daily request budgets,
    even if a provider later fails. Expiring, renewed leases survive worker crashes.
    """
    now = time.time()
    keys, remaining = _keys(client_ip(request), now)
    token = uuid.uuid4().hex
    try:
        redis = _redis()
        result = await redis.eval(_ACQUIRE, len(keys), *keys, now, token,
            _limit("HYPERCHE_PUBLIC_IP_PER_MINUTE", 2),
            _limit("HYPERCHE_PUBLIC_IP_PER_DAY", 20),
            _limit("HYPERCHE_PUBLIC_GLOBAL_PER_DAY", 100),
            _limit("HYPERCHE_PUBLIC_IP_CONCURRENCY", 1),
            _limit("HYPERCHE_PUBLIC_GLOBAL_CONCURRENCY", 2), remaining, _LEASE_SECONDS)
    except Exception as exc:
        logger.warning("Public query limiter unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, detail="公开体验暂时不可用，请稍后再试。") from None
    code, retry = map(int, result)
    if code:
        message = "体验请求过于频繁，请稍后再试。" if code in (1, 4, 5) else "今日公开体验额度已用完，请明日再试。"
        raise HTTPException(429, detail=message, headers={"Retry-After": str(retry)})

    lease = PublicQueryLease()

    async def renew():
        while True:
            await asyncio.sleep(45)
            try:
                alive = await redis.eval(_RENEW, 2, *keys[3:], token, time.time(), _LEASE_SECONDS)
                if not alive:
                    raise RuntimeError("public lease expired")
            except Exception:
                logger.warning("Public query lease lost; stopping its model request")
                if lease.owner:
                    lease.owner.cancel()
                return

    heartbeat = asyncio.create_task(renew())
    try:
        yield lease
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        try:
            await asyncio.shield(redis.eval(_RELEASE, 2, *keys[3:], token))
        except Exception:
            logger.warning("Public query lease release failed; expiration will recover it")
