from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from typing import Any

import numpy as np

from app.services.entity_resolution.embedding_matcher import get_model
from app.services.reputation_signals.brsr.brsr_mapper import map_brsr_signal
from app.services.reputation_signals.classifiers.llm_verifier import (
    verify_batch_with_llm,
    verify_category_with_llm,
)
from app.services.reputation_signals.classifiers.zero_shot_classifier import classify_zero_shot
from app.services.reputation_signals.reputation_common import (
    dedupe_items,
    evidence_card,
    group_incident_items,
    normalize,
    text_for_item,
)
from app.services.reputation_signals.sdg.sdg_mapper import map_sdg_terms
from app.services.reputation_signals.sdg.sdg_rules import SDG_RULES


CATEGORY_CONFIG: dict[str, dict[str, Any]] = {
    "product": {
        "title": "Product Failures / Successes",
        "description": "Material positive or negative reputation developments involving a product or service.",
        "signals": [
            "product_success",
            "product_failure",
            "product_launch",
            "product_review",
            "product_comparison",
            "product_feature",
        ],
        "limit": 8,
    },
    "esg": {
        "title": "ESG Issues",
        "description": "Environmental, social, or governance conduct and impact involving the entity.",
        "signals": ["environmental", "social", "governance"],
        "limit": 12,
    },
    "investments": {
        "title": "Investments & Withdrawals",
        "description": "Material allocation or withdrawal of company capital, assets, capacity, or strategic operations.",
        "signals": ["investment", "withdrawal"],
        "limit": 8,
    },
    "regulatory": {
        "title": "Regulatory Actions",
        "description": "Material legal, regulatory, enforcement, court, or compliance action involving the entity.",
        "signals": ["regulatory_action"],
        "limit": 8,
    },
    "complaints": {
        "title": "Customer Complaints",
        "description": "A genuine customer-reported negative experience involving the entity's product or service.",
        "signals": ["customer_complaint"],
        "limit": 8,
    },
    "security": {
        "title": "Security Incidents",
        "description": "A material cybersecurity, information security, data protection, or privacy incident.",
        "signals": ["security_incident"],
        "limit": 8,
    },
    "layoffs": {
        "title": "Layoffs & Employee Well-being",
        "description": "A material workforce reduction, employment disruption, compensation problem, or employee welfare risk.",
        "signals": ["layoff"],
        "limit": 8,
    },
    "fraud": {
        "title": "Fraud Allegations",
        "description": "A credible allegation or finding of fraud, corruption, deception, or financial misconduct.",
        "signals": ["fraud_allegation"],
        "limit": 8,
    },
    "executive": {
        "title": "Executive Controversies",
        "description": "A material senior leadership or board change, dispute, investigation, or controversy.",
        "signals": ["executive_change", "executive_controversy"],
        "limit": 8,
    },
}


DISPLAY_SIGNAL = {
    "regulatory_action": "regulatory_signal",
    "layoff": "employee_wellbeing_risk",
}


GROUPED_CATEGORIES = {
    "regulatory",
    "complaints",
    "security",
    "layoffs",
    "fraud",
    "executive",
}

SIGNAL_TO_CATEGORY = {
    signal: category
    for category, config in CATEGORY_CONFIG.items()
    for signal in config["signals"]
}

PRODUCT_SCOPE_CATEGORIES = {"product", "complaints", "security", "regulatory"}
COMPANY_SCOPE_CATEGORIES = {
    "esg",
    "investments",
    "regulatory",
    "security",
    "layoffs",
    "fraud",
    "executive",
}

_CLASSIFICATION_CACHE: dict[str, dict[str, Any]] = {}
_CLASSIFICATION_CACHE_LOCK = threading.RLock()
_CLASSIFICATION_CACHE_VERSION = "pooled-v7-batch-parser-primary-category"

HIGH_RISK_SIGNAL_EVIDENCE = {
    "regulatory_action": [
        "regulator", "regulatory", "court", "lawsuit", "legal action",
        "fine", "penalty", "investigation", "enforcement", "compliance notice",
        "government order", "authority", "tribunal", "settlement", "sued",
        "legal notice", "show cause notice",
    ],
    "security_incident": [
        "data breach", "cyber attack", "cyberattack", "hacked", "hackers",
        "vulnerability", "security flaw", "data leak", "privacy breach",
        "ransomware", "malware", "exploit", "breached", "leaked data",
    ],
    "fraud_allegation": [
        "fraud", "fraudulent", "bribery", "corruption", "money laundering",
        "embezzlement", "scam allegation", "charged with fraud",
    ],
    "layoff": [
        "layoff", "layoffs", "job cuts", "workforce reduction",
        "redundancies", "retrenchment", "salary delay", "unpaid wages",
        "laid off", "cuts jobs",
    ],
}

EXECUTIVE_ROLE_TERMS = [
    "ceo", "chief executive", "chairman", "chairwoman", "founder", "president",
    "cfo", "coo", "board member", "director", "executive",
]

EXECUTIVE_EVENT_TERMS = [
    "resign", "resignation", "appointed", "appointment", "removed", "ousted",
    "investigation", "controversy", "scandal", "dispute", "charged", "arrested",
    "succession", "leadership change",
]

