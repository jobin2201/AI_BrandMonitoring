from __future__ import annotations

import re
from typing import Any

MERGER_RE = re.compile(
    r"\b(acquired|acquires|acquisition|strategic acquisition|merger|merged|takeover|purchase of|purchased|buyout|bought|deal to buy)\b",
    re.IGNORECASE,
)


def merger_events(mentions: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    events = []
    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        match = MERGER_RE.search(text)
        if not match:
            continue
        events.append({
            "event": match.group(1).lower(),
            "title": mention.get("title") or text[:120],
            "source": mention.get("source") or "",
            "url": mention.get("url") or "",
        })
        if len(events) >= limit:
            break
    return events
