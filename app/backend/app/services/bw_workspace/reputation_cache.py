from __future__ import annotations

import copy
import time
from typing import Any


_CACHE: dict[str, dict[str, Any]] = {}
_TTL_SECONDS = 900


def get_cached_reputation(cache_key: str) -> dict[str, Any] | None:
    entry = _CACHE.get(cache_key)
    if not entry:
        return None
    if time.time() - float(entry.get("created_at") or 0) > _TTL_SECONDS:
        _CACHE.pop(cache_key, None)
        return None
    payload = copy.deepcopy(entry.get("payload") or {})
    payload.setdefault("bw_cache", {})["hit"] = True
    return payload


def set_cached_reputation(cache_key: str, payload: dict[str, Any]) -> None:
    _CACHE[cache_key] = {
        "created_at": time.time(),
        "payload": copy.deepcopy(payload),
    }
