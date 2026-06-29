from __future__ import annotations

import json
from pathlib import Path

from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = BACKEND_ROOT / "logs" / "entity_resolution" / "traces"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]
        return str(value)


class EntityTraceLogger:
    def __init__(self, request_id: int):
        self.request_id = request_id
        self.steps = []
        self.start_time = now_ist()

    def log(self, step: str, data: dict):
        self.steps.append({
            "step": step,
            "timestamp": now_ist(),
            "data": json_safe(data),
        })

    def save(self):
        file_path = LOG_DIR / f"{self.request_id}.json"
        payload = {
            "request_id": self.request_id,
            "start_time": self.start_time,
            "steps": self.steps,
        }
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return str(file_path)
