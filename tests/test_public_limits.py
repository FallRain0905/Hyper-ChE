"""Public quotas execute the actual Redis Lua scripts using fakeredis/lupa."""
import asyncio
import importlib.util
from pathlib import Path

import fakeredis.aioredis
import pytest
from fastapi import HTTPException
from starlette.requests import Request

PATH = Path(__file__).resolve().parents[1] / "web-ui/backend/public_limits.py"
SPEC = importlib.util.spec_from_file_location("public_limits", PATH)
limits = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(limits)


def request(ip, headers=None):
    return Request({"type": "http", "client": (ip, 1234),
                    "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()]})


def test_untrusted_client_cannot_spoof_ip(monkeypatch):
    monkeypatch.setenv("HYPERCHE_TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    assert limits.client_ip(request("198.51.100.4", {"x-real-ip": "203.0.113.1"})) == "198.51.100.4"
    assert limits.client_ip(request("127.0.0.1", {"x-real-ip": "203.0.113.1"})) == "203.0.113.1"
    assert limits.client_ip(request("127.0.0.1", {"x-real-ip": "bad"})) == "127.0.0.1"


def test_budgets_and_stream_slot_release(monkeypatch):
    async def check():
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        monkeypatch.setattr(limits, "_client", redis)
        async with limits.public_query_slot(request("198.51.100.4")):
            with pytest.raises(HTTPException) as error:
                async with limits.public_query_slot(request("198.51.100.4")):
                    pass
            assert error.value.status_code == 429
        async with limits.public_query_slot(request("198.51.100.4")):
            pass
        with pytest.raises(HTTPException) as error:
            async with limits.public_query_slot(request("198.51.100.4")):
                pass
        assert error.value.status_code == 429
        assert int(error.value.headers["Retry-After"]) > 0
        keys, _ = limits._keys("198.51.100.4", limits.time.time())
        assert await redis.zcard(keys[3]) == 0
        assert await redis.get(keys[1]) == "2"
        await redis.aclose()
    asyncio.run(check())


def test_global_budget_and_cancellation(monkeypatch):
    monkeypatch.setenv("HYPERCHE_PUBLIC_GLOBAL_PER_DAY", "2")
    async def check():
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        monkeypatch.setattr(limits, "_client", redis)
        with pytest.raises(asyncio.CancelledError):
            async with limits.public_query_slot(request("198.51.100.4")):
                raise asyncio.CancelledError
        async with limits.public_query_slot(request("198.51.100.5")):
            pass
        with pytest.raises(HTTPException) as error:
            async with limits.public_query_slot(request("198.51.100.6")):
                pass
        assert error.value.status_code == 429
        keys, _ = limits._keys("198.51.100.4", limits.time.time())
        assert await redis.zcard(keys[4]) == 0
        await redis.aclose()
    asyncio.run(check())


def test_missing_redis_fails_closed(monkeypatch):
    class Offline:
        async def eval(self, *args):
            raise ConnectionError("offline")
    monkeypatch.setattr(limits, "_client", Offline())
    async def check():
        with pytest.raises(HTTPException) as error:
            async with limits.public_query_slot(request("198.51.100.4")):
                pytest.fail("must not call provider")
        assert error.value.status_code == 503
    asyncio.run(check())


def test_global_concurrency_and_daily_ip_budget(monkeypatch):
    monkeypatch.setenv("HYPERCHE_PUBLIC_IP_PER_DAY", "1")
    async def check():
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        monkeypatch.setattr(limits, "_client", redis)
        async with limits.public_query_slot(request("198.51.100.4")):
            async with limits.public_query_slot(request("198.51.100.5")):
                with pytest.raises(HTTPException) as error:
                    async with limits.public_query_slot(request("198.51.100.6")):
                        pass
                assert error.value.status_code == 429
        async with limits.public_query_slot(request("198.51.100.6")):
            pass
        with pytest.raises(HTTPException) as error:
            async with limits.public_query_slot(request("198.51.100.4")):
                pass
        assert error.value.status_code == 429
        assert int(error.value.headers["Retry-After"]) > 60
        await redis.aclose()
    asyncio.run(check())
