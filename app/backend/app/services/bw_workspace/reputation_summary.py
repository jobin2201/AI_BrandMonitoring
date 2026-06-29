from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.bw_workspace.reputation_category_mapper import REPUTATION_SECTION_KEYS


def build_reputation_summary(reputation: dict[str, Any]) -> dict[str, Any]:
    verified = []
    related = []
    sources = Counter()
    products = Counter()
    executives = Counter()

    for key in REPUTATION_SECTION_KEYS:
        for item in reputation.get(key, {}).get("items") or []:
            verified.append({**item, "section": key})
        for item in reputation.get(key, {}).get("related_mentions") or []:
            related.append({**item, "section": key})

    for item in [*verified, *related]:
        source = item.get("source_name") or item.get("source") or "unknown"
        sources[source] += 1
        if item.get("matched_product"):
            products[str(item.get("matched_product"))] += 1
        if item.get("executive_name"):
            executives[str(item.get("executive_name"))] += 1

    highest_risk = sorted(
        verified,
        key=lambda item: float(item.get("bw_risk") or 0),
        reverse=True,
    )[:1]
    top_category = Counter(item["section"] for item in [*verified, *related]).most_common(1)
    return {
        "verified": len(verified),
        "related": len(related),
        "highest_risk": highest_risk[0] if highest_risk else {},
        "top_category": top_category[0][0] if top_category else "",
        "top_category_count": top_category[0][1] if top_category else 0,
        "top_sources": sources.most_common(5),
        "most_discussed_product": products.most_common(1)[0][0] if products else "",
        "top_executive": executives.most_common(1)[0][0] if executives else "",
    }
