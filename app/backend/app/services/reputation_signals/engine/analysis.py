from __future__ import annotations

import os
import time
import traceback
from typing import Any

from app.services.competitor_intelligence.intelligence_common import (
    enrich_competitor_profile,
    infer_competitor_entity_info,
)
from app.services.reputation_signals.classifiers.signal_classifier import analyze_signal_categories
from app.services.reputation_signals.reputation_common import (
    REPUTATION_CATEGORIES,
    normalize,
)
from app.services.reputation_signals.engine.common import _empty_reputation_result, _empty_section
from app.services.reputation_signals.observability.logger import write_reputation_log
from app.services.reputation_signals.retrieval.evidence import _collect_evidence
from app.services.reputation_signals.retrieval.query_planner import _product_aliases

def _safe_analyze(
    name: str,
    analyzer,
    items: list[dict[str, Any]],
    fallback: dict[str, Any],
    brand_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        print(f"[REPUTATION] Before {name}: {len(items)} item(s)")
        result = analyzer(items or [])
        print(f"[REPUTATION] After {name}: {result.get('count', 0)} signal(s)")
        return result
    except Exception as exc:
        trace = traceback.format_exc()
        log_path = write_reputation_log("errors", brand_id, {
            "stage": f"{name}_analyzer",
            "error": str(exc),
            "traceback": trace,
            "items_received": len(items or []),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        print(f"[REPUTATION] {name} analyzer failed -> {log_path}: {exc}")
        return {
            **fallback,
            "error": str(exc),
            "error_log": log_path,
        }


def _signal_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return f"url:{url}"
    return normalize(" ".join([
        str(item.get("title") or ""),
        str(item.get("snippet") or ""),
        str(item.get("source_name") or ""),
    ]))


def _section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    value = section.get("items") if isinstance(section, dict) else []
    return value if isinstance(value, list) else []


def _identity_terms_for_subject(profile: dict[str, Any]) -> list[str]:
    entity_resolution = profile.get("entity_resolution") or {}
    values = [
        profile.get("competitor_name") or "",
        profile.get("competitor_company") or "",
        profile.get("competitor") or "",
        entity_resolution.get("entity_name") if isinstance(entity_resolution, dict) else "",
        *(profile.get("aliases") or []),
        *(profile.get("product_names") or []),
        *(profile.get("service_names") or []),
    ]
    return list(dict.fromkeys(
        term for term in (str(value or "").strip() for value in values)
        if len(term) >= 3 and normalize(term)
    ))


def _token_positions(tokens: list[str], term_tokens: list[str]) -> list[int]:
    if not term_tokens:
        return []
    width = len(term_tokens)
    return [
        index for index in range(0, len(tokens) - width + 1)
        if tokens[index:index + width] == term_tokens
    ]


def _high_risk_action_terms(section_name: str, item: dict[str, Any]) -> list[str]:
    action_terms = {
        "regulatory": [
            "fine", "penalty", "lawsuit", "court order", "investigation",
            "regulatory action", "antitrust", "probe", "settlement", "charged",
            "charges", "sued", "compliance violation",
        ],
        "fraud": [
            "fraud", "scam", "bribery", "corruption", "money laundering",
            "embezzlement", "deceptive practices", "forged", "false claims",
        ],
        "layoffs": [
            "layoff", "layoffs", "job cuts", "workforce reduction",
            "salary delay", "delayed pay", "unpaid wages", "furlough",
            "restructuring",
        ],
        "security": [
            "data breach", "breach", "hack", "hacked", "cyber attack",
            "cyberattack", "ransomware", "data leak", "privacy breach",
        ],
    }
    return action_terms.get(section_name, [])


def _identity_as_media_descriptor(tokens: list[str], start: int, width: int) -> bool:
    descriptors = {
        "show", "series", "film", "movie", "documentary", "docuseries",
        "drama", "trailer", "episode", "actor", "director", "cast",
        "season", "screening", "streaming",
    }
    after = tokens[start + width:start + width + 3]
    before = tokens[max(0, start - 2):start]
    return any(token in descriptors for token in [*before, *after])


def _brand_is_subject_for_signal(
    item: dict[str, Any],
    profile: dict[str, Any],
    section_name: str,
) -> tuple[bool, str]:
    text = " ".join([
        str(item.get("title") or ""),
        str(item.get("snippet") or ""),
        str(item.get("body_text") or ""),
    ])
    tokens = normalize(text).split()
    if not tokens:
        return False, "empty_signal_text"

    action_positions = []
    for action in _high_risk_action_terms(section_name, item):
        action_positions.extend(_token_positions(tokens, normalize(action).split()))
    if not action_positions:
        return True, "no_high_risk_action_terms"

    for term in _identity_terms_for_subject(profile):
        term_tokens = normalize(term).split()
        for position in _token_positions(tokens, term_tokens):
            if _identity_as_media_descriptor(tokens, position, len(term_tokens)):
                continue
            if position == 0:
                return True, f"brand_starts_headline:{term}"
            for action_position in action_positions:
                distance = action_position - position
                if 0 <= distance <= 7:
                    return True, f"brand_subject_before_action:{term}"
                if -8 <= distance < 0:
                    between = set(tokens[action_position:position + len(term_tokens)])
                    if between.intersection({"against", "at", "by", "from", "over", "with", "on", "into"}):
                        return True, f"action_directed_at_brand:{term}"

    return False, "brand_mentioned_but_not_subject_of_signal"


def _refresh_basic_section(section: dict[str, Any]) -> dict[str, Any]:
    items = _section_items(section)
    section["count"] = len(items)
    title = section.get("title") or "Reputation Signals"
    section["summary"] = (
        f"Found {len(items)} {title.lower()} signal(s)."
        if items else
        f"No direct {title.lower()} signal found in temporary live evidence."
    )
    return section


def _refresh_esg_counts(section: dict[str, Any]) -> dict[str, Any]:
    items = section.get("items") or []
    section["count"] = len(items)

    if "pillar_counts" in section:
        counts = {"environmental": 0, "social": 0, "governance": 0}
        for item in items:
            pillar = item.get("esg_pillar")
            if pillar in counts:
                counts[pillar] += 1
        section["pillar_counts"] = counts

    if "sdg_counts" in section:
        counts = {key: 0 for key in section.get("sdg_counts") or {}}
        for item in items:
            for sdg in item.get("sdgs") or []:
                code = sdg.get("code") if isinstance(sdg, dict) else str(sdg)
                if code in counts:
                    counts[code] += 1
        section["sdg_counts"] = counts

    section["summary"] = (
        f"Found {len(items)} ESG signal(s) mapped across the 17 SDGs."
        if items else
        "No direct ESG signal found in temporary live evidence."
    )
    return section


def _remove_cross_category_esg_duplicates(
    esg: dict[str, Any],
    executive: dict[str, Any],
) -> dict[str, Any]:
    executive_keys = {
        _signal_key(item)
        for item in executive.get("items") or []
        if _signal_key(item)
    }
    if not executive_keys:
        return esg

    filtered = []
    removed = []
    for item in esg.get("items") or []:
        key = _signal_key(item)
        if (
            key
            and key in executive_keys
            and not item.get("cross_category_origin")
            and not item.get("multi_signal_classification")
        ):
            removed.append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "reason": "same evidence already classified as executive controversy",
            })
            continue
        filtered.append(item)

    if removed:
        esg = dict(esg)
        esg["items"] = filtered
        esg["removed_cross_category_duplicates"] = removed
        esg = _refresh_esg_counts(esg)
    return esg


def _merge_semantic_cross_category_items(
    sections: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    additions: dict[str, list[dict[str, Any]]] = {
        name: [] for name in sections
    }
    for origin, section in sections.items():
        for value in section.get("cross_category_items") or []:
            if not isinstance(value, dict):
                continue
            destination = str(value.get("category") or "")
            item = value.get("item")
            if destination not in additions or not isinstance(item, dict):
                continue
            additions[destination].append(item)

    merged: dict[str, dict[str, Any]] = {}
    for name, section in sections.items():
        section = dict(section)
        incoming = additions.get(name) or []
        if incoming:
            existing = _section_items(section)
            section["items"] = [*existing, *incoming]
            section["accepted_cross_category"] = [
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "signal": item.get("classification_signal") or item.get("signal") or "",
                    "origin": item.get("cross_category_origin") or "",
                }
                for item in incoming
            ]
            section = (
                _refresh_esg_counts(section)
                if name == "esg"
                else _refresh_basic_section(section)
            )
        merged[name] = section
    return merged


def _filter_subject_required_section(
    section: dict[str, Any],
    profile: dict[str, Any],
    section_name: str,
) -> dict[str, Any]:
    kept = []
    removed = []
    for item in _section_items(section):
        keep, reason = _brand_is_subject_for_signal(item, profile, section_name)
        if keep:
            kept.append(item)
            continue
        removed.append({
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "reason": reason,
        })
    if not removed:
        return section
    section = dict(section)
    section["items"] = kept
    section["removed_subject_validation"] = removed
    return _refresh_basic_section(section)


REGULATORY_PRODUCT_INCIDENT_TERMS = [
    "consumer court",
    "product recall",
    "recalled",
    "product defect",
    "defective product",
    "explosion",
    "explode",
    "explodes",
    "exploded",
    "battery fire",
    "catches fire",
    "caught fire",
    "device failure",
    "device defect",
]

REGULATORY_COMPANY_WIDE_SCOPE_TERMS = [
    "all models",
    "all units",
    "all devices",
    "multiple models",
    "multiple devices",
    "entire lineup",
    "product line",
    "product range",
    "company-wide",
    "nationwide recall",
    "global recall",
    "mass recall",
    "widespread defect",
    "widespread issue",
    "systemic defect",
]


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    return f" {normalize(phrase)} " in f" {normalize(text)} "


def _regulatory_product_aliases(profile: dict[str, Any]) -> list[str]:
    identity = profile.get("_reputation_identity") or {}
    product = str(
        identity.get("product")
        or profile.get("competitor_product")
        or ""
    ).strip()
    company = str(
        identity.get("company")
        or profile.get("competitor_company")
        or ""
    ).strip()
    aliases = identity.get("product_aliases") or _product_aliases(product, company)
    normalized_product = normalize(product)
    compact_product = normalized_product.replace(" ", "")
    strong_aliases = []
    for alias in (str(value or "").strip() for value in [product, *aliases]):
        normalized_alias = normalize(alias)
        compact_alias = normalized_alias.replace(" ", "")
        if len(normalized_alias) < 3:
            continue
        if (
            normalized_alias == normalized_product
            or compact_alias == compact_product
            or len(normalized_alias.split()) >= 2
            or any(char.isdigit() for char in normalized_alias)
        ):
            strong_aliases.append(alias)
    return list(dict.fromkeys(strong_aliases))


def _filter_product_incident_regulatory_scope(
    section: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    identity = profile.get("_reputation_identity") or {}
    if str(identity.get("entity_type") or "").lower() != "product":
        return section

    product_aliases = _regulatory_product_aliases(profile)
    kept = []
    removed = []
    for item in _section_items(section):
        text = " ".join([
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("body_text") or ""),
            str(item.get("reason") or ""),
        ])
        incident_terms = [
            term for term in REGULATORY_PRODUCT_INCIDENT_TERMS
            if _contains_normalized_phrase(text, term)
        ]
        if not incident_terms:
            kept.append(item)
            continue

        matched_product_aliases = [
            alias for alias in product_aliases
            if _contains_normalized_phrase(text, alias)
            or (
                len(normalize(alias).replace(" ", "")) >= 5
                and normalize(alias).replace(" ", "") in normalize(text).replace(" ", "")
            )
        ]
        if matched_product_aliases:
            item["regulatory_scope"] = "monitored_product"
            item["matched_product_aliases"] = matched_product_aliases[:5]
            kept.append(item)
            continue

        company_wide_terms = [
            term for term in REGULATORY_COMPANY_WIDE_SCOPE_TERMS
            if _contains_normalized_phrase(text, term)
        ]
        if company_wide_terms:
            item["regulatory_scope"] = "company_wide_product_issue"
            item["matched_scope_terms"] = company_wide_terms[:5]
            kept.append(item)
            continue

        removed.append({
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "reason": "product_incident_not_connected_to_monitored_product_or_company_wide_scope",
            "incident_terms": incident_terms[:5],
            "monitored_product": identity.get("product") or "",
        })

    if not removed:
        return section
    section = dict(section)
    section["items"] = kept
    section["removed_regulatory_product_scope"] = removed
    return _refresh_basic_section(section)


def _apply_priority_dedupe(sections: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    priority = [
        "regulatory",
        "security",
        "fraud",
        "executive",
        "layoffs",
        "esg",
        "complaints",
        "investments",
        "product",
    ]
    seen: dict[str, str] = {}
    cleaned: dict[str, dict[str, Any]] = {}
    for name in priority:
        section = dict(sections.get(name) or {})
        kept = []
        removed = []
        for item in _section_items(section):
            key = _signal_key(item)
            explicit_multi_signal = bool(
                item.get("cross_category_origin")
                or item.get("multi_signal_classification")
            )
            if key and key in seen and not explicit_multi_signal:
                removed.append({
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "reason": f"same evidence already classified as {seen[key]}",
                })
                continue
            if key:
                seen[key] = name
            kept.append(item)
        section["items"] = kept
        if removed:
            section["removed_priority_duplicates"] = removed
        cleaned[name] = _refresh_esg_counts(section) if name == "esg" else _refresh_basic_section(section)
    return cleaned


def _post_processing_log(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "removed_subject_validation": section.get("removed_subject_validation") or [],
            "removed_regulatory_product_scope": section.get("removed_regulatory_product_scope") or [],
            "accepted_cross_category": section.get("accepted_cross_category") or [],
            "removed_priority_duplicates": section.get("removed_priority_duplicates") or [],
            "removed_cross_category_duplicates": section.get("removed_cross_category_duplicates") or [],
            "final_count": section.get("count", 0),
        }
        for name, section in sections.items()
    }


CLASSIFICATION_DEBUG_SIGNALS = {
    "product": {
        "product_success",
        "product_failure",
        "product_launch",
        "product_review",
        "product_comparison",
        "product_feature",
    },
    "esg": {"environmental", "social", "governance"},
    "investments": {"investment", "withdrawal"},
    "regulatory": {"regulatory_action"},
    "complaints": {"customer_complaint"},
    "security": {"security_incident"},
    "layoffs": {"layoff"},
    "fraud": {"fraud_allegation"},
    "executive": {"executive_change", "executive_controversy"},
}


def _debug_item_key(item: dict[str, Any]) -> str:
    return _signal_key(item)


def _post_processing_removal_reasons(section: dict[str, Any]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for field in [
        "removed_subject_validation",
        "removed_regulatory_product_scope",
        "removed_priority_duplicates",
        "removed_cross_category_duplicates",
    ]:
        for item in section.get(field) or []:
            if not isinstance(item, dict):
                continue
            key = _debug_item_key(item)
            if key:
                reasons[key] = str(item.get("reason") or field)
    return reasons


def _classification_debug(
    evidence: dict[str, list[dict[str, Any]]],
    retrieval_summary: dict[str, Any],
    sections: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    debug: dict[str, Any] = {}
    sample_limit = max(1, int(os.getenv("REPUTATION_CLASSIFICATION_DEBUG_LIMIT", "50")))
    retrieval_runs = retrieval_summary.get("runs") or {}

    for category in CLASSIFICATION_DEBUG_SIGNALS:
        category_evidence = evidence.get(category) or []
        section = sections.get(category) or {}
        accepted_keys = {
            _debug_item_key(item)
            for item in _section_items(section)
            if _debug_item_key(item)
        }
        removal_reasons = _post_processing_removal_reasons(section)
        classifier_rejections = {
            _debug_item_key(item): item
            for item in section.get("classification_rejections") or []
            if isinstance(item, dict) and _debug_item_key(item)
        }
        accepted_items = []
        rejected_items = []

        for item in category_evidence:
            key = _debug_item_key(item)
            base = {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "",
                "evidence_origin": item.get("evidence_origin") or "",
                "validation_mode": item.get("validation_mode") or "",
                "validation_target": item.get("validation_target") or "",
            }
            if key and key in accepted_keys:
                accepted_items.append({
                    **base,
                    "classification_result": "accepted",
                })
                continue

            rejection = classifier_rejections.get(key) or {}
            rejected_items.append({
                **base,
                "classification_result": "rejected",
                "reason": (
                    removal_reasons.get(key)
                    or rejection.get("reason")
                    or f"no_{category}_semantic_signal_detected"
                ),
                "classifier_reason": rejection.get("reason") or "",
                "detected_signal": rejection.get("detected_signal") or "none",
                "confidence": float(rejection.get("confidence") or 0.0),
                "classification_source": rejection.get("classification_source") or "",
                "embedding": rejection.get("embedding") or {},
                "zero_shot": rejection.get("zero_shot") or {},
                "debug_classifier": "zero_shot_then_groq",
            })

        category_runs = retrieval_runs.get(category) or []
        retrieved_raw = sum(
            int(run.get("raw_found") or 0)
            for run in category_runs
            if isinstance(run, dict)
        )
        debug[category] = {
            "retrieved": retrieved_raw,
            "validated": len(category_evidence),
            "classified": int(section.get("count") or 0),
            "accepted": len(accepted_items),
            "rejected": len(rejected_items),
            "accepted_items": accepted_items[:sample_limit],
            "rejected_items": rejected_items[:sample_limit],
            "items_truncated": (
                len(accepted_items) > sample_limit
                or len(rejected_items) > sample_limit
            ),
        }
    return debug


def _combined_groq_usage(
    brand_intelligence_usage: dict[str, Any],
    classification_run: dict[str, Any],
) -> dict[str, Any]:
    classification_usage = classification_run.get("groq_usage") or {}
    return {
        "requests": (
            int(brand_intelligence_usage.get("requests") or 0)
            + int(classification_usage.get("requests") or 0)
        ),
        "cached_hits": (
            int(brand_intelligence_usage.get("cached_hits") or 0)
            + int(classification_usage.get("cached_hits") or 0)
        ),
        "prompt_tokens": (
            int(brand_intelligence_usage.get("prompt_tokens") or 0)
            + int(classification_usage.get("prompt_tokens") or 0)
        ),
        "completion_tokens": (
            int(brand_intelligence_usage.get("completion_tokens") or 0)
            + int(classification_usage.get("completion_tokens") or 0)
        ),
        "total_tokens": (
            int(brand_intelligence_usage.get("total_tokens") or 0)
            + int(classification_usage.get("total_tokens") or 0)
        ),
        "rate_limit_retries": (
            int(brand_intelligence_usage.get("rate_limit_retries") or 0)
            + int(classification_usage.get("rate_limit_retries") or 0)
        ),
        "duration_ms": round(
            float(brand_intelligence_usage.get("duration_ms") or 0.0)
            + float(classification_usage.get("duration_ms") or 0.0),
            2,
        ),
        "failed_requests": (
            int(brand_intelligence_usage.get("success") is False)
            + int(classification_usage.get("failed_requests") or 0)
        ),
        "model": (
            classification_usage.get("model")
            or brand_intelligence_usage.get("model")
            or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        ),
    }


def run_reputation_analysis(
    brand_id: str,
    brand: dict[str, Any],
    competitor_profile: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        profile = enrich_competitor_profile(competitor_profile)
        info = infer_competitor_entity_info(profile)
        company = info.get("company") or profile.get("competitor_name") or profile.get("competitor") or ""
        product = info.get("product") or profile.get("competitor_product") or ""
        profile["_reputation_subjects"] = {
            "company": company.strip(),
            "product": product.strip(),
            "primary": (product or company).strip(),
        }
        profile["_reputation_identity"] = {
            "entity_type": "product" if product else "company",
            "company": company.strip(),
            "product": product.strip(),
            "primary": (product or company).strip(),
            "product_aliases": _product_aliases(product, company),
            "company_validated_categories": [
                "layoffs", "esg", "regulatory", "fraud", "executive", "investments"
            ],
            "product_validated_categories": [
                "product", "complaints", "security"
            ] if product else [],
            "temporary": True,
            "stored": False,
        }
        print(f"[REPUTATION] Brand: {brand.get('brand_name') or ''}")
        evidence, retrieval_summary = _collect_evidence(brand_id, profile)
    except Exception as exc:
        return _empty_reputation_result(
            brand_id,
            brand,
            str(exc),
            traceback.format_exc(),
        )

    print("[REPUTATION] Evidence counts:", {key: len(value) for key, value in evidence.items()})
    classification_started = time.perf_counter()
    semantic_sections = analyze_signal_categories(evidence, profile)
    classification_run = semantic_sections.get("_classification_run") or {}
    print(
        "[REPUTATION] Semantic classification completed in "
        f"{round(time.perf_counter() - classification_started, 2)}s"
    )
    product = semantic_sections["product"]
    esg = semantic_sections["esg"]
    investments = semantic_sections["investments"]
    regulatory = semantic_sections["regulatory"]
    complaints = semantic_sections["complaints"]
    security = semantic_sections["security"]
    layoffs = semantic_sections["layoffs"]
    fraud = semantic_sections["fraud"]
    executive = semantic_sections["executive"]
    regulatory = _filter_product_incident_regulatory_scope(regulatory, profile)
    regulatory = _filter_subject_required_section(regulatory, profile, "regulatory")
    fraud = _filter_subject_required_section(fraud, profile, "fraud")
    layoffs = _filter_subject_required_section(layoffs, profile, "layoffs")
    security = _filter_subject_required_section(security, profile, "security")
    esg = _remove_cross_category_esg_duplicates(esg, executive)
    cleaned_sections = _apply_priority_dedupe({
        "product": product,
        "esg": esg,
        "investments": investments,
        "regulatory": regulatory,
        "complaints": complaints,
        "security": security,
        "layoffs": layoffs,
        "fraud": fraud,
        "executive": executive,
    })
    product = cleaned_sections["product"]
    esg = cleaned_sections["esg"]
    investments = cleaned_sections["investments"]
    regulatory = cleaned_sections["regulatory"]
    complaints = cleaned_sections["complaints"]
    security = cleaned_sections["security"]
    layoffs = cleaned_sections["layoffs"]
    fraud = cleaned_sections["fraud"]
    executive = cleaned_sections["executive"]
    post_processing = _post_processing_log(cleaned_sections)
    classification_debug = _classification_debug(
        evidence,
        retrieval_summary,
        cleaned_sections,
    )
    print("[REPUTATION][CLASSIFICATION] Category analytics:", {
        category: {
            "retrieved": values.get("retrieved", 0),
            "validated": values.get("validated", 0),
            "classified": values.get("classified", 0),
            "rejected": values.get("rejected", 0),
        }
        for category, values in classification_debug.items()
    })
    brand_intelligence_usage = (
        (profile.get("_brand_intelligence") or {}).get("groq_usage") or {}
    )
    combined_usage = _combined_groq_usage(
        brand_intelligence_usage,
        classification_run,
    )
    groq_usage_log = write_reputation_log("groq_usage", brand_id, {
        "stage": "temporary_reputation_groq_usage",
        "brand": brand.get("brand_name") or "",
        "model": combined_usage["model"],
        "totals": combined_usage,
        "brand_intelligence": {
            "usage": brand_intelligence_usage,
            "cache_hit": bool((profile.get("_brand_intelligence") or {}).get("cache_hit")),
        },
        "article_classification": {
            key: value
            for key, value in classification_run.items()
            if key != "groq_events"
        },
        "evidence_reuse": retrieval_summary.get("evidence_merge") or {},
        "article_calls": classification_run.get("groq_events") or [],
    })
    print(
        "[REPUTATION][GROQ] "
        f"requests={combined_usage['requests']} "
        f"cache_hits={combined_usage['cached_hits']} "
        f"prompt_tokens={combined_usage['prompt_tokens']} "
        f"completion_tokens={combined_usage['completion_tokens']} "
        f"total_tokens={combined_usage['total_tokens']} "
        f"rate_limit_retries={combined_usage['rate_limit_retries']} "
        f"log={groq_usage_log}"
    )
    classification_payload = {
        "stage": "temporary_reputation_classification",
        "brand": brand.get("brand_name") or "",
        "reputation_identity": profile.get("_reputation_identity") or {},
        "evidence_counts": {key: len(value) for key, value in evidence.items()},
        "evidence_reuse": retrieval_summary.get("evidence_merge") or {},
        "signal_counts": {
            "product_signals": product.get("count", 0),
            "esg_signals": esg.get("count", 0),
            "investment_signals": investments.get("count", 0),
            "regulatory_signals": regulatory.get("count", 0),
            "customer_complaints": complaints.get("count", 0),
            "security_incidents": security.get("count", 0),
            "layoff_signals": layoffs.get("count", 0),
            "fraud_signals": fraud.get("count", 0),
            "executive_controversies": executive.get("count", 0),
        },
        "classification_debug": classification_debug,
        "semantic_classification_run": classification_run,
        "groq_usage": combined_usage,
        "groq_usage_log": groq_usage_log,
        "post_processing": post_processing,
    }
    classification_log = write_reputation_log("classification", brand_id, classification_payload)
    result = {
        "temporary": True,
        "stored": False,
        "brand": brand.get("brand_name") or "",
        "competitor": profile.get("competitor_name") or profile.get("competitor") or "",
        "descriptions": REPUTATION_CATEGORIES,
        "product_signals": product,
        "esg_signals": esg,
        "investment_signals": investments,
        "regulatory_signals": regulatory,
        "customer_complaints": complaints,
        "security_incidents": security,
        "layoff_signals": layoffs,
        "fraud_signals": fraud,
        "executive_controversies": executive,
        "retrieval_summary": retrieval_summary,
        "reputation_identity": profile.get("_reputation_identity") or {},
        "classification_log": classification_log,
        "groq_usage": combined_usage,
        "groq_usage_log": groq_usage_log,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    write_reputation_log("intelligence", brand_id, {
        "stage": "temporary_reputation_signals",
        "competitor_profile": profile,
        "result": result,
    })
    return result
