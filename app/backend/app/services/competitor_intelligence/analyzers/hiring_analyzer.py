from __future__ import annotations

import re
from typing import Any

HIRING_TERMS = [
    "h-1b",
    "h1b",
    "visa sponsorship",
    "hiring",
    "hiring plans",
    "recruiting",
    "recruitment drive",
    "job openings",
    "headcount",
    "headcount growth",
    "employee growth",
    "staff expansion",
    "expanding engineering team",
    "workforce expansion",
    "talent acquisition",
    "new roles",
    "to hire",
]


def hiring_trends(mentions: list[dict[str, Any]]) -> dict[str, Any]:
    pattern = re.compile("|".join(re.escape(term) for term in HIRING_TERMS), re.I)
    evidence = []

    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        if not pattern.search(text):
            continue
        if len(evidence) < 10:
            evidence.append({
                "title": mention.get("title") or text[:120],
                "source": mention.get("source") or "",
                "url": mention.get("url") or "",
            })

    count = len(evidence)
    trend = "increasing" if count >= 5 else "some_activity" if count else "no_signal"
    return {
        "trend": trend,
        "evidence_count": count,
        "evidence": evidence,
    }
