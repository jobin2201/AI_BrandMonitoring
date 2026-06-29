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


def normalized_key(value: str) -> str:
    return " ".join((value or "").lower().split())


def sanitize_negative_terms(
    brand_name: str,
    aliases: list[str],
    terms: list[str],
    product_tokens: list[str] | None = None,
) -> list[str]:
    protected_terms = {
        normalized_key(brand_name),
        *(normalized_key(alias) for alias in aliases),
    }
    protected_terms = {term for term in protected_terms if term}
    protected_tokens = {
        token
        for term in protected_terms
        for token in term.split()
    }
    protected_tokens.update(normalized_key(token) for token in (product_tokens or []) if normalized_key(token))
    cleaned = []
    for term in terms:
        key = normalized_key(term)
        if not key:
            continue
        key_tokens = set(key.split())
        if key in protected_terms or (key_tokens and key_tokens.issubset(protected_tokens)):
            print(f"[BRAND PROFILE] Removed self-ignore term: {term}")
            continue
        cleaned.append(term)
    return list(dict.fromkeys(cleaned))


def needs_user_disambiguation(brand_name: str, resolved: dict, user_aliases: list[str] | None = None) -> bool:
    if normalize_list(user_aliases):
        return False

    confidence = float(resolved.get("confidence") or 0.0)
    source = (resolved.get("source") or "").lower()
    industry = (resolved.get("industry") or "").lower()
    entity_name = (resolved.get("entity_name") or brand_name).strip()
    search_terms = normalize_list(resolved.get("search_terms"))
    aliases = normalize_list(resolved.get("aliases"))
    disambiguating_terms = [
        term for term in [*search_terms, *aliases]
        if term.strip().lower() != brand_name.strip().lower()
    ]

    return (
        source == "fallback"
        or confidence < 0.65
        or (
            entity_name.lower() == brand_name.strip().lower()
            and industry in {"", "unknown", "general"}
            and not disambiguating_terms
        )
    )


def build_disambiguation_options(brand_name: str, resolved: dict) -> list[dict]:
    entity_name = (resolved.get("entity_name") or brand_name).strip()
    industry = normalize_industry(resolved.get("industry"))
    search_terms = normalize_list(resolved.get("search_terms"))
    aliases = normalize_list(resolved.get("aliases"))
    useful_aliases = list(dict.fromkeys([
        *aliases,
        *search_terms,
    ]))
    useful_aliases = [
        alias for alias in useful_aliases
        if alias.strip() and alias.strip() != entity_name and alias.strip() != brand_name.strip()
    ]

    options = []
    if entity_name and entity_name.lower() != brand_name.strip().lower():
        options.append({
            "id": "resolved_entity",
            "label": f"{entity_name} - {industry or 'brand/company'}",
            "description": "Use this resolved brand or company identity.",
            "search_value": entity_name,
            "aliases": useful_aliases[:8],
        })

    options.append({
        "id": "brand_company",
        "label": f"{brand_name} - brand/company/product",
        "description": "Use this when you mean a monitored commercial brand.",
        "search_value": brand_name,
        "aliases": useful_aliases[:8],
    })
    options.append({
        "id": "generic_topic",
        "label": f"{brand_name} - generic topic",
        "description": "Use this when you mean the common word or broad topic.",
        "search_value": brand_name,
        "aliases": [],
    })
    options.append({
        "id": "something_else",
        "label": "Something else",
        "description": "Use the current text and continue without automatic disambiguation.",
        "search_value": brand_name,
        "aliases": [],
    })

    unique = []
    seen = set()
    for option in options:
        key = (option["id"], option["search_value"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(option)
    return unique


def build_brand_profile(brand_name: str, user_aliases: list[str] | None = None) -> dict:
    resolved = {}
    try:
        resolved = resolve_brand(brand_name) or {}
    except Exception as exc:
        print(f"[BRAND PROFILE] Resolver failed for {brand_name}: {exc}")

    industry = normalize_industry(resolved.get("industry"))
    industry_profile = INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["default"])
    entity_type = resolved.get("entity_type") or "brand"
    primary_category = resolved.get("primary_category") or resolved.get("category") or ""
    subcategory = resolved.get("subcategory") or resolved.get("segment") or ""
    competitor_category = resolved.get("competitor_category") or resolved.get("comparison_category") or primary_category
    manufacturer = resolved.get("manufacturer") or ""
    company = resolved.get("company") or manufacturer or (
        resolved.get("entity_name") if entity_type == "product" else ""
    )
    product = resolved.get("product") or (brand_name if entity_type == "product" else "")
    product_tokens = normalize_list(resolved.get("product_tokens"))
    required_tokens = normalize_list(resolved.get("required_tokens"))
    categories = normalize_list(resolved.get("categories"))

    aliases = normalize_list(user_aliases)
    aliases.extend(normalize_list(resolved.get("aliases")))
    aliases.extend(normalize_list(resolved.get("search_terms")))
    aliases = list(dict.fromkeys(alias for alias in aliases if alias.strip() != brand_name.strip()))

    positive_terms = [
        *industry_profile["positive_terms"],
        *categories,
        primary_category,
        subcategory,
        competitor_category,
        *normalize_list(resolved.get("positive_terms")),
        *normalize_list(resolved.get("context_terms")),
    ]
    negative_terms = [
        *industry_profile["negative_terms"],
        *normalize_list(resolved.get("negative_terms")),
        *normalize_list(resolved.get("ignore_terms")),
        *normalize_list(resolved.get("exclude_terms")),
    ]
    negative_terms = sanitize_negative_terms(brand_name, aliases, negative_terms, product_tokens)

    brand_context = (
        resolved.get("description")
        or f"{brand_name} is a brand/company in the {industry} industry."
    )

    return {
        "entity_type": entity_type,
        "industry": industry,
        "primary_category": primary_category,
        "subcategory": subcategory,
        "competitor_category": competitor_category,
        "manufacturer": manufacturer,
        "company": company,
        "product": product,
        "product_tokens": product_tokens,
        "required_tokens": required_tokens,
        "categories": list(dict.fromkeys(categories)),
        "aliases": aliases,
        "positive_terms": list(dict.fromkeys(term for term in positive_terms if term)),
        "negative_terms": list(dict.fromkeys(negative_terms)),
        "brand_context": brand_context,
        "needs_disambiguation": needs_user_disambiguation(brand_name, resolved, user_aliases),
        "disambiguation_options": build_disambiguation_options(brand_name, resolved),
        "entity_resolution": {
            "source": resolved.get("source") or "unknown",
            "confidence": float(resolved.get("confidence") or 0.0),
            "entity_name": resolved.get("entity_name") or brand_name,
            "entity_type": entity_type,
            "primary_category": primary_category,
            "subcategory": subcategory,
            "competitor_category": competitor_category,
            "manufacturer": manufacturer,
            "company": company,
            "product": product,
            "product_tokens": product_tokens,
            "required_tokens": required_tokens,
            "categories": list(dict.fromkeys(categories)),
        },
    }
