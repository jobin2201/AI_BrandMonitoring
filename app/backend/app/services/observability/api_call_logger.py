from __future__ import annotations

import json
from pathlib import Path

from app.services.observability.entity_trace_logger import json_safe
from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = BACKEND_ROOT / "logs" / "entity_resolution" / "api_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_api_call(request_id: int, api_name: str, payload: dict, response: dict):
    file_path = LOG_DIR / f"{api_name}_{request_id}.json"
    data = {
        "request_id": request_id,
        "api": api_name,
        "timestamp": now_ist(),
        "payload": json_safe(payload),
        "response": json_safe(response),
    }
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return str(file_path)
