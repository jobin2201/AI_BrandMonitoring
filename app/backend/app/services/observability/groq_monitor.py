from __future__ import annotations

import json
import os
from pathlib import Path

from groq import Groq
from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = BACKEND_ROOT / "logs" / "entity_resolution" / "api_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_groq_limits(client: Groq):
    resp = client.chat.completions.with_raw_response.create(
        model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        messages=[{"role": "user", "content": "ping"}],
    )
    headers = resp.headers
    return {
        "max_requests_day": headers.get("x-ratelimit-limit-requests"),
        "remaining_requests": headers.get("x-ratelimit-remaining-requests"),
        "remaining_tokens_min": headers.get("x-ratelimit-remaining-tokens"),
        "timestamp": now_ist(),
    }


def log_groq_usage(request_id: int, client: Groq):
    limits = get_groq_limits(client)
    file_path = LOG_DIR / f"groq_{request_id}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump({"request_id": request_id, "limits": limits}, f, indent=2)

    print("\n--- GROQ LIVE LIMITS ---")
    print("Request ID:", request_id)
    print("Max Requests/Day:", limits["max_requests_day"])
    print("Remaining Requests:", limits["remaining_requests"])
    print("Remaining Tokens/Min:", limits["remaining_tokens_min"])
    return limits
