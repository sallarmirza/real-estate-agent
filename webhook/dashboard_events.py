"""Publishes a 'data changed' event to Redis after every lead write.

Best-effort: a Redis problem must never break message handling.
"""
from __future__ import annotations
import json
import os
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHANNEL = "real_estate_dashboard_events"

_client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def publish_dashboard_event() -> None:
    try:
        _client.publish(CHANNEL, json.dumps({}))
    except Exception:
        pass
