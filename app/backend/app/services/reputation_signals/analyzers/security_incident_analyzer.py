from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


SECURITY_TERMS = [
    "data breach", "breach", "hack", "hacked", "cyber attack",
    "cyberattack", "ransomware", "data leak", "leaked data",
    "security incident", "privacy breach", "customer data exposed",
]


def analyze_security_incidents(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        matched, term = contains_any(text, SECURITY_TERMS)
        if not matched:
            continue
        signal = "security_incident"
        signals.append(evidence_card(
            item,
            signal,
            0.84,
            f"Matched security incident term: {term}",
            {
                "brsr_principle": map_brsr_signal("governance", [term]).get("principle") or "Principle 9",
                "sdgs": map_sdg_terms([term], "regulatory_action"),
                "matched_terms": [term],
            },
        ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Security Incidents",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} security incident signal(s)."
            if signals else
            "No direct security incident signal found in temporary live evidence."
        ),
    }
