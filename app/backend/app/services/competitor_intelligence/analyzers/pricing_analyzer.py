from __future__ import annotations

import re
from typing import Any

PRICE_RE = re.compile(
    r"""
    (?: 
        (?:rs\.?|inr|₹)\s?\d[\d,]*(?:\.\d+)?
        (?:\s?/(?:month|mo|year|yr|user|seat|token|1k\s?tokens|million\s?tokens))?
    )
    |
    (?:
        \$\s?\d[\d,]*(?:\.\d+)?
        (?:\s?(?:/|per)\s?(?:month|mo|year|yr|user|seat|token|1k\s?tokens|million\s?tokens))?
    )
    |
    (?:
        \d[\d,]*(?:\.\d+)?\s?(?:credits|tokens)\s?(?:per|/)\s?(?:month|mo|day|request)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

PRICING_CONTEXT_RE = re.compile(
    r"\b(subscription|pricing plan|pricing|enterprise pricing|api pricing|credits|tokens|per user|per seat|monthly|annual|pro plan|team plan|enterprise plan)\b",
    re.IGNORECASE,
)
FUNDING_CONTEXT_RE = re.compile(
    r"\b(raised|raising|funding|series\s+[a-z]|investment|investors?|venture capital|valuation|capital raise)\b",
    re.IGNORECASE,
)


def _numeric_price(value: str) -> float | None:
    digits = re.sub(r"[^\d.]", "", value or "")
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def pricing_intelligence(mentions: list[dict[str, Any]]) -> dict[str, Any]:
    price_points = []
    examples = []
    numeric_prices = []

    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        found = PRICE_RE.findall(text)
        context_match = PRICING_CONTEXT_RE.search(text)
        if found and FUNDING_CONTEXT_RE.search(text) and not context_match:
            continue
        if not found and not context_match:
            continue
        found = [item if isinstance(item, str) else "".join(item) for item in found]
        for price in found:
            clean_price = price.strip()
            if not clean_price:
                continue
            price_points.append(clean_price)
            numeric = _numeric_price(clean_price)
            if numeric is not None:
                numeric_prices.append(numeric)
        if len(examples) < 5:
            examples.append({
                "title": mention.get("title") or "",
                "prices": [price.strip() for price in found],
                "pricing_context": context_match.group(1) if context_match else "",
                "source": mention.get("source") or "",
            })

    average_price = round(sum(numeric_prices) / len(numeric_prices), 2) if numeric_prices else None
    return {
        "price_points": price_points[:20],
        "average_price": average_price,
        "evidence_count": len(examples),
        "examples": examples,
    }
