from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


FRAUD_TERMS = [
    "fraud", "scam", "bribery", "corruption", "money laundering",
    "accounting irregularities", "forged", "misconduct", "embezzlement",
    "false claims", "deceptive practices",
]


def analyze_fraud_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        matched, term = contains_any(text, FRAUD_TERMS)
        if not matched:
            continue
        signal = "fraud_allegation"
        signals.append(evidence_card(
            item,
            signal,
            0.86,
            f"Matched fraud/governance term: {term}",
            {
                "brsr_principle": map_brsr_signal("governance", [term]).get("principle") or "Principle 1",
                "sdgs": map_sdg_terms([term], "governance"),
                "matched_terms": [term],
            },
        ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Fraud Allegations",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} fraud/governance signal(s)."
            if signals else
            "No direct fraud allegation signal found in temporary live evidence."
        ),
    }
