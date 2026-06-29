from __future__ import annotations

import json
from pathlib import Path

from app.services.observability.entity_trace_logger import json_safe
from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = BACKEND_ROOT / "logs" / "entity_resolution" / "db_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_db_operation(request_id: int, operation: str, table: str, data: dict):
    file_path = LOG_DIR / f"db_{request_id}.json"
    entry = {
        "request_id": request_id,
        "operation": operation,
        "table": table,
        "timestamp": now_ist(),
        "data": json_safe(data),
    }

    if file_path.exists():
        with file_path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    existing.append(entry)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    return str(file_path)
