from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


COMPLAINT_TERMS = [
    "complaint", "complaints", "poor service", "bad service", "refund issue",
    "refund problem", "delay", "delayed", "cancelled", "canceled",
    "worst experience", "scam", "fraudulent charge", "customer care",
    "support issue", "not resolved", "consumer complaint",
    "service issue", "delivery issue", "quality complaint", "refund delay",
    "replacement issue", "warranty issue", "after sales service",
    "customer support", "unresolved complaint", "defective product",
    "poor quality", "bad experience", "faulty", "impossible complaint",
    "not working", "product issue", "service failure",
]


def analyze_customer_complaints(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        matched, term = contains_any(text, COMPLAINT_TERMS)
        if not matched:
            continue
        signal = "customer_complaint"
        signals.append(evidence_card(
            item,
            signal,
            0.78,
            f"Matched customer complaint term: {term}",
            {
                "brsr_principle": map_brsr_signal(signal, [term]).get("principle") or "Principle 9",
                "sdgs": map_sdg_terms([term], signal),
                "matched_terms": [term],
            },
        ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Customer Complaints",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} customer complaint signal(s)."
            if signals else
            "No direct customer complaint signal found in temporary live evidence."
        ),
    }
