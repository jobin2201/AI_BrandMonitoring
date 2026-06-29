from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.classifiers.keyword_classifier import classify_reputation_text
from app.services.reputation_signals.reputation_common import contains_any, dedupe_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


FAILURE_TERMS = [
    "recall", "bug", "outage", "battery issue", "defect", "explosion",
    "crash", "lawsuit", "complaint", "failure", "fault", "overheating",
    "not working", "broken", "quality issue", "shoe defect", "sole separation",
    "tearing", "poor quality", "durability issue", "defective", "product recall",
    "manufacturing defect", "design flaw", "battery drain", "thermal throttling",
    "firmware issue", "bios issue", "driver issue", "camera issue",
    "screen issue", "display issue", "charging issue", "performance problem",
]
SUCCESS_TERMS = [
    "award", "best-selling", "bestselling", "top rated", "successful launch",
    "positive reviews", "market leader", "wins", "innovation award",
    "record sales", "strong demand", "product launch", "service launch",
    "new collection", "sneaker release", "collaboration", "limited edition",
    "customer rating", "best airline", "new route", "new aircraft",
    "best shoes", "best sneakers", "highly rated", "top-selling",
    "sales milestone", "sold out", "strong sales", "popular model",
    "customer favorite", "wins award", "ranked best", "product success",
    "new feature", "new features", "feature update", "app update",
    "platform update", "service update", "new plan", "new tier",
    "ad tier", "ads tier", "subscription tier", "rolls out",
    "expands service", "user experience", "ux update", "games launch",
    "streaming feature", "mobile app", "web app", "release date",
    "launch date", "released", "specs", "specifications", "hands-on",
    "first look", "benchmark", "camera upgrade", "battery life",
    "performance review", "review roundup", "price revealed",
]


def analyze_product_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        classification = classify_reputation_text(text)
        if classification.get("decision") != "reject" and classification.get("signal") in {
            "product_failure",
            "product_success",
        }:
            signal_name = classification["signal"]
            matched_terms = classification.get("matched_terms") or []
            signals.append(evidence_card(
                item,
                signal_name,
                float(classification.get("confidence") or 0.0),
                classification.get("reason") or f"Classified as {signal_name}",
                {
                    "classification_source": classification.get("source"),
                    "classification_decision": classification.get("decision"),
                    "brsr_principle": map_brsr_signal(signal_name, matched_terms).get("principle"),
                    "sdgs": map_sdg_terms(matched_terms, signal_name),
                    "matched_terms": matched_terms,
                },
            ))
            continue

        matched, term = contains_any(text, FAILURE_TERMS)
        if matched:
            signals.append(evidence_card(
                item,
                "product_failure",
                0.74,
                f"Matched product failure term: {term}",
                {
                    "brsr_principle": map_brsr_signal("product_failure", [term]).get("principle"),
                    "sdgs": map_sdg_terms([term], "product_failure"),
                    "matched_terms": [term],
                },
            ))
            continue
        matched, term = contains_any(text, SUCCESS_TERMS)
        if matched:
            signals.append(evidence_card(
                item,
                "product_success",
                0.72,
                f"Matched product success term: {term}",
                {
                    "brsr_principle": map_brsr_signal("product_success", [term]).get("principle"),
                    "sdgs": map_sdg_terms([term], "product_success"),
                    "matched_terms": [term],
                },
            ))

    signals = dedupe_items(signals, 8)
    return {
        "title": "Product Failures / Successes",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} product reputation signal(s)."
            if signals else
            "No direct product failure or success signal found in temporary live evidence."
        ),
    }
