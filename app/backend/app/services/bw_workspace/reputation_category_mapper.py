from __future__ import annotations

import re
from typing import Any


REPUTATION_SECTION_KEYS = [
    "fraud_signals",
    "layoff_signals",
    "executive_controversies",
    "security_incidents",
    "customer_complaints",
    "regulatory_signals",
    "product_signals",
    "esg_signals",
    "investment_signals",
]


SIGNAL_SECTION_MAP = {
    "fraud_allegation": "fraud_signals",
    "fraud_signal": "fraud_signals",
    "employee_wellbeing_risk": "layoff_signals",
    "layoff": "layoff_signals",
    "layoffs": "layoff_signals",
    "executive_change": "executive_controversies",
    "executive_controversy": "executive_controversies",
    "security_incident": "security_incidents",
    "security_signal": "security_incidents",
    "customer_complaint": "customer_complaints",
    "complaint_signal": "customer_complaints",
    "regulatory_action": "regulatory_signals",
    "regulatory_signal": "regulatory_signals",
    "product_success": "product_signals",
    "product_failure": "product_signals",
    "product_launch": "product_signals",
    "product_review": "product_signals",
    "product_comparison": "product_signals",
    "product_feature": "product_signals",
    "environmental": "esg_signals",
    "social": "esg_signals",
    "governance": "esg_signals",
    "esg_signal": "esg_signals",
    "investment": "investment_signals",
    "withdrawal": "investment_signals",
}


CATEGORY_EVIDENCE: dict[str, dict[str, Any]] = {
    "fraud_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 5,
        "terms": [
            "fraud", "corruption", "bribery", "money laundering", "embezzlement",
            "whistleblower", "forgery", "scam", "accounting irregularity", "misconduct",
        ],
    },
    "layoff_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 4,
        "terms": [
            "layoff", "layoffs", "job cut", "job cuts", "workforce reduction",
            "headcount", "retrenchment", "downsizing", "salary freeze", "severance",
            "restructuring", "unpaid wages",
        ],
    },
    "executive_controversies": {
        "min": 3,
        "verified_min": 4,
        "severity": 4,
        "terms": [
            "ceo", "founder", "chairman", "board", "executive", "director",
            "resignation", "resigns", "investigation", "misconduct", "controversy",
            "lawsuit", "arrest", "statement", "probe",
        ],
    },
    "security_incidents": {
        "min": 2,
        "verified_min": 3,
        "severity": 5,
        "terms": [
            "data breach", "breach", "cyber attack", "cyberattack", "hack",
            "hacked", "ransomware", "leak", "leaked", "privacy", "vulnerability",
            "malware", "phishing", "outage",
        ],
    },
    "customer_complaints": {
        "min": 2,
        "verified_min": 3,
        "severity": 3,
        "terms": [
            "complaint", "customer", "refund", "support", "service issue", "poor service",
            "unable to access", "not working", "glitch", "delay", "defect", "broken",
            "overheating", "battery drain", "portal down", "outage",
        ],
    },
    "regulatory_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 5,
        "terms": [
            "regulator", "regulatory", "court", "lawsuit", "fine", "penalty",
            "notice", "show cause", "investigation", "tax", "compliance",
            "government", "authority", "sebi", "sec", "ftc", "consumer court",
        ],
    },
    "product_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 3,
        "terms": [
            "product", "launch", "launched", "review", "rating", "feature", "specs",
            "glitch", "failure", "defect", "recall", "outage", "not working",
            "service disruption", "technical issue", "comparison", "benchmark",
        ],
    },
    "esg_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 2,
        "terms": [
            "sustainability", "sustainable", "net zero", "emissions", "climate",
            "renewable", "csr", "diversity", "inclusion", "governance", "ethics",
            "human rights", "community", "environment", "esg",
        ],
    },
    "investment_signals": {
        "min": 2,
        "verified_min": 3,
        "severity": 2,
        "terms": [
            "investment", "invest", "funding", "expansion", "acquisition", "stake",
            "dividend", "share buyback", "valuation", "ipo", "facility", "plant",
            "partnership", "joint venture", "capex", "deal",
        ],
    },
}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ").replace("-", " ")).casefold().strip()


def evidence_text(item: dict[str, Any]) -> str:
    return normalize_text(" ".join(
        str(item.get(key) or "")
        for key in [
            "title", "signal", "event", "snippet", "description", "summary",
            "reason", "classification", "category", "source_name",
        ]
    ))


def signal_section(item: dict[str, Any]) -> str:
    candidates = [
        item.get("signal"),
        item.get("detected_signal"),
        item.get("primary_signal"),
        item.get("classification"),
        item.get("category"),
        item.get("primary_category"),
    ]
    normalized_candidates = [normalize_text(value) for value in candidates if value]
    for value in normalized_candidates:
        compact = value.replace(" ", "_")
        if compact in SIGNAL_SECTION_MAP:
            return SIGNAL_SECTION_MAP[compact]
    for value in normalized_candidates:
        for signal, section in SIGNAL_SECTION_MAP.items():
            phrase = signal.replace("_", " ")
            if phrase and phrase in value:
                return section
    return ""


def evidence_identity(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip().casefold().rstrip("/")
    if url:
        return f"url:{url}"
    title = normalize_text(item.get("title") or item.get("signal") or item.get("snippet") or "")
    source = normalize_text(item.get("source") or item.get("source_name") or item.get("publisher") or "")
    return f"title:{source}:{title}" if title else ""


def score_category(item: dict[str, Any], section_key: str) -> dict[str, Any]:
    rule = CATEGORY_EVIDENCE.get(section_key) or {}
    terms = list(rule.get("terms") or [])
    text = evidence_text(item)
    signal = normalize_text(item.get("signal") or "")
    classification = normalize_text(item.get("classification") or item.get("category") or "")
    matched = [term for term in terms if term in text]
    score = len(matched)
    signal_matched_section = signal_section(item)
    if signal_matched_section == section_key:
        score += 10
    if signal and any(term in signal for term in terms):
        score += 2
    if classification and any(term in classification for term in terms):
        score += 1
    return {
        "section": section_key,
        "score": score,
        "matched_terms": matched[:6],
        "min": int(rule.get("min") or 1),
        "verified_min": int(rule.get("verified_min") or 2),
        "severity": int(rule.get("severity") or 1),
        "signal_matched": signal_matched_section == section_key,
    }


def choose_best_category(item: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        score_category(item, section_key)
        for section_key in REPUTATION_SECTION_KEYS
    ]
    candidates = [
        candidate
        for candidate in candidates
        if candidate["score"] >= candidate["min"]
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (
            int(bool(candidate.get("signal_matched"))),
            candidate["score"],
            candidate["severity"],
        ),
        reverse=True,
    )[0]
