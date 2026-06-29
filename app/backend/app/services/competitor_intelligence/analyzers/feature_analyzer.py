from __future__ import annotations

import re
from typing import Any

FEATURE_PATTERNS = [
    "ai feature",
    "ai features",
    "battery improvement",
    "camera upgrade",
    "camera upgrades",
    "launches",
    "launched",
    "release",
    "releases",
    "released",
    "available on",
    "now available",
    "rolled out",
    "rolling out",
    "ships",
    "shipping",
    "added support",
    "adds support",
    "introduces",
    "introduced",
    "announces",
    "announced",
    "reveals",
    "revealed",
    "unveils",
    "unveiled",
    "debuts",
    "debuted",
    "debuts on",
    "expands to",
    "integration",
    "integrated with",
    "new feature",
    "new features",
    "upgrade",
    "upgrades",
    "upgraded",
]

FEATURE_CONTEXT_RE = re.compile(
    r"\b(feature|features|model|models|product|tool|tools|app|api|camera|battery|software|platform|service|agent|assistant|codex|upgrade|mode|capability)\b",
    re.IGNORECASE,
)
NON_FEATURE_RE = re.compile(
    r"\b(ipo|stock|shares?|funding|valuation|blockbuster launches|market debut|launches on wall street|acquisition|acquired|merger|takeover|buyout)\b",
    re.IGNORECASE,
)


def feature_announcements(mentions: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    results = []
    pattern = re.compile(r"\b(" + "|".join(re.escape(term) for term in FEATURE_PATTERNS) + r")\b", re.I)

    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        match = pattern.search(text)
        if not match:
            continue
        if NON_FEATURE_RE.search(text):
            continue
        if match.group(1).lower() in {"launches", "launched", "release", "released", "debuts", "debuted"}:
            if not FEATURE_CONTEXT_RE.search(text):
                continue
        title = (mention.get("title") or "").strip()
        snippet = text.strip()[:220]
        results.append({
            "feature": title or snippet[:120],
            "trigger": match.group(1).lower(),
            "date": mention.get("published_at") or "",
            "source": mention.get("source") or "",
            "url": mention.get("url") or "",
            "evidence": snippet,
        })
        if len(results) >= limit:
            break

    return results
