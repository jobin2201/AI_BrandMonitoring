from __future__ import annotations

from collections import Counter
from typing import Any


def sentiment_breakdown(mentions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter((mention.get("sentiment_label") or "unknown").lower() for mention in mentions)
    total = sum(counts.values())
    percentages = {
        label: round((count / total) * 100, 2) if total else 0.0
        for label, count in counts.items()
    }
    for label in ["positive", "neutral", "negative"]:
        counts.setdefault(label, 0)
        percentages.setdefault(label, 0.0)

    return {
        "counts": dict(counts),
        "percentages": percentages,
        "total_mentions": total,
    }