ZERO_SHOT_FALLBACK_CATEGORIES = {"product", "complaints"}

COMPLAINT_EVIDENCE_TERMS = [
    "issue", "problem", "refund", "heating", "overheating", "battery drain",
    "defect", "defective", "broken", "complaint", "customer service",
    "poor service", "not working", "stopped working", "wasted my money",
    "disappointed", "worst experience", "replacement", "repair",
]


def _threshold(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _entity_context(profile: dict[str, Any], category: str) -> dict[str, Any]:
    identity = profile.get("_reputation_identity") or {}
    company = identity.get("company") or profile.get("competitor_company") or ""
    product = identity.get("product") or profile.get("competitor_product") or ""
    product_categories = set(identity.get("product_validated_categories") or [])
    target = product if product and category in product_categories else company
    return {
        "entity_type": identity.get("entity_type") or profile.get("entity_type") or "",
        "company": company,
        "product": product,
        "validation_mode": "product" if product and category in product_categories else "company",
        "validation_target": target,
        "aliases": profile.get("aliases") or [],
        "product_aliases": identity.get("product_aliases") or profile.get("product_aliases") or [],
    }


def _validation_mode(item: dict[str, Any], profile: dict[str, Any], category: str) -> str:
    mode = str(item.get("validation_mode") or "").strip().lower()
    if mode in {"product", "company"}:
        return mode
    return str(_entity_context(profile, category).get("validation_mode") or "company")


def _compatible_categories(item: dict[str, Any], profile: dict[str, Any], category: str) -> set[str]:
    mode = _validation_mode(item, profile, category)
    if mode == "product":
        return set(PRODUCT_SCOPE_CATEGORIES)
    return set(COMPANY_SCOPE_CATEGORIES)


def _zero_shot_result(category: str, text: str) -> dict[str, Any]:
    config = CATEGORY_CONFIG[category]
    relevant_label = f"relevant {config['title'].lower()} event"
    unrelated_label = f"not a {config['title'].lower()} event"
    labels = [relevant_label, unrelated_label]
    payload = classify_zero_shot(text, labels)
    label = str(payload.get("label") or "")
    signal = "category_relevant" if label == relevant_label else "none"
    return {
        "signal": signal,
        "confidence": float(payload.get("confidence") or 0.0),
        "reason": f"Zero-shot semantic label: {label or 'none'}",
        "concepts": [],
        "source": "zero_shot_classifier",
        "zero_shot": payload,
    }


def _embedding_relevance(category: str, text: str) -> dict[str, Any]:
    if os.getenv("REPUTATION_ENABLE_EMBEDDING_PREFILTER", "true").lower() not in {"1", "true", "yes"}:
        return {
            "available": False,
            "score": 0.0,
            "relevant": False,
            "reason": "embedding_prefilter_disabled",
        }
    try:
        model = get_model()
        category_text = (
            f"{CATEGORY_CONFIG[category]['title']}. "
            f"{CATEGORY_CONFIG[category]['description']}"
        )
        vectors = model.encode(
            [category_text, text[:1200]],
            normalize_embeddings=True,
        )
        score = float(np.dot(vectors[0], vectors[1]))
        threshold = _threshold("REPUTATION_EMBEDDING_RELEVANCE_THRESHOLD", "0.22")
        return {
            "available": True,
            "score": round(score, 4),
            "relevant": score >= threshold,
            "threshold": threshold,
            "reason": "generic_category_embedding_similarity",
        }
    except Exception as exc:
        print(f"[REPUTATION] Embedding relevance unavailable: {exc}")
        return {
            "available": False,
            "score": 0.0,
            "relevant": False,
            "reason": str(exc),
        }


def _embedding_relevance_for_categories(
    categories: set[str],
    text: str,
) -> dict[str, Any]:
    if os.getenv("REPUTATION_ENABLE_EMBEDDING_PREFILTER", "true").lower() not in {"1", "true", "yes"}:
        return {
            "available": False,
            "score": 0.0,
            "relevant": False,
            "reason": "embedding_prefilter_disabled",
        }
    try:
        ordered = [category for category in CATEGORY_CONFIG if category in categories]
        category_texts = [
            f"{CATEGORY_CONFIG[category]['title']}. {CATEGORY_CONFIG[category]['description']}"
            for category in ordered
        ]
        model = get_model()
        vectors = model.encode(
            [*category_texts, text[:1200]],
            normalize_embeddings=True,
        )
        article_vector = vectors[-1]
        scores = {
            category: round(float(np.dot(vectors[index], article_vector)), 4)
            for index, category in enumerate(ordered)
        }
        best_category = max(scores, key=scores.get) if scores else ""
        best_score = scores.get(best_category, 0.0)
        threshold = _threshold("REPUTATION_EMBEDDING_LLM_THRESHOLD", "0.15")
        return {
            "available": True,
            "score": best_score,
            "relevant": best_score >= threshold,
            "threshold": threshold,
            "best_category": best_category,
            "category_scores": scores,
            "reason": "pooled_category_embedding_similarity",
        }
    except Exception as exc:
        print(f"[REPUTATION] Pooled embedding relevance unavailable: {exc}")
        return {
            "available": False,
            "score": 0.0,
            "relevant": False,
            "reason": str(exc),
        }


def _pooled_zero_shot_result(text: str) -> dict[str, Any]:
    relevant_label = "material reputation intelligence event"
    unrelated_label = "not a material reputation intelligence event"
    payload = classify_zero_shot(text, [relevant_label, unrelated_label])
    label = str(payload.get("label") or "")
    return {
        "signal": "reputation_relevant" if label == relevant_label else "none",
        "confidence": float(payload.get("confidence") or 0.0),
        "reason": f"Zero-shot semantic label: {label or 'none'}",
        "source": "zero_shot_classifier",
        "zero_shot": payload,
    }


def _pooled_entity_context(
    profile: dict[str, Any],
    validation_modes: set[str],
    source_categories: set[str],
) -> dict[str, Any]:
    identity = profile.get("_reputation_identity") or {}
    return {
        "entity_type": identity.get("entity_type") or profile.get("entity_type") or "",
        "company": identity.get("company") or profile.get("competitor_company") or "",
        "product": identity.get("product") or profile.get("competitor_product") or "",
        "validation_modes": sorted(validation_modes),
        "source_categories": sorted(source_categories),
        "aliases": profile.get("aliases") or [],
        "product_aliases": identity.get("product_aliases") or profile.get("product_aliases") or [],
    }


def _categories_for_validation_modes(validation_modes: set[str]) -> set[str]:
    categories: set[str] = set()
    if "product" in validation_modes:
        categories.update(PRODUCT_SCOPE_CATEGORIES)
    if "company" in validation_modes or not validation_modes:
        categories.update(COMPANY_SCOPE_CATEGORIES)
    return categories


def _embedding_threshold_for_entry(
    validation_modes: set[str],
    source_categories: set[str],
) -> float:
    product_categories = {"product", "complaints", "security"}
    if "product" in validation_modes and source_categories.intersection(product_categories):
        return _threshold("REPUTATION_PRODUCT_EMBEDDING_LLM_THRESHOLD", "0.05")
    return _threshold("REPUTATION_EMBEDDING_LLM_THRESHOLD", "0.15")


def _contains_evidence_phrase(text: str, phrases: list[str]) -> bool:
    normalized_text = f" {normalize(text)} "
    return any(
        normalized_phrase and f" {normalized_phrase} " in normalized_text
        for normalized_phrase in (normalize(phrase) for phrase in phrases)
    )


def _signal_is_grounded(signal: str, text: str) -> tuple[bool, str]:
    if signal == "customer_complaint":
        grounded = _contains_evidence_phrase(text, COMPLAINT_EVIDENCE_TERMS)
        return grounded, (
            "grounded_in_article_text"
            if grounded
            else "customer_complaint_missing_negative_experience_evidence"
        )
    phrases = HIGH_RISK_SIGNAL_EVIDENCE.get(signal)
    if phrases is not None:
        grounded = _contains_evidence_phrase(text, phrases)
        return grounded, (
            "grounded_in_article_text"
            if grounded
            else f"{signal}_missing_article_evidence"
        )
    if signal in {"executive_change", "executive_controversy"}:
        grounded = (
            _contains_evidence_phrase(text, EXECUTIVE_ROLE_TERMS)
            and _contains_evidence_phrase(text, EXECUTIVE_EVENT_TERMS)
        )
        return grounded, (
            "grounded_in_article_text"
            if grounded
            else "executive_signal_missing_role_or_event_evidence"
        )
    return True, "grounding_not_required"


def _select_primary_classification(
    classifications: list[dict[str, Any]],
    source_categories: set[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not classifications:
        return None, []

    def rank(value: dict[str, Any]) -> tuple[float, int, str]:
        destination = SIGNAL_TO_CATEGORY.get(str(value.get("signal") or ""), "")
        return (
            float(value.get("confidence") or 0.0),
            int(destination in source_categories),
            destination,
        )

    ordered = sorted(classifications, key=rank, reverse=True)
    return ordered[0], ordered[1:]


def _related_mention(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "title": item.get("title") or item.get("snippet") or "Related mention",
        "source": item.get("source") or "",
        "source_name": (
            item.get("source_name")
            or item.get("publisher")
            or item.get("channel")
            or ""
        ),
        "url": item.get("url") or "",
        "published_at": item.get("published_at") or "",
        "snippet": str(
            item.get("snippet")
            or item.get("description")
            or item.get("body_text")
            or ""
        )[:260],
        "evidence_origin": item.get("evidence_origin") or "",
        "classification_status": "unverified_related_mention",
        "reason": reason,
    }


def _empty_category_section(category: str) -> dict[str, Any]:
    config = CATEGORY_CONFIG[category]
    section = {
        "title": config["title"],
        "items": [],
        "count": 0,
        "classification_rejections": [],
        "cross_category_items": [],
        "related_mentions": [],
        "summary": f"No direct {config['title'].lower()} signal found in temporary live evidence.",
    }
    return _refresh_counts(category, section)


def _pooled_item_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return f"url:{url}"
    normalized_title = normalize(str(item.get("title") or ""))
    if not normalized_title:
        return ""
    source = normalize(str(
        item.get("source_name")
        or item.get("publisher")
        or item.get("channel")
        or item.get("source")
        or ""
    ))
    published_at = str(item.get("published_at") or "").strip()[:10]
    return f"title:{normalized_title}|source:{source}|date:{published_at}"


def _compact_article_for_llm(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    source = str(
        item.get("source_name")
        or item.get("publisher")
        or item.get("channel")
        or item.get("source")
        or ""
    ).strip()
    summary = str(
        item.get("snippet")
        or item.get("description")
        or item.get("body_text")
        or ""
    ).strip()
    summary_limit = max(200, int(os.getenv("REPUTATION_GROQ_SUMMARY_CHARS", "400")))
    return "\n".join([
        f"Title: {title[:300]}",
        f"Summary: {summary[:summary_limit]}",
        f"Source: {source[:120]}",
    ])


def _classification_cache_key(
    item: dict[str, Any],
    profile: dict[str, Any],
    validation_modes: set[str],
    allowed_signals: list[str],
) -> str:
    identity = profile.get("_reputation_identity") or {}
    payload = {
        "version": _CLASSIFICATION_CACHE_VERSION,
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "article": _pooled_item_key(item),
        "text": _compact_article_for_llm(item),
        "company": identity.get("company") or profile.get("competitor_company") or "",
        "product": identity.get("product") or profile.get("competitor_product") or "",
        "validation_modes": sorted(validation_modes),
        "allowed_signals": sorted(allowed_signals),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cached_classification(key: str) -> dict[str, Any] | None:
    ttl_seconds = max(0, int(os.getenv("REPUTATION_CLASSIFICATION_CACHE_TTL_SECONDS", "604800")))
    with _CLASSIFICATION_CACHE_LOCK:
        cached = _CLASSIFICATION_CACHE.get(key)
        if not cached:
            return None
        if ttl_seconds and time.time() - float(cached.get("created_at") or 0.0) > ttl_seconds:
            _CLASSIFICATION_CACHE.pop(key, None)
            return None
        result = copy.deepcopy(cached["result"])
    original_usage = result.get("groq_usage") or {}
    result["groq_usage"] = {
        "requests": 0,
        "cached_hits": 1,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "duration_ms": 0.0,
        "model": original_usage.get("model") or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "success": True,
        "cache_key": key,
    }
    result["classification_cache_hit"] = True
    return result


def _store_cached_classification(key: str, result: dict[str, Any]) -> None:
    if not result.get("llm_verified"):
        return
    max_entries = max(1, int(os.getenv("REPUTATION_CLASSIFICATION_CACHE_MAX_ENTRIES", "2048")))
    with _CLASSIFICATION_CACHE_LOCK:
        if len(_CLASSIFICATION_CACHE) >= max_entries:
            oldest_key = min(
                _CLASSIFICATION_CACHE,
                key=lambda value: float(_CLASSIFICATION_CACHE[value].get("created_at") or 0.0),
            )
            _CLASSIFICATION_CACHE.pop(oldest_key, None)
        _CLASSIFICATION_CACHE[key] = {
            "created_at": time.time(),
            "result": copy.deepcopy(result),
        }


def _add_usage(total: dict[str, Any], usage: dict[str, Any]) -> None:
    for field in [
        "requests",
        "cached_hits",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "rate_limit_retries",
    ]:
        total[field] += int(usage.get(field) or 0)
    total["duration_ms"] += float(usage.get("duration_ms") or 0.0)
    if usage.get("success") is False:
        total["failed_requests"] += 1


def analyze_signal_categories(
    evidence: dict[str, list[dict[str, Any]]],
    profile: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    sections = {
        category: _empty_category_section(category)
        for category in CATEGORY_CONFIG
    }
    pooled: dict[str, dict[str, Any]] = {}
    for source_category, items in evidence.items():
        if source_category not in CATEGORY_CONFIG:
            continue
        for item in items or []:
            key = _pooled_item_key(item)
            if not key:
                continue
            entry = pooled.setdefault(key, {
                "item": item,
                "source_categories": set(),
                "validation_modes": set(),
            })
            entry["source_categories"].add(source_category)
            mode = str(item.get("validation_mode") or "").strip().lower()
            if mode in {"product", "company"}:
                entry["validation_modes"].add(mode)

    llm_calls = 0
    cache_hits = 0
    embedding_rejections = 0
    accepted_signals = 0
    rejected_signals = 0
    groq_usage = {
        "requests": 0,
        "cached_hits": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "rate_limit_retries": 0,
        "duration_ms": 0.0,
        "failed_requests": 0,
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
    }
    groq_events = []
    groq_batch_events = []
    prepared_by_key: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for article_index, (article_key, entry) in enumerate(pooled.items(), start=1):
        item = entry["item"]
        source_categories = set(entry["source_categories"])
        validation_modes = set(entry["validation_modes"])
        compatible_categories = _categories_for_validation_modes(validation_modes)
        text = text_for_item(item)
        embedding = _embedding_relevance_for_categories(compatible_categories, text)
        entry_embedding_threshold = _embedding_threshold_for_entry(
            validation_modes,
            source_categories,
        )
        embedding["threshold"] = entry_embedding_threshold
        embedding["relevant"] = (
            not embedding.get("available")
            or float(embedding.get("score") or 0.0) >= entry_embedding_threshold
        )
        zero_shot = _pooled_zero_shot_result(text) if embedding["relevant"] else {}
        allowed_signals = [
            signal
            for category in CATEGORY_CONFIG
            if category in compatible_categories
            for signal in CATEGORY_CONFIG[category]["signals"]
        ]
        prior = {
            **zero_shot,
            "embedding": embedding,
            "classification_mode": "batched_llm_per_unique_article",
        }
        cache_key = _classification_cache_key(
            item,
            profile,
            validation_modes,
            allowed_signals,
        )
        prepared = {
            "article_key": article_key,
            "entry": entry,
            "item": item,
            "source_categories": source_categories,
            "validation_modes": validation_modes,
            "compatible_categories": compatible_categories,
            "text": text,
            "embedding": embedding,
            "zero_shot": zero_shot,
            "allowed_signals": allowed_signals,
            "prior": prior,
            "cache_key": cache_key,
            "llm_result": None,
        }
        prepared_by_key[article_key] = prepared
        if not embedding["relevant"]:
            continue
        cached = _cached_classification(cache_key)
        if cached is not None:
            prepared["llm_result"] = cached
            cache_hits += 1
            continue
        request_id = f"a{article_index}"
        prepared["request_id"] = request_id
        pending.append({
            "id": request_id,
            "text": _compact_article_for_llm(item),
            "allowed_signals": allowed_signals,
            "entity_context": {
                **_pooled_entity_context(
                    profile,
                    validation_modes,
                    source_categories,
                ),
                "allowed_signal_categories": {
                    signal: SIGNAL_TO_CATEGORY[signal]
                    for signal in allowed_signals
                },
            },
            "prior_signal": prior,
            "prepared": prepared,
        })

    batch_size = max(1, int(os.getenv("REPUTATION_GROQ_BATCH_SIZE", "2")))
    batch_count = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        batch_count += 1
        batch_results, batch_usage = verify_batch_with_llm(batch)
        _add_usage(groq_usage, batch_usage)
        llm_calls += int(int(batch_usage.get("requests") or 0) > 0)
        groq_batch_events.append({
            "batch": batch_count,
            "article_count": len(batch),
            "article_ids": [str(request["id"]) for request in batch],
            "usage": batch_usage,
        })
        for request in batch:
            prepared = request["prepared"]
            result = batch_results.get(str(request["id"])) or {
                **prepared["prior"],
                "signal": "none",
                "confidence": 0.0,
                "reason": "Missing result from Groq batch response",
                "classifications": [],
                "semantic_rejections": [],
                "source": "groq_batch_verifier",
                "llm_verified": False,
                "llm_available": False,
            }
            result["groq_usage"] = {
                "requests": 0,
                "cached_hits": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "rate_limit_retries": 0,
                "duration_ms": 0.0,
                "model": batch_usage.get("model") or groq_usage["model"],
                "success": bool(batch_usage.get("success")),
                "batch": batch_count,
            }
            prepared["llm_result"] = result
            prepared["batch"] = batch_count
            _store_cached_classification(prepared["cache_key"], result)

    for article_key, entry in pooled.items():
        prepared = prepared_by_key[article_key]
        item = prepared["item"]
        source_categories = prepared["source_categories"]
        validation_modes = prepared["validation_modes"]
        compatible_categories = prepared["compatible_categories"]
        text = prepared["text"]
        embedding = prepared["embedding"]
        entry_embedding_threshold = float(embedding.get("threshold") or 0.15)
        if (
            embedding.get("available")
            and float(embedding.get("score") or 0.0)
            < entry_embedding_threshold
        ):
            embedding_rejections += 1
            for category in source_categories:
                sections[category]["classification_rejections"].append({
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "source": item.get("source") or "",
                    "classification_result": "rejected",
                    "reason": "embedding_relevance_below_llm_threshold",
                    "detected_signal": "none",
                    "confidence": float(embedding.get("score") or 0.0),
                    "classification_source": "embedding_prefilter",
                    "embedding": embedding,
                    "zero_shot": {},
                })
                sections[category]["related_mentions"].append(
                    _related_mention(item, "Below semantic classification threshold")
                )
            continue

        zero_shot = prepared["zero_shot"]
        allowed_signals = prepared["allowed_signals"]
        llm_result = prepared["llm_result"] or {
            **prepared["prior"],
            "signal": "none",
            "confidence": 0.0,
            "reason": "Groq batch classification unavailable",
            "classifications": [],
            "semantic_rejections": [],
            "source": "groq_batch_verifier",
            "llm_verified": False,
            "llm_available": False,
        }
        usage = llm_result.get("groq_usage") or {}
        groq_events.append({
            "article_key": _pooled_item_key(item),
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "evidence_origin": item.get("evidence_origin") or "",
            "source_categories": sorted(source_categories),
            "validation_modes": sorted(validation_modes),
            "cache_hit": bool(llm_result.get("classification_cache_hit")),
            "batch": prepared.get("batch"),
            "usage": usage,
            "signals_returned": [
                value.get("signal")
                for value in llm_result.get("classifications") or []
                if isinstance(value, dict)
            ],
            "semantic_rejections": llm_result.get("semantic_rejections") or [],
        })
        threshold = _threshold("REPUTATION_LLM_ACCEPT_THRESHOLD", "0.65")
        classifications = []
        grounding_rejections = []
        filter_rejections = []
        for value in llm_result.get("classifications") or []:
            signal = str(value.get("signal") or "")
            confidence = float(value.get("confidence") or 0.0)
            if signal not in allowed_signals:
                filter_rejections.append({
                    "signal": signal or "none",
                    "confidence": confidence,
                    "reason": "signal_not_allowed_for_article_scope",
                })
                continue
            if signal not in SIGNAL_TO_CATEGORY:
                filter_rejections.append({
                    "signal": signal or "none",
                    "confidence": confidence,
                    "reason": "unknown_signal_mapping",
                })
                continue
            if confidence < threshold:
                filter_rejections.append({
                    "signal": signal,
                    "confidence": confidence,
                    "threshold": threshold,
                    "reason": "confidence_below_threshold",
                })
                continue
            grounded, grounding_reason = _signal_is_grounded(signal, text)
            if not grounded:
                grounding_rejections.append({
                    "signal": signal,
                    "reason": grounding_reason,
                    "confidence": confidence,
                })
                continue
            classifications.append(value)
        if groq_events:
            groq_events[-1]["filter_rejections"] = filter_rejections
            groq_events[-1]["grounding_rejections"] = grounding_rejections
        if not llm_result.get("llm_verified"):
            zero_shot_threshold = _threshold("REPUTATION_ZERO_SHOT_ACCEPT_THRESHOLD", "0.65")
            if (
                zero_shot.get("zero_shot", {}).get("available")
                and zero_shot.get("signal") != "none"
                and float(zero_shot.get("confidence") or 0.0) >= zero_shot_threshold
            ):
                for category in source_categories:
                    if category not in ZERO_SHOT_FALLBACK_CATEGORIES:
                        continue
                    signals = CATEGORY_CONFIG[category]["signals"]
                    if len(signals) == 1 and category in compatible_categories:
                        classifications.append({
                            "signal": signals[0],
                            "confidence": float(zero_shot.get("confidence") or 0.0),
                            "reason": "Groq unavailable; accepted by pooled zero-shot relevance",
                            "concepts": [],
                        })
        primary_classification, secondary_classifications = _select_primary_classification(
            classifications,
            source_categories,
        )
        if groq_events:
            groq_events[-1]["accepted_classifications"] = [
                {
                    "signal": value.get("signal"),
                    "confidence": value.get("confidence"),
                    "destination": SIGNAL_TO_CATEGORY.get(value.get("signal")),
                }
                for value in classifications
                if isinstance(value, dict)
            ]
            groq_events[-1]["selected_primary"] = (
                {
                    "signal": primary_classification.get("signal"),
                    "confidence": primary_classification.get("confidence"),
                    "destination": SIGNAL_TO_CATEGORY.get(primary_classification.get("signal")),
                }
                if primary_classification
                else None
            )
        accepted_signals += int(primary_classification is not None)
        if primary_classification is None:
            rejected_signals += 1

        routed_categories: set[str] = set()
        if primary_classification is not None:
            destination = SIGNAL_TO_CATEGORY[primary_classification["signal"]]
            classification = {
                **primary_classification,
                "category": destination,
            }
            routed_categories.add(destination)
            card = _build_card(destination, item, {
                **llm_result,
                **classification,
                "decision": (
                    "llm_verified"
                    if llm_result.get("llm_verified")
                    else "zero_shot_fallback"
                ),
                "embedding": embedding,
                "zero_shot": zero_shot.get("zero_shot") or {},
            })
            card["article_id"] = _pooled_item_key(item)
            card["primary_category"] = destination
            card["secondary_categories"] = [
                SIGNAL_TO_CATEGORY[value["signal"]]
                for value in secondary_classifications
                if value.get("signal") in SIGNAL_TO_CATEGORY
            ]
            card["secondary_signals"] = [
                value.get("signal")
                for value in secondary_classifications
                if value.get("signal")
            ]
            if destination not in source_categories:
                card["cross_category_origin"] = ",".join(sorted(source_categories))
                card["cross_category_destination"] = destination
                sections[destination]["accepted_cross_category"] = [
                    *(sections[destination].get("accepted_cross_category") or []),
                    {
                        "title": card.get("title") or "",
                        "url": card.get("url") or "",
                        "signal": classification["signal"],
                        "origin": sorted(source_categories),
                    },
                ]
            sections[destination]["items"].append(card)

        for category in source_categories:
            if category in routed_categories:
                continue
            sections[category]["classification_rejections"].append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "",
                "classification_result": "rejected",
                "reason": llm_result.get("reason") or "no_supported_signal_for_source_category",
                "detected_signal": llm_result.get("signal") or "none",
                "confidence": float(llm_result.get("confidence") or 0.0),
                "classification_source": llm_result.get("source") or "",
                "embedding": embedding,
                "zero_shot": zero_shot.get("zero_shot") or {},
                "grounding_rejections": grounding_rejections,
            })
            sections[category]["related_mentions"].append(
                _related_mention(
                    item,
                    llm_result.get("reason") or "No verified signal returned",
                )
            )

    for category, section in sections.items():
        limit = int(CATEGORY_CONFIG[category].get("limit") or 8)
        if category in GROUPED_CATEGORIES:
            section["items"] = group_incident_items(section["items"], limit)
        else:
            section["items"] = dedupe_items(section["items"], limit)
        section["count"] = len(section["items"])
        section["related_mentions"] = (
            dedupe_items(section.get("related_mentions") or [], 5)
            if not section["count"]
            else []
        )
        section["summary"] = (
            f"Found {section['count']} {section['title'].lower()} signal(s)."
            if section["count"] else
            f"No direct {section['title'].lower()} signal found in temporary live evidence."
        )
        sections[category] = _refresh_counts(category, section)

    sections["_classification_run"] = {
        "mode": "batched_llm_per_unique_article",
        "cache": "temporary_in_memory",
        "cache_ttl_seconds": max(
            0,
            int(os.getenv("REPUTATION_CLASSIFICATION_CACHE_TTL_SECONDS", "604800")),
        ),
        "unique_articles": len(pooled),
        "embedding_rejected": embedding_rejections,
        "groq_calls": llm_calls,
        "groq_http_requests": groq_usage["requests"],
        "cached_hits": cache_hits,
        "prompt_tokens": groq_usage["prompt_tokens"],
        "completion_tokens": groq_usage["completion_tokens"],
        "total_tokens": groq_usage["total_tokens"],
        "groq_duration_ms": round(groq_usage["duration_ms"], 2),
        "failed_requests": groq_usage["failed_requests"],
        "rate_limit_retries": groq_usage["rate_limit_retries"],
        "accepted_signals": accepted_signals,
        "rejected_signals": rejected_signals,
        "routing": "one_primary_category_per_article",
        "batch_size": batch_size,
        "batch_count": batch_count,
        "groq_articles_classified": len(pending),
        "groq_usage": {
            **groq_usage,
            "duration_ms": round(groq_usage["duration_ms"], 2),
        },
        "groq_events": groq_events,
        "groq_batch_events": groq_batch_events,
        "embedding_threshold": _threshold("REPUTATION_EMBEDDING_LLM_THRESHOLD", "0.15"),
        "product_embedding_threshold": _threshold(
            "REPUTATION_PRODUCT_EMBEDDING_LLM_THRESHOLD",
            "0.05",
        ),
        "llm_accept_threshold": _threshold("REPUTATION_LLM_ACCEPT_THRESHOLD", "0.65"),
    }
    print(
        "[REPUTATION][CLASSIFICATION] "
        f"unique_articles={len(pooled)} "
        f"embedding_rejected={embedding_rejections} "
        f"groq_calls={llm_calls} "
        f"groq_http_requests={groq_usage['requests']} "
        f"cache_hits={cache_hits} "
        f"tokens={groq_usage['total_tokens']}"
    )
    return sections


def classify_signal_item(
    category: str,
    item: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    config = CATEGORY_CONFIG[category]
    text = text_for_item(item)
    embedding = _embedding_relevance(category, text)
    zero_shot = _zero_shot_result(category, text)
    accept_threshold = _threshold("REPUTATION_ZERO_SHOT_ACCEPT_THRESHOLD", "0.65")
    llm_threshold = _threshold("REPUTATION_ZERO_SHOT_LLM_THRESHOLD", "0.35")
    signal = zero_shot["signal"]
    confidence = zero_shot["confidence"]

    prior = {
        **zero_shot,
        "embedding": embedding,
        "zero_shot_accept_threshold": accept_threshold,
        "zero_shot_llm_threshold": llm_threshold,
    }
    compatible_categories = _compatible_categories(item, profile, category)
    allowed_signals = [
        signal
        for allowed_category in compatible_categories
        for signal in CATEGORY_CONFIG[allowed_category]["signals"]
    ]
    llm_result = verify_category_with_llm(
        _compact_article_for_llm(item),
        category=category,
        allowed_signals=allowed_signals,
        entity_context=_entity_context(profile, category),
        prior_signal=prior,
    )
    llm_accept_threshold = _threshold("REPUTATION_LLM_ACCEPT_THRESHOLD", "0.65")
    accepted_classifications = [
        value
        for value in llm_result.get("classifications") or []
        if (
            value.get("signal") in allowed_signals
            and value.get("signal") in SIGNAL_TO_CATEGORY
            and float(value.get("confidence") or 0.0) >= llm_accept_threshold
            and _signal_is_grounded(str(value.get("signal") or ""), text)[0]
        )
    ]
    primary_classifications = [
        value
        for value in accepted_classifications
        if SIGNAL_TO_CATEGORY.get(value.get("signal")) == category
    ]
    cross_classifications = [
        value
        for value in accepted_classifications
        if SIGNAL_TO_CATEGORY.get(value.get("signal")) != category
    ]
    if llm_result.get("llm_verified") and primary_classifications:
        primary = primary_classifications[0]
        return {
            **llm_result,
            **primary,
            "decision": "llm_verified",
            "cross_classifications": cross_classifications,
            "embedding": embedding,
            "zero_shot": zero_shot.get("zero_shot"),
        }

    if llm_result.get("llm_verified"):
        return {
            **llm_result,
            "decision": "reject",
            "cross_classifications": cross_classifications,
            "embedding": embedding,
            "zero_shot": zero_shot.get("zero_shot"),
        }

    if (
        zero_shot.get("zero_shot", {}).get("available")
        and signal != "none"
        and confidence >= accept_threshold
    ):
        fallback_signal = (
            config["signals"][0]
            if len(config["signals"]) == 1 and category in ZERO_SHOT_FALLBACK_CATEGORIES
            else ""
        )
        if fallback_signal:
            return {
                **prior,
                "signal": fallback_signal,
                "decision": "zero_shot_fallback",
                "reason": "Groq unavailable; accepted by zero-shot category relevance",
            }
    return {
        **llm_result,
        "decision": "reject",
        "embedding": embedding,
        "zero_shot": zero_shot.get("zero_shot"),
    }


def _mapping_signal(signal: str) -> str:
    if signal in {"executive_change", "executive_controversy"}:
        return "executive_controversy"
    return signal


def _build_card(
    category: str,
    item: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    raw_signal = str(classification.get("signal") or "none")
    mapping_signal = _mapping_signal(raw_signal)
    concepts = [
        str(value).strip()
        for value in classification.get("concepts") or []
        if str(value).strip()
    ]
    sdgs = map_sdg_terms(concepts, mapping_signal)
    display_signal = DISPLAY_SIGNAL.get(raw_signal, raw_signal)
    extra: dict[str, Any] = {
        "classification_signal": raw_signal,
        "classification_category": classification.get("category") or category,
        "semantic_basis": classification.get("semantic_basis") or "",
        "evidence_origin": item.get("evidence_origin") or "",
        "stored_evidence": bool(item.get("stored_evidence")),
        "live_evidence": bool(item.get("live_evidence")),
        "classification_source": classification.get("source") or "",
        "classification_decision": classification.get("decision") or "",
        "embedding_relevance": classification.get("embedding") or {},
        "zero_shot": classification.get("zero_shot") or {},
        "matched_terms": concepts,
        "brsr_principle": map_brsr_signal(mapping_signal, concepts).get("principle"),
        "sdgs": sdgs,
    }
    if category == "esg":
        extra["esg_pillar"] = raw_signal
        if sdgs:
            extra["sdg_code"] = sdgs[0].get("code")
            extra["sdg_name"] = sdgs[0].get("name")
        display_signal = f"esg_{raw_signal}_{str(extra.get('sdg_code') or '').lower()}".rstrip("_")
    return evidence_card(
        item,
        display_signal,
        float(classification.get("confidence") or 0.0),
        classification.get("reason") or "Semantic reputation classification",
        extra,
    )


def _refresh_counts(category: str, section: dict[str, Any]) -> dict[str, Any]:
    items = section["items"]
    if category == "esg":
        pillars = {"environmental": 0, "social": 0, "governance": 0}
        sdg_counts = {rule["code"]: 0 for rule in SDG_RULES}
        for item in items:
            pillar = item.get("esg_pillar")
            if pillar in pillars:
                pillars[pillar] += 1
            for sdg in item.get("sdgs") or []:
                code = sdg.get("code") if isinstance(sdg, dict) else str(sdg)
                if code in sdg_counts:
                    sdg_counts[code] += 1
        section["pillar_counts"] = pillars
        section["sdg_counts"] = sdg_counts
        section["sdg_taxonomy"] = [
            {"code": rule["code"], "name": rule["name"], "pillar": rule["pillar"]}
            for rule in SDG_RULES
        ]
    return section


def analyze_signal_category(
    category: str,
    items: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    config = CATEGORY_CONFIG[category]
    accepted = []
    cross_category_items = []
    rejected = []
    seen = set()
    for item in items or []:
        key = item.get("url") or str(item.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        classification = classify_signal_item(category, item, profile)
        for cross_classification in classification.get("cross_classifications") or []:
            destination = SIGNAL_TO_CATEGORY.get(cross_classification.get("signal"))
            if not destination or destination == category:
                continue
            cross_card = _build_card(destination, item, {
                **classification,
                **cross_classification,
                "decision": "llm_cross_category",
            })
            cross_card["cross_category_origin"] = category
            cross_card["cross_category_destination"] = destination
            cross_category_items.append({
                "category": destination,
                "item": cross_card,
            })
        if classification.get("decision") == "reject":
            rejected.append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "",
                "classification_result": "rejected",
                "reason": classification.get("reason") or "semantic_classifier_rejected",
                "detected_signal": classification.get("signal") or "none",
                "confidence": float(classification.get("confidence") or 0.0),
                "classification_source": classification.get("source") or "",
                "embedding": classification.get("embedding") or {},
                "zero_shot": classification.get("zero_shot") or {},
            })
            continue
        accepted.append(_build_card(category, item, classification))

    limit = int(config.get("limit") or 8)
    if category in GROUPED_CATEGORIES:
        accepted = group_incident_items(accepted, limit)
    else:
        accepted = dedupe_items(accepted, limit)
    section = {
        "title": config["title"],
        "items": accepted,
        "count": len(accepted),
        "classification_rejections": rejected,
        "cross_category_items": cross_category_items,
        "summary": (
            f"Found {len(accepted)} {config['title'].lower()} signal(s)."
            if accepted else
            f"No direct {config['title'].lower()} signal found in temporary live evidence."
        ),
    }
    return _refresh_counts(category, section)
