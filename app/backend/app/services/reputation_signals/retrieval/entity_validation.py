from __future__ import annotations

import os
import re
from typing import Any

from app.services.competitor_intelligence.intelligence_common import normalize
from app.services.reputation_signals.engine.common import _unique_strings
from app.services.reputation_signals.retrieval.query_planner import _subjects

def _text_for_match(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in ["title", "body_text", "description", "snippet"]
    )


def _term_present(text: str, term: str) -> bool:
    return f" {normalize(term)} " in f" {normalize(text)} "


def _compact_normalize(value: str) -> str:
    return "".join(normalize(value).split())


def _compact_term_present(text: str, term: str) -> bool:
    compact_term = _compact_normalize(term)
    if len(compact_term) < 5:
        return False
    return compact_term in _compact_normalize(text)


def _surface_term_present(text: str, term: str) -> bool:
    raw_text = text or ""
    raw_term = str(term or "").strip()
    if not raw_text or not raw_term:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(raw_term)}(?![A-Za-z0-9])"
    flags = 0 if any(char.isupper() for char in raw_term) else re.IGNORECASE
    return re.search(pattern, raw_text, flags) is not None


def _normalized_profile_terms(profile: dict[str, Any], *keys: str) -> set[str]:
    terms: set[str] = set()
    for key in keys:
        value = profile.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            normalized = normalize(str(item or ""))
            if normalized:
                terms.add(normalized)
    return terms


def _context_terms(profile: dict[str, Any]) -> list[str]:
    values = [
        *(profile.get("product_names") or []),
        *(profile.get("product_aliases") or []),
        *(profile.get("service_names") or []),
        *(profile.get("aliases") or []),
        *(profile.get("context_terms") or []),
        *(profile.get("competitor_keywords") or []),
    ]
    return [
        term for term in dict.fromkeys(str(value or "").strip() for value in values)
        if len(term) >= 4 and len(normalize(term).split()) >= 1
    ]


def _identity_surface_terms(profile: dict[str, Any]) -> list[str]:
    entity_resolution = profile.get("entity_resolution") or {}
    values = [
        profile.get("competitor_name"),
        profile.get("competitor_company"),
        entity_resolution.get("entity_name") if isinstance(entity_resolution, dict) else "",
        *(profile.get("aliases") or []),
        *(profile.get("product_names") or []),
        *(profile.get("product_aliases") or []),
        *(profile.get("service_names") or []),
    ]
    return [
        term for term in dict.fromkeys(str(value or "").strip() for value in values)
        if len(term) >= 3
    ]


def _has_exact_identity_surface(text: str, profile: dict[str, Any]) -> bool:
    return any(_surface_term_present(text, term) for term in _identity_surface_terms(profile))


def _identity_surface_matches(text: str, profile: dict[str, Any]) -> list[str]:
    return [
        term for term in _identity_surface_terms(profile)
        if _surface_term_present(text, term)
    ]


def _is_stylized_identity_term(term: str) -> bool:
    raw = str(term or "").strip()
    if not raw:
        return False
    return (
        any(char.islower() for char in raw)
        and any(char.isupper() for char in raw)
        and raw != raw.title()
    )


def _has_strong_identity_surface_match(matches: list[str]) -> bool:
    for term in matches:
        normalized = normalize(term)
        if len(normalized.split()) > 1:
            return True
        if _is_stylized_identity_term(term):
            return True
    return False


def _only_ambiguous_single_word_identity_matches(matches: list[str], profile: dict[str, Any]) -> bool:
    if not matches:
        return False
    return all(_ambiguous_identity_term(term, profile) for term in matches)


def _product_alias_weight(term: str, profile: dict[str, Any]) -> float:
    normalized = normalize(term)
    if not normalized:
        return 0.0
    product = normalize(profile.get("competitor_product") or profile.get("competitor_name") or "")
    if product and normalized == product:
        return 1.0
    tokens = normalized.split()
    if len(tokens) >= 2:
        return 0.75
    if any(char.isdigit() for char in normalized):
        return 0.7
    return 0.4


