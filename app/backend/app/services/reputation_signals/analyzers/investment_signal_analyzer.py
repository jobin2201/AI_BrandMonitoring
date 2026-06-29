from __future__ import annotations

import re
from typing import Any

from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.classifiers.keyword_classifier import classify_reputation_text
from app.services.reputation_signals.reputation_common import contains_any, dedupe_items, evidence_card, text_for_item
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms


INVESTMENT_TERMS = [
    "invests", "investment", "funding", "capital injection", "stake acquired",
    "raises", "venture investment", "expansion", "backs", "financing",
    "manufacturing", "factory", "production facility", "plant",
    "partnership", "joint venture", "capacity expansion",
    "manufacturing expansion", "production expansion", "new facility",
]
WITHDRAWAL_TERMS = [
    "divestment", "exit", "shutdown", "withdraws", "pulls out",
    "closes operations", "sells stake", "halts investment", "cuts investment",
]
NON_COMPANY_INVESTMENT_RE = re.compile(
    r"\b(founder|chairman|ceo|executive|minister|official)\b.*\b("
    r"declines|declined|appointed|position|role|national investment fund|"
    r"investment fund chairman"
    r")\b",
    re.IGNORECASE,
)
COMPANY_ACTION_RE = re.compile(
    r"\b("
    r"invests?|invested|investment in|funding|funds?|raises?|raised|"
    r"capital injection|stake acquired|acquires stake|expansion|backs|"
    r"financing|manufacturing|factory|production facility|plant|"
    r"partnership|joint venture|capacity expansion|new facility|"
    r"divests?|divestment|exits?|withdraws?|pulls out|"
    r"closes operations|sells stake|halts investment|cuts investment"
    r")\b",
    re.IGNORECASE,
)


def is_company_investment_event(text: str) -> bool:
    if NON_COMPANY_INVESTMENT_RE.search(text or ""):
        return False
    return bool(COMPANY_ACTION_RE.search(text or ""))


def analyze_investment_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    signals = []
    for item in items:
        text = text_for_item(item)
        if not is_company_investment_event(text):
            continue
        classification = classify_reputation_text(text)
        if classification.get("decision") != "reject" and classification.get("signal") in {
            "investment",
            "withdrawal",
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

        matched, term = contains_any(text, INVESTMENT_TERMS)
        if matched:
            signals.append(evidence_card(item, "investment", 0.82, f"Matched investment term: {term}"))
            continue
        matched, term = contains_any(text, WITHDRAWAL_TERMS)
        if matched:
            signals.append(evidence_card(item, "withdrawal", 0.82, f"Matched withdrawal term: {term}"))

    signals = dedupe_items(signals, 8)
    return {
        "title": "Investments & Withdrawals",
        "items": signals,
        "count": len(signals),
        "summary": (
            f"Found {len(signals)} investment/withdrawal signal(s)."
            if signals else
            "No direct investment or withdrawal signal found in temporary live evidence."
        ),
    }
