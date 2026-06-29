from __future__ import annotations

import re
from typing import Any

TERMINATION_RE = re.compile(
    r"\b(layoffs?|laid off|downsizing|workforce reduction|employee reduction|staff reduction|workforce cuts|job cuts|cut jobs|cuts jobs|headcount reduction|staff cuts|retrenchment|redundancies|office closure|store closure|plant closure|factory closure|ceased operations|discontinued operations)\b",
    re.IGNORECASE,
)
RESTRUCTURING_WITH_WORKFORCE_RE = re.compile(
    r"\b(restructuring|restructure)\b.*\b(workforce|employees?|staff|jobs|headcount|operations)\b|"
    r"\b(workforce|employees?|staff|jobs|headcount|operations)\b.*\b(restructuring|restructure)\b",
    re.IGNORECASE,
)
COUNT_RE = re.compile(r"\b(\d{2,6})\b")


def termination_events(mentions: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    events = []
    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        match = TERMINATION_RE.search(text)
        restructuring_match = RESTRUCTURING_WITH_WORKFORCE_RE.search(text)
        if not match and not restructuring_match:
            continue
        count = COUNT_RE.search(text)
        events.append({
            "event": (match.group(1) if match else "workforce restructuring").lower(),
            "count": int(count.group(1)) if count else None,
            "title": mention.get("title") or text[:120],
            "source": mention.get("source") or "",
            "url": mention.get("url") or "",
        })
        if len(events) >= limit:
            break
    return events
