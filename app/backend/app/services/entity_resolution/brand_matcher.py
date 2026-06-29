"""
Brand relevance scoring for monitored mentions.

This module is intentionally deterministic and cheap: no embeddings, no LLMs,
and no external API calls. It combines aliases, official channels, exclusions,
and source-aware context into a single confidence score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


DEFAULT_CONTEXT_KEYWORDS = {
    "ai",
    "autopilot",
    "automotive",
    "automobile",
    "automobiles",
    "business",
    "car",
    "cars",
    "cloud",
    "company",
    "cybertruck",
    "deliver",
    "delivers",
    "delivery",
    "earnings call",
    "earnings",
    "electric vehicle",
    "enterprise",
    "ev",
    "factory",
    "gt",
    "fsd",
    "hardware",
    "laptop",
    "market share",
    "model 3",
    "model s",
    "model x",
    "model y",
    "monitor",
    "motors",
    "pc",
    "price",
    "product",
    "recall",
    "review",
    "revealed",
    "revenue",
    "server",
    "software",
    "stock",
    "suv",
    "supercharger",
    "technology",
    "u-turn",
    "vehicle",
    "vehicles",
}

DEFAULT_NOISY_CONTEXT = {
    "album",
    "animal",
    "artist",
    "audio",
    "beat",
    "big cat",
    "capo plaza",
    "concert",
    "crocodile",
    "database",
    "didine canon",
    "dj",
    "feat",
    "ft.",
    "instrumental",
    "karaoke",
    "kids song",
    "love song",
    "lyrics",
    "music",
    "music video",
    "nursery rhyme",
    "official audio",
    "official music video",
    "python library",
    "punjabi",
    "rapper",
    "remix",
    "song",
    "tiger",
    "wildlife",
}

SOURCE_THRESHOLDS = {
    "youtube": 0.78,
    "reddit": 0.4,
    "newsapi": 0.4,
    "google_news": 0.4,
}

@dataclass(frozen=True)
class BrandChannel:
    source: str | None
    channel_name: str
    channel_url: str | None = None
    verified: bool = False


@dataclass(frozen=True)
class BrandProfile:
    brand_id: str | None
    brand_name: str
    aliases: list[str] = field(default_factory=list)
    official_channels: list[BrandChannel] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    context_keywords: list[str] = field(default_factory=list)
    entity_type: str = "brand"
    industry: str = "unknown"
    primary_category: str = ""
    subcategory: str = ""
    competitor_category: str = ""
    manufacturer: str = ""
    categories: list[str] = field(default_factory=list)
    brand_context: str = ""
    product_tokens: list[str] = field(default_factory=list)
    required_tokens: list[str] = field(default_factory=list)


def normalize_text(value: str | None) -> str:
    """Lowercase text and collapse spacing for stable comparisons."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def contains_term(text: str, term: str) -> bool:
    """Return True when term appears as a whole phrase, not a substring."""
    normalized_text = normalize_text(text)
    normalized_term = normalize_text(term)
    if not normalized_text or not normalized_term:
        return False

    left = r"(?<![a-z0-9])"
    right = r"(?![a-z0-9])"
    return re.search(f"{left}{re.escape(normalized_term)}{right}", normalized_text) is not None


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def unique_terms(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = normalize_text(value)
        if value and key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def remove_self_exclusions(brand_name: str, aliases: Iterable[str], exclusions: Iterable[str]) -> list[str]:
    protected = {normalize_text(brand_name), *(normalize_text(alias) for alias in aliases or [])}
    protected = {term for term in protected if term}
    protected_tokens = {
        token
        for term in protected
        for token in term.split()
    }
    cleaned = []
    for exclusion in exclusions or []:
        key = normalize_text(exclusion)
        if not key:
            continue
        key_tokens = set(key.split())
        if key in protected or (key_tokens and key_tokens.issubset(protected_tokens)):
            print(f"[BRAND MATCHER] Removed self-exclusion term: {exclusion}")
            continue
        cleaned.append(exclusion)
    return unique_terms(cleaned)


def channel_matches(
    channel_name: str | None,
    official_channels: Iterable[BrandChannel | dict[str, Any] | str],
    source: str | None = None,
) -> tuple[bool, list[str]]:
    normalized_channel = normalize_text(channel_name)
    normalized_source = normalize_text(source)
    matches = []

    if not normalized_channel:
        return False, matches

    for channel in official_channels or []:
        if isinstance(channel, str):
            channel_source = ""
            official_name = channel
        elif isinstance(channel, dict):
            channel_source = normalize_text(channel.get("source"))
            official_name = channel.get("channel_name") or ""
        else:
            channel_source = normalize_text(channel.source)
            official_name = channel.channel_name

        if normalized_source and channel_source and channel_source != normalized_source:
            continue

        if normalize_text(official_name) == normalized_channel:
            matches.append(official_name)

    return bool(matches), unique_terms(matches)


def match_brand(
    *,
    brand_name: str,
    aliases: list[str] | tuple[str, ...] | None = None,
    text: str = "",
    title: str = "",
    channel_name: str = "",
    source: str = "",
    official_channels: list[BrandChannel | dict[str, Any] | str] | None = None,
    exclusions: list[str] | tuple[str, ...] | None = None,
    context_keywords: list[str] | tuple[str, ...] | None = None,
    product_tokens: list[str] | tuple[str, ...] | None = None,
    required_tokens: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Score whether a source item is relevant to a monitored brand.

    Returns:
        {
            "matched": bool,
            "confidence": float,
            "reason": str,
            "matched_terms": list[str],
        }
    """
    aliases = list(aliases or [])
    exclusions = list(exclusions or [])
    official_channels = list(official_channels or [])
    context_keywords = list(context_keywords or DEFAULT_CONTEXT_KEYWORDS)
    product_tokens = unique_terms(product_tokens or [])
    required_tokens = unique_terms(required_tokens or [])

    combined_text = " ".join(part for part in [title, text, channel_name] if part)
    source_key = normalize_text(source)
    normalized_brand = normalize_text(brand_name)
    confidence = 0.0
    reasons = []
    matched_terms = []

    if contains_term(combined_text, brand_name):
        confidence += 0.4
        reasons.append("exact_brand_match")
        matched_terms.append(brand_name)

    alias_hits = [alias for alias in aliases if contains_term(combined_text, alias)]
    if alias_hits:
        confidence += min(0.3, 0.15 * len(alias_hits))
        reasons.append("alias_match")
        matched_terms.extend(alias_hits)

    official_channel_hit, channel_terms = channel_matches(
        channel_name,
        official_channels,
        source=source,
    )
    if official_channel_hit:
        confidence += 0.25
        reasons.append("official_channel")
        matched_terms.extend(channel_terms)

        if contains_term(title, brand_name) or any(contains_term(title, alias) for alias in aliases):
            confidence += 0.15 if source_key == "youtube" else 0.1
            reasons.append("official_title_match")

    context_hits = [term for term in context_keywords if contains_term(combined_text, term)]
    if context_hits:
        context_score = min(0.4, 0.4 * len(context_hits)) if source_key == "youtube" else min(0.15, 0.05 * len(context_hits))
        confidence += context_score
        reasons.append("context_keyword")
        matched_terms.extend(context_hits)

    product_token_hits = [term for term in product_tokens if contains_term(combined_text, term)]
    if product_token_hits:
        confidence += min(0.35, 0.12 * len(product_token_hits))
        reasons.append("product_token_match")
        matched_terms.extend(product_token_hits)

    missing_required_tokens = [
        term for term in required_tokens
        if not contains_term(combined_text, term)
    ]
    if required_tokens and missing_required_tokens:
        confidence -= 0.8
        reasons.append("required_product_token_missing")

    exclusion_hits = [phrase for phrase in exclusions if contains_term(combined_text, phrase)]
    if exclusion_hits:
        confidence -= 0.8
        reasons.append("exclusion_phrase")

    noisy_hits = [phrase for phrase in DEFAULT_NOISY_CONTEXT if contains_term(combined_text, phrase)]
    if noisy_hits:
        confidence -= 0.25
        reasons.append("noisy_context")

    title_looks_like_track = bool(
        source_key == "youtube"
        and title
        and re.search(r"^\s*[^|:\n]{2,80}\s+-\s+[^|:\n]{2,80}\s*$", title)
    )
    if title_looks_like_track and not official_channel_hit:
        confidence -= 0.25
        reasons.append("youtube_track_title_pattern")

    if source_key == "youtube" and not official_channel_hit and not alias_hits and not contains_term(combined_text, brand_name):
        confidence -= 0.1
        reasons.append("youtube_untrusted_channel")

    if (
        source_key == "youtube"
        and context_keywords
        and not official_channel_hit
        and not alias_hits
        and not context_hits
    ):
        confidence -= 0.2
        reasons.append("youtube_ambiguous_exact_only")

    confidence = clamp_score(confidence)
    threshold = SOURCE_THRESHOLDS.get(source_key, 0.5)
    matched = (
        confidence >= threshold
        and not (exclusion_hits and confidence < 0.7)
        and not missing_required_tokens
    )

    return {
        "matched": matched,
        "confidence": confidence,
        "reason": " + ".join(reasons) if reasons else "no_signal",
        "matched_terms": unique_terms(matched_terms),
        "product_token_hits": product_token_hits,
        "missing_required_tokens": missing_required_tokens,
    }


def load_brand_profile(conn: Any, *, brand_id: str | None = None, brand_name: str | None = None) -> BrandProfile:
    """
    Load monitor aliases, official channels, and exclusion phrases from Postgres.

    The caller owns the connection. This function does not commit, close, or make
    network/API requests.
    """
    if not brand_id and not brand_name:
        raise ValueError("brand_id or brand_name is required")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'monitored_brands'
            """
        )
        monitored_brand_columns = {column for (column,) in cur.fetchall()}
        optional_columns = [
            column
            for column in [
                "industry",
                "entity_type",
                "primary_category",
                "subcategory",
                "competitor_category",
                "manufacturer",
                "categories",
                "context_terms",
                "negative_terms",
                "brand_context",
            ]
            if column in monitored_brand_columns
        ]
        select_columns = ["id", "brand_name", "aliases", *optional_columns]

        if brand_id:
            cur.execute(
                f"""
                SELECT {", ".join(select_columns)}
                FROM monitored_brands
                WHERE id = %s
                LIMIT 1
                """,
                (brand_id,),
            )
        else:
            cur.execute(
                f"""
                SELECT {", ".join(select_columns)}
                FROM monitored_brands
                WHERE brand_name ILIKE %s
                LIMIT 1
                """,
                (brand_name,),
            )

        row = cur.fetchone()
        if not row:
            raise LookupError("Brand monitor not found")

        row_data = dict(zip(select_columns, row))
        loaded_brand_id = row_data["id"]
        loaded_brand_name = row_data["brand_name"]
        aliases = row_data.get("aliases") or []
        entity_type = row_data.get("entity_type") or "brand"
        industry = row_data.get("industry") or "unknown"
        primary_category = row_data.get("primary_category") or ""
        subcategory = row_data.get("subcategory") or ""
        competitor_category = row_data.get("competitor_category") or ""
        manufacturer = row_data.get("manufacturer") or ""
        categories = row_data.get("categories") or []
        context_terms = row_data.get("context_terms") or []
        negative_terms = row_data.get("negative_terms") or []
        brand_context = row_data.get("brand_context") or ""

        cur.execute(
            """
            SELECT source, channel_name, channel_url, verified
            FROM brand_channels
            WHERE brand_id = %s
            """,
            (loaded_brand_id,),
        )
        channels = [
            BrandChannel(
                source=source,
                channel_name=channel,
                channel_url=url,
                verified=bool(verified),
            )
            for source, channel, url, verified in cur.fetchall()
            if channel
        ]

        cur.execute(
            """
            SELECT phrase
            FROM brand_exclusions
            WHERE brand_id = %s
            """,
            (loaded_brand_id,),
        )
        exclusions = remove_self_exclusions(
            loaded_brand_name,
            aliases,
            [*(phrase for (phrase,) in cur.fetchall() if phrase), *negative_terms],
        )

    return BrandProfile(
        brand_id=str(loaded_brand_id),
        brand_name=loaded_brand_name,
        aliases=list(aliases or []),
        official_channels=channels,
        exclusions=exclusions,
        context_keywords=list(context_terms or []),
        entity_type=entity_type,
        industry=industry,
        primary_category=primary_category,
        subcategory=subcategory,
        competitor_category=competitor_category,
        manufacturer=manufacturer,
        categories=list(categories or []),
        brand_context=brand_context,
        product_tokens=(
            [
                token for token in normalize_text(loaded_brand_name).split()
                if token not in set(normalize_text(manufacturer).split())
            ]
            if entity_type == "product" else []
        ),
        required_tokens=(
            [
                token for token in normalize_text(loaded_brand_name).split()
                if token not in set(normalize_text(manufacturer).split())
            ]
            if entity_type == "product" else []
        ),
    )


def match_brand_profile(
    profile: BrandProfile,
    *,
    text: str = "",
    title: str = "",
    channel_name: str = "",
    source: str = "",
) -> dict[str, Any]:
    """Convenience wrapper for scoring with a loaded BrandProfile."""
    return match_brand(
        brand_name=profile.brand_name,
        aliases=profile.aliases,
        text=text,
        title=title,
        channel_name=channel_name,
        source=source,
        official_channels=profile.official_channels,
        exclusions=profile.exclusions,
        context_keywords=profile.context_keywords,
        product_tokens=profile.product_tokens,
        required_tokens=profile.required_tokens,
    )
