from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


LAYOFF_TERMS = [
    "layoff", "layoffs", "job cuts", "workforce reduction",
    "retrenchment", "salary delay", "delayed pay", "delays pay",
    "unpaid wages", "pilot pay delayed", "pay delayed",
    "furlough", "restructuring", "redundancies",
]


def analyze_layoff_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        matched, term = contains_any(text, LAYOFF_TERMS)
        if not matched:
            continue
        signal = "employee_wellbeing_risk"
        signals.append(evidence_card(
            item,
            signal,
            0.82,
            f"Matched workforce/pay risk term: {term}",
            {
                "brsr_principle": map_brsr_signal("social", [term]).get("principle") or "Principle 3",
                "sdgs": map_sdg_terms([term], "social"),
                "matched_terms": [term],
            },
        ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Layoffs & Employee Well-being",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} layoff/employee well-being signal(s)."
            if signals else
            "No direct layoff or employee well-being signal found in temporary live evidence."
        ),
    }
