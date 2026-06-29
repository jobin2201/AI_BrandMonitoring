from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


EXECUTIVE_TERMS = [
    "ceo", "chairman", "founder", "board", "president", "cfo", "coo",
    "executive", "management", "chief", "director", "head",
    "hr head", "senior vice president", "svp",
]
CONTROVERSY_TERMS = [
    "controversy", "resigns", "resignation", "steps down", "ousted",
    "leadership crisis", "board dispute", "management shakeup",
    "misconduct", "investigated", "investigation", "scandal",
    "head resigns", "addresses diversity issues", "diversity issues",
    "internal probe", "internal investigation", "workplace allegations",
]


def analyze_executive_controversies(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        role_matched, role_term = contains_any(text, EXECUTIVE_TERMS)
        action_matched, action_term = contains_any(text, CONTROVERSY_TERMS)
        if not role_matched or not action_matched:
            continue
        signal = "executive_controversy"
        signals.append(evidence_card(
            item,
            signal,
            0.82,
            f"Matched executive controversy terms: {role_term}, {action_term}",
            {
                "brsr_principle": map_brsr_signal("governance", [role_term, action_term]).get("principle") or "Principle 1",
                "sdgs": map_sdg_terms([role_term, action_term], "governance"),
                "matched_terms": [role_term, action_term],
            },
        ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Executive Controversies",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} executive controversy signal(s)."
            if signals else
            "No direct executive controversy signal found in temporary live evidence."
        ),
    }