def _product_alias_match_score(text: str, profile: dict[str, Any]) -> tuple[float, str]:
    if (profile.get("entity_type") or "").lower() != "product":
        return 0.0, "not_product_validation"
    best_score = 0.0
    best_term = ""
    for term in _unique_strings(
        [profile.get("competitor_product") or ""],
        profile.get("product_names"),
        profile.get("product_aliases"),
    ):
        if (
            not _surface_term_present(text, term)
            and not _term_present(text, term)
            and not _compact_term_present(text, term)
        ):
            continue
        score = _product_alias_weight(term, profile)
        if score > best_score:
            best_score = score
            best_term = term
    return best_score, f"product_alias_match:{best_term}:{best_score}"


def _has_resolved_context(text: str, profile: dict[str, Any]) -> bool:
    broad_terms = {
        "technology",
        "software",
        "hardware",
        "ai",
        "cloud",
        "app",
        "platform",
        "device",
        "product",
        "company",
        "brand",
    }
    for term in _context_terms(profile):
        normalized = normalize(term)
        if not normalized or normalized in broad_terms:
            continue
        if len(normalized.split()) > 1 and _term_present(text, term):
            return True
        if normalized not in broad_terms and _surface_term_present(text, term):
            return True
    return False


def _ignore_terms_present(text: str, profile: dict[str, Any]) -> list[str]:
    ignored_terms = _unique_strings(profile.get("ignore_terms"), profile.get("negative_terms"))
    matched: list[str] = []
    for term in ignored_terms:
        normalized = normalize(term)
        if not normalized:
            continue
        if _term_present(text, term) or _surface_term_present(text, term):
            matched.append(term)
    return matched


def _gliner_entity_matches_resolved_context(text: str, profile: dict[str, Any]) -> tuple[bool, str]:
    if os.getenv("REPUTATION_GLINER_ARTICLE_VALIDATION", "1").strip().lower() in {"0", "false", "no"}:
        return False, "gliner_validation_disabled"

    try:
        from app.services.entity_resolution.entity_detector import detect_brand_entities

        min_score = float(os.getenv("REPUTATION_GLINER_ARTICLE_MIN_SCORE", "0.45"))
        entities = detect_brand_entities(text[:1000], min_score=min_score)
    except Exception as exc:
        return False, f"gliner_validation_unavailable:{exc}"

    expected_terms = {
        normalize(term)
        for term in _identity_surface_terms(profile)
        if normalize(term)
    }
    if not expected_terms:
        return False, "gliner_no_expected_terms"

    detected_terms = []
    for entity in entities or []:
        entity_text = str(entity.get("text") or "").strip()
        normalized_entity = normalize(entity_text)
        if not normalized_entity:
            continue
        detected_terms.append(entity_text)
        for expected in expected_terms:
            expected_tokens = expected.split()
            entity_tokens = normalized_entity.split()
            if (
                len(expected_tokens) == 1
                and len(entity_tokens) > 1
                and expected in normalized_entity
            ):
                continue
            if normalized_entity == expected or normalized_entity in expected or expected in normalized_entity:
                return True, f"gliner_entity_match:{entity_text}"

    return False, f"gliner_no_entity_match:{detected_terms[:5]}"


