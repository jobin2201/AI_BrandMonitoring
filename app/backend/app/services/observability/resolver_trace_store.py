from __future__ import annotations

import json
from pathlib import Path

from app.services.observability.entity_trace_logger import json_safe
from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = BACKEND_ROOT / "logs" / "entity_resolution"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "resolver.log"


def append_resolver_event(request_id: int, event: str, data: dict | None = None):
    payload = {
        "request_id": request_id,
        "timestamp": now_ist(),
        "event": event,
        "data": json_safe(data or {}),
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    return str(LOG_FILE)
