from __future__ import annotations

import re
from typing import Any

STRONG_FUNDING_RE = re.compile(
    r"\b(raised|raising|funding|series\s+[a-z]|investment round|venture capital|seed round|pre-seed|backed by|capital raise|valuation)\b",
    re.IGNORECASE,
)
INVESTOR_CONTEXT_RE = re.compile(
    r"\b(investors?|softbank|sequoia|andreessen horowitz|a16z)\b",
    re.IGNORECASE,
)
INVESTOR_REQUIRED_CONTEXT_RE = re.compile(
    r"\b(raised|raising|funding|backed|valuation|capital|round|investment)\b",
    re.IGNORECASE,
)
AMOUNT_RE = re.compile(r"(?:\$\s?[\d,.]+\s?(?:m|million|b|billion)?|[\d,.]+\s?(?:million|billion))", re.IGNORECASE)


def funding_events(mentions: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    events = []
    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        match = STRONG_FUNDING_RE.search(text)
        investor_match = INVESTOR_CONTEXT_RE.search(text)
        if not match and investor_match and INVESTOR_REQUIRED_CONTEXT_RE.search(text):
            match = investor_match
        if not match:
            continue
        amount = AMOUNT_RE.search(text)
        events.append({
            "event": match.group(1).lower(),
            "amount": amount.group(0) if amount else "",
            "title": mention.get("title") or text[:120],
            "source": mention.get("source") or "",
            "url": mention.get("url") or "",
        })
        if len(events) >= limit:
            break
    return events
