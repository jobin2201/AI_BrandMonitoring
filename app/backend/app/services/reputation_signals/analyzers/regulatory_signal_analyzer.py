from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.classifiers.keyword_classifier import classify_reputation_text
from app.services.reputation_signals.reputation_common import contains_any, group_incident_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


REGULATORY_TERMS = [
    "regulatory action", "fine", "penalty", "investigation", "compliance",
    "lawsuit", "court order", "antitrust", "data privacy", "consumer protection",
    "sec", "sebi", "ftc", "rbi", "dgca", "nclt", "cci", "ed", "cbi",
    "regulator", "regulatory probe", "violation", "settlement",
    "show cause notice", "tax demand", "notice from", "legal notice",
    "probe", "inquiry", "class action", "consumer court", "tribunal",
    "compliance failure", "license suspension", "regulatory scrutiny",
    "tax notice", "charges", "charged", "gst", "itc", "input tax credit",
    "compliance issue", "tax fraud", "enforcement", "enforcement action",
    "tax investigation", "finance manager", "fraud charges",
]


def analyze_regulatory_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        classification = classify_reputation_text(text)
        if classification.get("decision") != "reject" and classification.get("signal") == "regulatory_action":
            matched_terms = classification.get("matched_terms") or []
            signals.append(evidence_card(
                item,
                "regulatory_signal",
                float(classification.get("confidence") or 0.0),
                classification.get("reason") or "Classified as regulatory action",
                {
                    "classification_source": classification.get("source"),
                    "classification_decision": classification.get("decision"),
                    "brsr_principle": map_brsr_signal("regulatory_action", matched_terms).get("principle"),
                    "sdgs": map_sdg_terms(matched_terms, "regulatory_action"),
                    "matched_terms": matched_terms,
                },
            ))
            continue

        matched, term = contains_any(text, REGULATORY_TERMS)
        if matched:
            signals.append(evidence_card(
                item,
                "regulatory_signal",
                0.8,
                f"Matched regulatory reputation term: {term}",
                {
                    "brsr_principle": map_brsr_signal("regulatory_action", [term]).get("principle"),
                    "sdgs": map_sdg_terms([term], "regulatory_action"),
                    "matched_terms": [term],
                },
            ))

    signals = group_incident_items(signals, 8)
    return {
        "title": "Regulatory Signals",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} regulatory signal(s)."
            if signals else
            "No direct regulatory signal found in temporary live evidence."
        ),
    }
