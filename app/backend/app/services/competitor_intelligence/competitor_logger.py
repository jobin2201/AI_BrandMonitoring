from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


LOG_ROOT = Path(__file__).resolve().parents[3] / "logs" / "competitor_analysis"
LOG_KINDS = [
    "discovery",
    "profiles",
    "swot",
    "prompts",
    "validation",
    "traces",
    "fallbacks",
    "retrieval",
]


def now_ist() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:80]


def ensure_competitor_log_dirs():
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    for kind in LOG_KINDS:
        (LOG_ROOT / kind).mkdir(parents=True, exist_ok=True)
    (LOG_ROOT / "competitor.log").touch(exist_ok=True)


def append_competitor_log(message: str, data: dict | None = None):
    ensure_competitor_log_dirs()
    line = {
        "timestamp": now_ist(),
        "message": message,
        "data": data or {},
    }
    with (LOG_ROOT / "competitor.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, default=str) + "\n")


def write_competitor_log(kind: str, brand_id: str, payload: dict) -> str:
    ensure_competitor_log_dirs()
    directory = LOG_ROOT / kind
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_name(brand_id)}_{int(datetime.now().timestamp() * 1000)}.json"
    path = directory / filename
    data = {
        "timestamp": now_ist(),
        "brand_id": brand_id,
        **payload,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, default=str)
    append_competitor_log(f"{kind}_log_written", {
        "brand_id": brand_id,
        "path": str(path),
    })
    return str(path)