def _validate_article_against_resolved_entity(
    item: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[bool, str]:
    text = _text_for_match(item)
    if not text.strip():
        return False, "empty_article_text"

    identity_matches = _identity_surface_matches(text, profile)
    has_exact_identity = bool(identity_matches)
    has_context = _has_resolved_context(text, profile)
    alias_score, alias_reason = _product_alias_match_score(text, profile)
    ignore_matches = _ignore_terms_present(text, profile)

    if ignore_matches and not has_exact_identity and not has_context:
        return False, f"ignored_term_without_resolved_entity_context:{ignore_matches[:5]}"
    if ignore_matches and not has_exact_identity:
        return False, f"ignored_term_requires_exact_entity_surface:{ignore_matches[:5]}"

    if (
        has_exact_identity
        and not has_context
        and not _has_strong_identity_surface_match(identity_matches)
        and _only_ambiguous_single_word_identity_matches(identity_matches, profile)
    ):
        return False, f"ambiguous_identity_requires_resolved_context:{identity_matches[:5]}"

    if (profile.get("entity_type") or "").lower() == "product":
        min_score = float(os.getenv("REPUTATION_PRODUCT_ALIAS_MIN_SCORE", "0.7"))
        if alias_score >= min_score:
            return True, alias_reason
        if alias_score > 0 and has_context:
            return True, f"{alias_reason}:with_context"
        if alias_score > 0:
            return False, f"weak_product_alias_without_context:{alias_reason}"

    if has_exact_identity:
        return True, "exact_resolved_entity_surface"

    gliner_match, gliner_reason = _gliner_entity_matches_resolved_context(text, profile)
    if gliner_match:
        return True, gliner_reason

    if has_context:
        return False, f"resolved_context_without_entity_surface:{gliner_reason}"
    return False, gliner_reason


def _ambiguous_identity_term(term: str, profile: dict[str, Any]) -> bool:
    normalized = normalize(term)
    if not normalized:
        return False
    ignored = _normalized_profile_terms(profile, "negative_terms", "ignore_terms")
    if normalized in ignored:
        return True
    tokens = normalized.split()
    if len(tokens) == 1 and len(tokens[0]) <= 4:
        return True
    return False


def _profile_term_match(text: str, term: str, profile: dict[str, Any]) -> tuple[bool, str]:
    if not term:
        return False, "empty_term"
    if _ambiguous_identity_term(term, profile):
        if _surface_term_present(text, term):
            return True, "exact_surface_identity_match"
        return False, "ambiguous_identity_without_resolved_context"
    if _term_present(text, term):
        return True, "normalized_identity_match"
    return False, "identity_missing"


def _identity_terms(profile: dict[str, Any]) -> dict[str, list[str]]:
    subjects = _subjects(profile)
    company = subjects["company"]
    product = subjects["product"]
    full_name = profile.get("competitor_name") or profile.get("competitor") or ""
    product_terms = [
        product,
        full_name if product and _term_present(full_name, product) else "",
        *(profile.get("product_names") or []),
        *(profile.get("product_aliases") or []),
        *(profile.get("service_names") or []),
    ]
    company_terms = [
        company,
        full_name,
        profile.get("competitor_company") or "",
        *(profile.get("aliases") or []),
    ]
    return {
        "product": [term for term in dict.fromkeys(str(term).strip() for term in product_terms) if len(term.strip()) >= 3],
        "company": [term for term in dict.fromkeys(str(term).strip() for term in company_terms) if len(term.strip()) >= 3],
    }


def _reputation_relevance_score(item: dict[str, Any], profile: dict[str, Any], category: str) -> tuple[float, str]:
    text = _text_for_match(item)
    terms = _identity_terms(profile)
    product_terms = terms["product"]
    company_terms = terms["company"]

    for term in product_terms:
        matched, reason = _profile_term_match(text, term, profile)
        if matched:
            alias_score, alias_reason = _product_alias_match_score(text, profile)
            if alias_score >= float(os.getenv("REPUTATION_PRODUCT_ALIAS_MIN_SCORE", "0.7")):
                return max(alias_score, 0.7), f"product_or_exact_brand_match:{reason}:{alias_reason}"
            if alias_score > 0 and _has_resolved_context(text, profile):
                return 0.65, f"weak_product_alias_with_context:{reason}:{alias_reason}"
            if alias_score > 0:
                return 0.0, f"weak_product_alias_below_threshold:{reason}:{alias_reason}"
            return 1.0, f"product_or_exact_brand_match:{reason}"

    if not product_terms:
        for term in company_terms:
            matched, reason = _profile_term_match(text, term, profile)
            if matched:
                return 0.9, f"company_match:{reason}"

    if category in {"esg", "investments", "regulatory"}:
        for term in company_terms:
            matched, reason = _profile_term_match(text, term, profile)
            if matched:
                return 0.85, f"company_match:{reason}"

    for term in company_terms:
        if len(normalize(term).split()) > 1:
            matched, reason = _profile_term_match(text, term, profile)
            if matched:
                return 0.75, f"exact_brand_match:{reason}"
    return 0.0, "missing_active_brand_or_product"
