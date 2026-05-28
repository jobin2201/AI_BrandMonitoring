from __future__ import annotations

from app.services.entity_resolution.resolver_manager import resolve_brand

INDUSTRY_PROFILES = {
    "automotive": {
        "positive_terms": ["car", "cars", "automotive", "automobile", "vehicle", "suv", "ev", "electric vehicle", "motors", "gt"],
        "negative_terms": ["animal", "wildlife", "big cat", "song", "official music video", "movie", "lyrics", "database", "python"],
    },
    "technology": {
        "positive_terms": ["technology", "software", "hardware", "ai", "cloud", "app", "platform", "device", "product"],
        "negative_terms": ["song", "lyrics", "movie", "fan edit"],
    },
    "fashion": {
        "positive_terms": ["shoes", "sneakers", "apparel", "fashion", "sportswear", "footwear", "collection"],
        "negative_terms": ["animal", "wildlife", "song", "lyrics"],
    },
    "finance": {
        "positive_terms": ["banking", "finance", "fintech", "payments", "stock", "earnings", "market"],
        "negative_terms": ["song", "lyrics", "movie"],
    },
    "default": {
        "positive_terms": ["company", "brand", "product", "service", "business", "technology", "review"],
        "negative_terms": ["song", "lyrics", "official music video", "movie", "animal", "wildlife"],
    },
}

def normalize_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def normalize_industry(value: str | None) -> str:
    lowered = (value or "").lower()
    if any(term in lowered for term in ["auto", "car", "vehicle", "transport"]):
        return "automotive"
    if any(term in lowered for term in ["tech", "software", "hardware", "electronics", "cloud", "ai"]):
        return "technology"
    if any(term in lowered for term in ["fashion", "apparel", "footwear", "sportswear"]):
        return "fashion"
    if any(term in lowered for term in ["finance", "bank", "fintech", "payment"]):
        return "finance"
    return lowered or "default"


def build_brand_profile(brand_name: str, user_aliases: list[str] | None = None) -> dict:
    resolved = {}
    try:
        resolved = resolve_brand(brand_name) or {}
    except Exception as exc:
        print(f"[BRAND PROFILE] Resolver failed for {brand_name}: {exc}")

    industry = normalize_industry(resolved.get("industry"))
    industry_profile = INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["default"])

    aliases = normalize_list(user_aliases)
    aliases.extend(normalize_list(resolved.get("aliases")))
    aliases.extend(normalize_list(resolved.get("search_terms")))
    aliases = list(dict.fromkeys(alias for alias in aliases if alias.lower() != brand_name.strip().lower()))

    positive_terms = [
        *industry_profile["positive_terms"],
        *normalize_list(resolved.get("positive_terms")),
        *normalize_list(resolved.get("context_terms")),
    ]
    negative_terms = [
        *industry_profile["negative_terms"],
        *normalize_list(resolved.get("negative_terms")),
        *normalize_list(resolved.get("ignore_terms")),
        *normalize_list(resolved.get("exclude_terms")),
    ]

    brand_context = (
        resolved.get("description")
        or f"{brand_name} is a brand/company in the {industry} industry."
    )

    return {
        "industry": industry,
        "aliases": aliases,
        "positive_terms": list(dict.fromkeys(positive_terms)),
        "negative_terms": list(dict.fromkeys(negative_terms)),
        "brand_context": brand_context,
    }
