from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.utils.time_utils import now_ist


LOG_ROOT = Path(__file__).resolve().parents[4] / "logs" / "reputation_signals"


def write_reputation_log(kind: str, brand_id: str, payload: dict[str, Any]) -> str:
    try:
        directory = LOG_ROOT / kind
        directory.mkdir(parents=True, exist_ok=True)
        request_id = str(int(time.time() * 1000))
        path = directory / f"{kind}_{brand_id}_{request_id}.json"
        payload = {
            "request_id": request_id,
            "brand_id": brand_id,
            "kind": kind,
            "timestamp": now_ist(),
            **payload,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)
    except Exception as exc:
        print(f"[REPUTATION][LOG] Could not write {kind} log for {brand_id}: {exc}")
        return ""
