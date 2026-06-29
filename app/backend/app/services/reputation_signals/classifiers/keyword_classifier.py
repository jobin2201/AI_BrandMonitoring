from __future__ import annotations

import os
from typing import Any

from app.services.reputation_signals.reputation_common import normalize
from app.services.reputation_signals.sdg.sdg_rules import SDG_RULES
from app.services.reputation_signals.classifiers.llm_verifier import verify_with_llm
from app.services.reputation_signals.classifiers.zero_shot_classifier import classify_zero_shot


SIGNAL_LABELS = [
    "environmental issue",
    "social issue",
    "governance issue",
    "product success",
    "product failure",
    "investment",
    "withdrawal",
    "regulatory action",
    "customer complaint",
    "security incident",
    "layoff",
    "fraud allegation",
    "executive controversy",
    "none",
]


SIGNAL_KEYWORDS = {
    "environmental": [
        "renewable energy", "carbon", "emissions", "climate", "solar",
        "wind", "pollution", "waste", "recycling", "water conservation",
        "net zero", "biodiversity", "deforestation", "greenhouse gas",
        "sustainable aviation fuel", "saf", "environmental impact",
    ],
    "social": [
        "diversity", "employee welfare", "human rights", "worker safety",
        "community", "education", "healthcare", "gender equality",
        "inclusion", "livelihood", "workforce", "wellbeing",
    ],
    "governance": [
        "fraud", "corruption", "ethics", "investigation", "governance",
        "compliance", "transparency", "whistleblower", "data privacy",
        "regulatory violation",
    ],
    "product_success": [
        "award", "best-selling", "bestselling", "top rated",
        "successful launch", "positive reviews", "market leader",
        "record sales", "strong demand",
    ],
    "product_failure": [
        "recall", "bug", "outage", "battery issue", "defect", "explosion",
        "crash", "complaint", "failure", "fault", "overheating",
        "not working", "broken", "quality issue",
    ],
    "investment": [
        "invests", "investment", "funding", "capital injection",
        "stake acquired", "raises", "venture investment", "expansion",
        "backs", "financing",
    ],
    "withdrawal": [
        "divestment", "exit", "shutdown", "withdraws", "pulls out",
        "closes operations", "sells stake", "halts investment",
        "cuts investment",
    ],
    "regulatory_action": [
        "regulatory action", "fine", "penalty", "lawsuit", "court order",
        "antitrust", "consumer protection", "data privacy investigation",
    ],
    "customer_complaint": [
        "complaint", "complaints", "poor service", "bad service",
        "refund issue", "delay", "delayed", "cancelled", "canceled",
        "worst experience", "consumer complaint", "not resolved",
    ],
    "security_incident": [
        "data breach", "breach", "hack", "hacked", "cyber attack",
        "cyberattack", "ransomware", "data leak", "privacy breach",
        "customer data exposed",
    ],
    "layoff": [
        "layoff", "layoffs", "job cuts", "workforce reduction",
        "salary delay", "delayed pay", "delays pay", "unpaid wages",
        "pilot pay delayed", "pay delayed", "furlough", "restructuring",
    ],
    "fraud_allegation": [
        "fraud", "scam", "bribery", "corruption", "money laundering",
        "accounting irregularities", "embezzlement", "deceptive practices",
    ],
    "executive_controversy": [
        "ceo controversy", "founder controversy", "chairman controversy",
        "executive resigns", "ceo resigns", "leadership crisis",
        "board dispute", "executive misconduct", "ceo investigated",
    ],
}


ZERO_SHOT_TO_SIGNAL = {
    "environmental issue": "environmental",
    "social issue": "social",
    "governance issue": "governance",
    "product success": "product_success",
    "product failure": "product_failure",
    "investment": "investment",
    "withdrawal": "withdrawal",
    "regulatory action": "regulatory_action",
    "customer complaint": "customer_complaint",
    "security incident": "security_incident",
    "layoff": "layoff",
    "fraud allegation": "fraud_allegation",
    "executive controversy": "executive_controversy",
    "none": "none",
}


GENERIC_ESG_TERMS = {
    "sustainability",
    "sustainable",
    "esg",
    "corporate responsibility",
    "csr",
}


def contains_phrase(text: str, phrase: str) -> bool:
    return f" {normalize(phrase)} " in f" {normalize(text)} "


def classify_sdg_keywords(text: str, limit: int = 3) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rule in SDG_RULES:
        matched_terms = [
            keyword for keyword in rule["keywords"]
            if contains_phrase(text, keyword)
        ]
        if not matched_terms:
            continue
        matches.append({
            "code": rule["code"],
            "name": rule["name"],
            "pillar": rule["pillar"],
            "matched_terms": matched_terms,
            "score": len(matched_terms),
        })

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:limit]


def has_only_generic_esg_signal(text: str) -> bool:
    normalized = normalize(text)
    return any(f" {normalize(term)} " in f" {normalized} " for term in GENERIC_ESG_TERMS)


def classify_keywords(text: str) -> dict[str, Any]:
    matches = []
    for signal, terms in SIGNAL_KEYWORDS.items():
        matched_terms = [term for term in terms if contains_phrase(text, term)]
        if not matched_terms:
            continue
        confidence = min(0.75, 0.58 + 0.08 * len(matched_terms))
        matches.append({
            "signal": signal,
            "confidence": round(confidence, 3),
            "reason": f"Keyword matched: {', '.join(matched_terms[:4])}",
            "matched_terms": matched_terms,
            "source": "keyword_classifier",
        })

    matches.sort(key=lambda item: item["confidence"], reverse=True)
    return matches[0] if matches else {
        "signal": "none",
        "confidence": 0.0,
        "reason": "No reputation keyword matched",
        "matched_terms": [],
        "source": "keyword_classifier",
    }


def _from_zero_shot(payload: dict[str, Any]) -> dict[str, Any]:
    label = str(payload.get("label") or "none").lower()
    signal = ZERO_SHOT_TO_SIGNAL.get(label, "none")
    return {
        "signal": signal,
        "confidence": round(min(0.9, float(payload.get("confidence") or 0.0)), 3),
        "reason": f"Zero-shot label: {label}",
        "matched_terms": [],
        "source": "zero_shot_classifier",
        "zero_shot": payload,
    }


def classify_reputation_text(text: str) -> dict[str, Any]:
    keyword_result = classify_keywords(text)
    if keyword_result["confidence"] > 0.80:
        return {**keyword_result, "decision": "accept"}

    if keyword_result["confidence"] > 0.60:
        return {**keyword_result, "decision": "accept_with_warning"}

    # Runtime guard: do not run BART/Groq for every unrelated document. Enable
    # deeper verification only when you explicitly want it for weak candidates.
    if os.getenv("REPUTATION_ENABLE_DEEP_CLASSIFICATION", "false").lower() not in {"1", "true", "yes"}:
        return {
            **keyword_result,
            "decision": "reject",
        }

    zero_shot_result = _from_zero_shot(classify_zero_shot(text, SIGNAL_LABELS))
    if zero_shot_result["confidence"] > 0.80 and zero_shot_result["signal"] != "none":
        return {**zero_shot_result, "decision": "accept"}

    if zero_shot_result["confidence"] > 0.60 and zero_shot_result["signal"] != "none":
        return {**zero_shot_result, "decision": "accept_with_warning"}

    llm_result = verify_with_llm(text, prior_signal=keyword_result)
    if llm_result.get("signal") and llm_result.get("signal") != "none":
        return {**llm_result, "decision": "llm_verified"}

    return {
        **keyword_result,
        "decision": "reject",
    }
