from __future__ import annotations

from typing import Any

from app.services.reputation_signals.reputation_common import contains_any, text_for_item


POSITIVE_TERMS = [
    "award", "wins", "praised", "best", "top rated", "record sales",
    "strong demand", "successful", "improves", "growth",
]
NEGATIVE_TERMS = [
    "complaint", "lawsuit", "recall", "failure", "defect", "fine",
    "penalty", "investigation", "criticism", "boycott", "layoff",
]


def analyze_reputation_sentiment(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for item in items:
        text = text_for_item(item)
        negative, _ = contains_any(text, NEGATIVE_TERMS)
        positive, _ = contains_any(text, POSITIVE_TERMS)
        if negative:
            counts["negative"] += 1
        elif positive:
            counts["positive"] += 1
        else:
            counts["neutral"] += 1

    total = sum(counts.values())
    percentages = {
        label: round((count / total) * 100, 2) if total else 0.0
        for label, count in counts.items()
    }
    return {
        "title": "Reputation Sentiment",
        "counts": counts,
        "percentages": percentages,
        "total_mentions": total,
        "source": "temporary_keyword_rules",
    }

