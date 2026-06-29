from __future__ import annotations

from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.classifiers.keyword_classifier import (
    classify_sdg_keywords,
    classify_reputation_text,
    has_only_generic_esg_signal,
)
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms
from app.services.reputation_signals.sdg.sdg_rules import SDG_RULES
from app.services.reputation_signals.reputation_common import dedupe_items, evidence_card, text_for_item


def _brsr_principle(matches: list[dict[str, Any]]) -> str:
    for match in matches:
        for term in match.get("matched_terms") or []:
            principle = map_brsr_signal(match.get("pillar") or "", [term]).get("principle")
            if principle:
                return principle
    return ""


def _pillar_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"environmental": 0, "social": 0, "governance": 0}
    for item in items:
        pillar = item.get("esg_pillar")
        if pillar in counts:
            counts[pillar] += 1
    return counts


def _sdg_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {rule["code"]: 0 for rule in SDG_RULES}
    for item in items:
        for sdg in item.get("sdgs") or []:
            code = sdg.get("code") if isinstance(sdg, dict) else str(sdg)
            if code in counts:
                counts[code] += 1
    return counts


def analyze_esg_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        classification = classify_reputation_text(text)
        if classification.get("signal") not in {"environmental", "social", "governance"}:
            continue
        if classification.get("decision") == "reject":
            continue

        matches = classify_sdg_keywords(text)
        if not matches:
            # Avoid classifying generic "sustainability" headlines without a
            # concrete SDG signal, which caused earlier false positives.
            if has_only_generic_esg_signal(text):
                continue
            matches = map_sdg_terms(
                classification.get("matched_terms") or [],
                classification.get("signal") or "",
            )

        primary = matches[0]
        matched_terms = primary.get("matched_terms") or []
        signal = evidence_card(
            item,
            f"esg_{primary['pillar']}_{primary['code'].lower()}",
            min(0.95, 0.72 + 0.05 * len(matched_terms)),
            (
                f"Mapped to {primary['code']} ({primary['name']}) "
                f"using: {', '.join(matched_terms[:4]) or classification.get('source')}"
            ),
            {
                "esg_pillar": primary["pillar"],
                "sdg_code": primary["code"],
                "sdg_name": primary["name"],
                "sdgs": [
                    {
                        "code": match["code"],
                        "name": match["name"],
                        "pillar": match["pillar"],
                        "matched_terms": match["matched_terms"],
                    }
                    for match in matches
                ],
                "brsr_principle": (
                    _brsr_principle(matches)
                    or map_brsr_signal(classification.get("signal") or "", matched_terms).get("principle")
                ),
                "matched_terms": matched_terms,
                "classification_source": classification.get("source"),
                "classification_decision": classification.get("decision"),
            },
        )
        signals.append(signal)

    signals = dedupe_items(signals, 12)
    return {
        "title": "ESG Issues",
        "items": signals,
        "count": len(signals),
        "pillar_counts": _pillar_counts(signals),
        "sdg_counts": _sdg_counts(signals),
        "sdg_taxonomy": [
            {
                "code": rule["code"],
                "name": rule["name"],
                "pillar": rule["pillar"],
            }
            for rule in SDG_RULES
        ],
        "summary": (
            f"Found {len(signals)} ESG signal(s) mapped across the 17 SDGs."
            if signals else
            "No direct ESG signal found in temporary live evidence."
        ),
    }
