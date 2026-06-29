from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv

from app.services.entity_resolution.wikipedia_resolver import wikipedia_resolve

BACKEND_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(BACKEND_ENV_PATH, override=True)


def get_competitor_int_env(name: str, default: int) -> int:
    load_dotenv(BACKEND_ENV_PATH, override=True)
    raw_value = os.getenv(name, str(default))
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        print(f"[COMPETITOR] Invalid {name}={raw_value!r}; using {default}")
        return default

def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def valid_match_term(term: str) -> bool:
    normalized = normalize(term)
    if not normalized:
        return False
    if normalized.isdigit():
        return False
    if len(normalized) < 3:
        return False
    return True


def compact_product_term(term: str) -> str:
    normalized = normalize(term)
    tokens = normalized.split()
    if len(tokens) >= 2 and any(char.isdigit() for char in tokens[-1]):
        return "".join(tokens)
    return ""


def term_matches_text(text: str, term: str) -> bool:
    if not valid_match_term(term):
        return False
    normalized_text = f" {normalize(text)} "
    normalized_term = normalize(term)
    if not normalized_term:
        return False

    tokens = normalized_term.split()
    if len(tokens) >= 2:
        phrase = " ".join(tokens)
        if f" {phrase} " in normalized_text:
            return True
        compact = "".join(tokens)
        compact_text = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
        return bool(compact and compact in compact_text)

    if any(char.isdigit() for char in normalized_term):
        compact_text = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
        return normalized_term in compact_text

    return f" {normalized_term} " in normalized_text


def parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(raw[index:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        snippets = [match.group(0)] if match else []
        snippets.append(raw)
        for snippet in snippets:
            try:
                obj = ast.literal_eval(snippet)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        raise json.JSONDecodeError("No valid JSON object found", raw, 0)


COMPARISON_TERMS = [
    " vs ",
    " versus ",
    " compared with ",
    " compared to ",
    " better than ",
    " worse than ",
    " switched from ",
    " switch from ",
    " alternative to ",
    " competition with ",
]

COMPARISON_RE = re.compile(
    r"(\bvs\b|\bversus\b|\bcompared\s+(?:with|to)\b|\bbetter\s+than\b|\bworse\s+than\b|\bswitched\s+from\b|\bswitch\s+from\b|\balternative\s+to\b|\bcompetition\s+with\b)",
    re.IGNORECASE,
)

FEATURE_SIGNAL_RE = re.compile(
    r"\b(available on|now available|rolled out|rolling out|release|released|releases|launch|launched|launches|introduces|introduced|unveils|unveiled|debuts|debuted|added support|adds support|new feature|upgrade|upgraded|update|updated|integration|integrated with|oled|rtx|gpu|processor|battery|display|gaming laptop)\b",
    re.IGNORECASE,
)

NON_FEATURE_SIGNAL_RE = re.compile(
    r"\b(ties up|tie up|partnership|partnered|sponsorship|screening|screenings|world cup|broadcast|box office)\b",
    re.IGNORECASE,
)

ZERO_SHOT_LABELS = [
    "pricing",
    "feature announcement",
    "hiring",
    "funding",
    "merger acquisition",
    "layoffs termination",
    "competitor comparison",
    "general news",
]

METRIC_DESCRIPTIONS = {
    "sentiment": {
        "title": "Competitor Sentiment",
        "short": "How people feel about the competitor",
        "definition": (
            "Measures whether mentions of the competitor are mostly positive, "
            "neutral, or negative across news, social media, and other sources."
        ),
    },
    "sov": {
        "title": "Market Share of Voice",
        "short": "How much attention they get vs you",
        "definition": (
            "Compares how often your brand is mentioned versus competitors, "
            "indicating relative visibility and attention in the market."
        ),
    },
    "features": {
        "title": "Feature Announcements",
        "short": "What new things they are launching",
        "definition": (
            "Tracks newly launched products, features, integrations, updates, "
            "releases, or service improvements announced by competitors."
        ),
    },
    "ma": {
        "title": "Mergers",
        "short": "Who they are buying or merging with",
        "definition": (
            "Identifies mergers, acquisitions, buyouts, partnerships involving "
            "ownership changes, or major corporate consolidation activities."
        ),
    },
    "hiring": {
        "title": "Hiring Trends",
        "short": "Whether they are growing their team",
        "definition": (
            "Monitors recruitment activity, workforce growth, job postings, "
            "visa filings, team expansion, and talent acquisition signals."
        ),
    },
    "funding": {
        "title": "Funding",
        "short": "How much money they are raising",
        "definition": (
            "Tracks investments, funding rounds, venture capital activity, "
            "valuations, fundraising events, and major investor involvement."
        ),
    },
    "pricing": {
        "title": "Pricing",
        "short": "How they price their products/services",
        "definition": (
            "Detects pricing strategies, subscription plans, discounts, package "
            "changes, API costs, token pricing, and product/service pricing updates."
        ),
    },
    "terminations": {
        "title": "Terminations",
        "short": "Whether they are cutting staff or shutting things down",
        "definition": (
            "Monitors layoffs, workforce reductions, office closures, product "
            "discontinuations, restructuring, and shutdown-related activities."
        ),
    },
}

METRIC_QUERY_TERMS = {
    "pricing": [
        "pricing", "price", "ticket prices", "discount", "offer",
        "subscription", "membership", "premium", "package changes",
        "product pricing", "service pricing",
    ],
    "features": [
        "launch", "feature", "update", "new service", "opens",
        "expansion", "available", "rollout", "integration",
        "service improvement", "new product",
    ],
    "hiring": [
        "hiring", "jobs", "recruitment", "workforce", "employees",
        "expansion", "new locations", "talent acquisition",
        "team expansion", "job postings",
    ],
    "funding": [
        "funding", "investment", "investor", "valuation", "capital",
        "financing", "parent company funding", "fundraising",
        "venture capital", "funding round", "strategic capital",
        "receives backing", "investor support", "credit facility",
        "debt financing", "capital infusion",
    ],
    "ma": [
        "acquisition", "merger", "partnership", "joint venture",
        "strategic alliance", "stake", "buyout", "ownership change",
        "consolidation",
    ],
    "terminations": [
        "layoffs", "job cuts", "workforce reduction", "closure",
        "restructuring", "discontinued", "office closure",
        "product discontinuation",
    ],
    "comparison": [
        "vs", "versus", "compared with", "alternative to", "competitor",
    ],
}

INDUSTRY_QUERY_TERMS = {
    "cinema": {
        "features": ["multiplex expansion", "new screens", "new locations", "premium format", "IMAX", "VIP cinema"],
        "hiring": ["screen expansion", "multiplex expansion", "new locations", "operations hiring"],
        "pricing": ["ticket prices", "weekday offer", "student offer", "food pricing", "membership"],
    },
    "smartphone": {
        "features": ["camera update", "software update", "launch", "availability", "AI features"],
        "hiring": ["mobile division hiring", "manufacturing expansion", "engineering jobs"],
        "pricing": ["discount", "offer", "price cut", "trade in", "subscription"],
    },
    "automotive": {
        "features": ["launch", "variant", "facelift", "EV", "safety features", "booking"],
        "hiring": ["plant expansion", "dealer expansion", "manufacturing hiring"],
        "pricing": ["price hike", "discount", "offer", "ex showroom price"],
    },
    "ai": {
        "features": ["model launch", "API update", "integration", "agent", "available"],
        "hiring": ["research hiring", "AI engineer", "workforce", "recruitment"],
        "pricing": ["API pricing", "subscription", "enterprise plan", "tokens"],
        "funding": ["funding", "valuation", "investor", "investment round"],
    },
}

BUCKET_TO_KEY = {
    "pricing": "pricing",
    "feature announcement": "features",
    "hiring": "hiring",
    "funding": "funding",
    "merger acquisition": "ma",
    "layoffs termination": "terminations",
    "competitor comparison": "comparison",
    "general news": "general",
}

BUCKET_KEYWORDS = {
    "pricing": [
        "pricing", "msrp", "discount", "sale", "price cut", "price drop",
        "off", "subscription", "membership", "cost", "₹", "$", "rs", "inr",
    ],
    "features": [
        "launch", "launched", "launches", "introduces", "introduced",
        "release", "available", "rolls out", "new feature", "oled", "rtx",
        "gpu", "processor", "battery", "display", "gaming laptop", "upgrade",
        "update", "integration",
    ],
    "hiring": [
        "hiring", "to hire", "recruiting", "recruitment drive",
        "job openings", "headcount growth", "staff expansion",
        "team expansion", "talent acquisition", "workforce expansion",
        "new roles",
    ],
    "funding": [
        "funding", "raised", "raises", "valuation", "investor",
        "investment", "series", "backed by", "capital",
        "strategic capital", "receives backing", "investor support",
        "credit facility", "debt financing", "capital infusion",
    ],
    "ma": [
        "acquisition", "acquires", "acquired", "merger", "merged",
        "partnership", "joint venture", "strategic alliance", "stake",
    ],
    "terminations": [
        "layoff", "layoffs", "job cuts", "workforce reduction",
        "employee reduction", "staff reduction", "workforce cuts",
        "cuts jobs", "office closure", "store closure", "plant closure",
        "factory closure", "headcount reduction", "staff cuts",
        "retrenchment", "redundancies",
    ],
    "comparison": [
        "vs", "versus", "compared to", "compared with", "better than",
        "worse than", "alternative to", "competition with",
    ],
}

METRIC_REQUIRED_TERMS = {
    "pricing": [
        "pricing", "msrp", "discount", "sale", "price cut", "price drop",
        "off", "subscription", "membership", "cost", "rs", "inr", "₹", "$",
    ],
    "features": [
        "launch", "launched", "launches", "feature", "new feature",
        "introduces", "introducing", "introduced", "release", "released",
        "upgrade", "update", "available", "rollout", "rolls out", "unveils",
        "oled", "rtx", "gpu", "processor", "battery", "display",
        "gaming laptop", "integration",
    ],
    "hiring": [
        "hire", "hiring", "recruitment", "job opening", "job openings",
        "employee growth", "expands team", "team expansion",
        "talent acquisition", "recruiter", "staff expansion",
        "headcount growth", "new roles", "to hire",
    ],
    "funding": [
        "raised", "raises", "funding", "investment", "investor",
        "venture", "series a", "series b", "series c", "financing",
        "capital", "seed round", "fundraising", "valuation",
        "strategic capital", "receives backing", "investor support",
        "credit facility", "debt financing", "capital infusion",
    ],
    "ma": [
        "acquisition", "acquire", "acquires", "acquired", "merger",
        "merged", "buyout", "purchase", "purchased", "takeover",
    ],
    "terminations": [
        "layoff", "layoffs", "laid off", "job cuts", "workforce reduction",
        "employee reduction", "staff reduction", "workforce cuts",
        "downsizing", "cuts jobs", "headcount reduction", "staff cuts",
        "retrenchment", "redundancies", "office closure", "store closure",
        "plant closure", "factory closure",
    ],
    "comparison": [
        " vs ", " versus ", "compared to", "compared with", "better than",
        "worse than", "alternative to", "competition with",
    ],
}

PRODUCT_LEVEL_METRICS = {"pricing", "features", "comparison"}
CORPORATE_LEVEL_METRICS = {"hiring", "funding", "ma", "terminations"}

CONSUMER_REVIEW_SOURCES = {"youtube", "reddit"}
CONSUMER_CONTENT_RE = re.compile(
    r"\b("
    r"review|unboxing|first look|hands on|hands-on|walkthrough|tutorial|"
    r"how to|setup|benchmark|benchmarks|gaming test|gameplay|fps|thermals|"
    r"overclock|specs|specifications|camera test|battery test|performance test|"
    r"vs|versus|comparison|compared|price|deal|buy|sale|discount|"
    r"gaming laptop|laptop review|phone review|smartphone review"
    r")\b",
    re.IGNORECASE,
)
BUSINESS_METRIC_REQUIRED_RE = {
    "hiring": re.compile(
        r"\b(hiring|to hire|hire \d+|recruiting|recruitment|job openings|"
        r"new roles|headcount growth|staff expansion|team expansion|"
        r"talent acquisition|workforce expansion|expands workforce|"
        r"visa sponsorship|h-?1b)\b",
        re.IGNORECASE,
    ),
    "funding": re.compile(
        r"\b(funding round|raises?|raised|fundraising|investment|investor|"
        r"valuation|venture capital|seed round|series [a-z]|financing|"
        r"capital infusion|strategic capital|credit facility|debt financing|"
        r"receives backing|investor support)\b",
        re.IGNORECASE,
    ),
    "ma": re.compile(
        r"\b(acquisition|acquires?|acquired|merger|merged|buyout|takeover|"
        r"purchased|ownership stake|stake acquisition|joint venture|"
        r"strategic alliance|consolidation|to buy|buys)\b",
        re.IGNORECASE,
    ),
    "terminations": re.compile(
        r"\b(layoffs?|laid off|job cuts|cuts jobs|workforce reduction|"
        r"employee reduction|staff reduction|workforce cuts|headcount reduction|"
        r"staff cuts|retrenchment|redundancies|office closure|store closure|"
        r"plant closure|factory closure|shuts down operations|ceased operations|"
        r"discontinued operations)\b",
        re.IGNORECASE,
    ),
}
RESTRUCTURING_WITH_WORKFORCE_RE = re.compile(
    r"\b(restructuring|restructure)\b.*\b(workforce|employees?|staff|jobs|headcount|operations)\b|"
    r"\b(workforce|employees?|staff|jobs|headcount|operations)\b.*\b(restructuring|restructure)\b",
    re.IGNORECASE,
)


def keyword_terms(competitor_profile: dict[str, Any]) -> list[str]:
    terms = [
        competitor_profile.get("competitor_name") or competitor_profile.get("competitor") or "",
        competitor_profile.get("competitor_company") or "",
        competitor_profile.get("competitor_product") or "",
        competitor_profile.get("manufacturer") or "",
    ]
    for key in [
        "product_names",
        "service_names",
        "campaign_names",
        "hashtags",
        "competitor_keywords",
    ]:
        value = competitor_profile.get(key)
        if isinstance(value, list):
            terms.extend(str(item) for item in value)
        elif isinstance(value, str):
            terms.extend(part.strip() for part in value.split(","))
    cleaned = []
    for term in dict.fromkeys(term.strip() for term in terms):
        if not valid_match_term(term):
            continue
        cleaned.append(term)
        compact = compact_product_term(term)
        if compact and compact != normalize(term):
            cleaned.append(compact)
    return [term for term in dict.fromkeys(cleaned) if term]


def looks_like_product_name(value: str) -> bool:
    normalized = normalize(value)
    tokens = normalized.split()
    if len(tokens) < 2:
        return False
    if any(any(char.isdigit() for char in token) for token in tokens):
        return True
    product_words = {
        "phone", "iphone", "galaxy", "pixel", "reno", "edge", "thinkpad",
        "tuf", "gaming", "laptop", "macbook", "watch", "buds", "airpods",
        "seltos", "creta", "kushaq", "kylaq", "model",
    }
    return any(token in product_words for token in tokens)


def infer_competitor_entity_info(competitor_profile: dict[str, Any]) -> dict[str, str]:
    name = (
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or ""
    ).strip()
    company = (
        competitor_profile.get("competitor_company")
        or competitor_profile.get("manufacturer")
        or competitor_profile.get("company")
        or ""
    ).strip()
    product = (
        competitor_profile.get("competitor_product")
        or (product_or_service_terms(competitor_profile)[0] if product_or_service_terms(competitor_profile) else "")
    ).strip()
    entity_type = (competitor_profile.get("entity_type") or "").strip().lower()

    if product:
        entity_type = entity_type or "product"
        company = company or name
    elif looks_like_product_name(name):
        tokens = name.split()
        entity_type = entity_type or "product"
        if not company and len(tokens) >= 3:
            company = tokens[0]
            product = " ".join(tokens[1:])
        else:
            product = name
    else:
        entity_type = entity_type or "company"
        company = company or name

    return {
        "entity_type": entity_type,
        "company": company,
        "product": product,
    }


def enrich_competitor_profile(competitor_profile: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(competitor_profile or {})
    info = infer_competitor_entity_info(enriched)
    enriched.setdefault("entity_type", info["entity_type"])
    if info["company"]:
        enriched.setdefault("competitor_company", info["company"])
    if info["product"]:
        enriched.setdefault("competitor_product", info["product"])
        products = profile_values(enriched, "product_names")
        if not any(normalize(item) == normalize(info["product"]) for item in products):
            enriched["product_names"] = [*products, info["product"]]
    return enriched


def product_family_terms(terms: list[str]) -> list[str]:
    families = []
    for term in terms:
        clean = re.sub(r"[\"]+", " ", term or "").strip()
        tokens = clean.split()
        if len(tokens) >= 2 and any(char.isdigit() for char in tokens[-1]):
            families.append(" ".join(tokens[:-1]))
        if tokens and tokens[0].lower() in {"iphone", "galaxy", "pixel", "thinkpad", "macbook"}:
            families.append(tokens[0])
    return [term for term in dict.fromkeys(families) if len(term) >= 3]


def brand_identity_terms(brand: dict[str, Any]) -> list[str]:
    terms = [
        brand.get("brand_name") or "",
        *(brand.get("aliases") or []),
        *(brand.get("product_names") or []),
        *(brand.get("service_names") or []),
    ]
    terms.extend(product_family_terms([str(term) for term in terms]))
    return [term for term in dict.fromkeys(str(term).strip() for term in terms) if term]


def mention_matches(text: str, terms: list[str]) -> bool:
    for term in terms:
        if term_matches_text(text, term):
            return True
    return False


def is_direct_comparison(text: str, brand_terms: list[str], competitor_terms: list[str]) -> bool:
    has_brand = term_present(text, brand_terms)
    has_competitor = term_present(text, competitor_terms)
    has_comparison_language = bool(COMPARISON_RE.search(text or ""))
    return bool(has_brand and has_competitor and has_comparison_language)


def evidence_item(mention: dict[str, Any], reason: str = "") -> dict[str, Any]:
    text = " ".join([mention.get("title") or "", mention.get("body_text") or ""]).strip()
    return {
        "title": mention.get("title") or text[:120],
        "source": mention.get("source") or "",
        "source_name": mention.get("source_name") or "",
        "sentiment": mention.get("sentiment_label") or "",
        "published_at": mention.get("published_at") or "",
        "url": mention.get("url") or "",
        "reason": reason,
        "snippet": text[:240],
    }


def empty_pricing() -> dict[str, Any]:
    return {
        "price_points": [],
        "average_price": None,
        "evidence_count": 0,
        "examples": [],
    }


def empty_hiring() -> dict[str, Any]:
    return {
        "trend": "no_signal",
        "evidence_count": 0,
        "evidence": [],
    }


def empty_intelligence_result(
    brand_id: str,
    brand: dict[str, Any],
    competitor_profile: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    return {
        "brand_id": brand_id,
        "brand": brand.get("brand_name") or "",
        "competitor": competitor_profile.get("competitor_name") or competitor_profile.get("competitor") or "",
        "keywords": keyword_terms(competitor_profile),
        "metric_descriptions": METRIC_DESCRIPTIONS,
        "sentiment": {
            "counts": {"neutral": 0, "positive": 0, "negative": 0},
            "percentages": {"neutral": 0.0, "positive": 0.0, "negative": 0.0},
            "total_mentions": 0,
        },
        "share_of_voice": {
            "brand": 0,
            "competitor": 0,
            "brand_mentions": 0,
            "competitor_mentions": 0,
        },
        "pricing": empty_pricing(),
        "feature_announcements": [],
        "hiring_trends": empty_hiring(),
        "funding": [],
        "mergers": [],
        "terminations": [],
        "temporary": True,
        "stored": False,
        "error": error,
        "evidence": {
            "brand_mentions_scanned": 0,
            "competitor_mentions_matched": 0,
            "metric_google_news_mentions": 0,
            "metric_retrieval_summary": {},
            "direct_comparison_mentions": 0,
            "competitor_examples": [],
            "direct_comparison_examples": [],
            "pricing_examples": [],
            "feature_examples": [],
            "hiring_examples": [],
            "funding_examples": [],
            "merger_examples": [],
            "termination_examples": [],
            "metric_google_news_examples": [],
            "llm_metric_signal_used": False,
        },
    }


def safe_metric_step(name: str, default: Any, func, *args):
    try:
        value = func(*args)
        return default if value is None else value
    except Exception as exc:
        print(f"[COMPETITOR] {name} failed; using empty result: {exc}")
        return default


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def profile_values(profile: dict[str, Any], key: str) -> list[str]:
    value = profile.get(key)
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = []
    return [item.strip() for item in (str(item) for item in raw_values) if item.strip()]


def text_for_mention(mention: dict[str, Any]) -> str:
    return " ".join([mention.get("title") or "", mention.get("body_text") or ""]).strip()


def compact_evidence(mentions: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    return [
        {
            "title": mention.get("title") or "",
            "body_text": (mention.get("body_text") or "")[:280],
            "source": mention.get("source") or "",
            "metric": mention.get("metric") or "",
            "query": mention.get("query") or "",
            "sentiment_label": mention.get("sentiment_label") or "",
            "published_at": mention.get("published_at") or "",
            "url": mention.get("url") or "",
        }
        for mention in mentions[:limit]
    ]


def term_present(text: str, terms: list[str]) -> bool:
    return any(term_matches_text(text, term) for term in terms)


def metric_required_terms(metric: str) -> list[str]:
    return METRIC_REQUIRED_TERMS.get(metric) or []


def business_metric_text(article: dict[str, Any]) -> str:
    return " ".join(
        str(article.get(field) or "")
        for field in [
            "title",
            "body_text",
            "description",
            "snippet",
            "event",
            "reason",
            "evidence",
            "pricing_context",
            "source_name",
        ]
    )


def is_consumer_noise_for_business_metric(article: dict[str, Any], metric: str) -> bool:
    if metric not in CORPORATE_LEVEL_METRICS:
        return False

    source = normalize(str(article.get("source") or ""))
    text = business_metric_text(article)
    normalized_text = normalize(text)

    if source in CONSUMER_REVIEW_SOURCES and CONSUMER_CONTENT_RE.search(text or ""):
        return True

    business_re = BUSINESS_METRIC_REQUIRED_RE.get(metric)
    has_business_signal = bool(business_re and business_re.search(text or ""))
    if metric == "terminations":
        has_business_signal = has_business_signal or bool(RESTRUCTURING_WITH_WORKFORCE_RE.search(text or ""))

    if has_business_signal:
        return False

    if source in CONSUMER_REVIEW_SOURCES:
        return True

    product_context_words = {
        "review", "unboxing", "hands", "benchmark", "specs", "gaming",
        "laptop", "phone", "smartphone", "camera", "battery", "display",
        "price", "deal", "buy", "performance",
    }
    if metric in {"funding", "ma", "terminations"} and any(
        f" {word} " in f" {normalized_text} " for word in product_context_words
    ):
        return True

    return False


def is_business_fallback_candidate(article: dict[str, Any], metric: str) -> bool:
    """
    Let company-level context through only when it is safe for LLM review.
    Product reviews, unboxings, comparisons, and deal content should not fill
    hiring/funding/M&A/termination evidence quotas.
    """
    if metric not in CORPORATE_LEVEL_METRICS:
        return False
    if is_consumer_noise_for_business_metric(article, metric):
        return False

    source = normalize(str(article.get("source") or ""))
    if source in CONSUMER_REVIEW_SOURCES:
        return False

    text = business_metric_text(article)
    return bool(re.search(
        r"\b(company|corporate|business|operations|expansion|office|factory|"
        r"plant|workforce|employees|supplier|supply chain|earnings|revenue|"
        r"regulatory|antitrust|legal|market|shares|stock)\b",
        text or "",
        re.IGNORECASE,
    ))


def article_matches_metric(article: dict[str, Any], metric: str) -> bool:
    text = business_metric_text(article)
    if is_consumer_noise_for_business_metric(article, metric):
        return False
    if metric == "comparison":
        return bool(COMPARISON_RE.search(text or ""))
    if metric == "pricing":
        return bool(
            re.search(r"(₹|\$|\brs\.?\b|\binr\b)\s?\d", text or "", re.IGNORECASE)
            or re.search(
                r"\b(pricing|msrp|discount|sale|price\s+(?:cut|drop|hike|increase)|\d+%?\s+off|subscription|membership|costs?|priced at)\b",
                text or "",
                re.IGNORECASE,
            )
        )
    if metric == "hiring":
        return bool(BUSINESS_METRIC_REQUIRED_RE["hiring"].search(text or ""))
    if metric == "funding":
        return bool(BUSINESS_METRIC_REQUIRED_RE["funding"].search(text or ""))
    if metric == "ma":
        return bool(BUSINESS_METRIC_REQUIRED_RE["ma"].search(text or ""))
    if metric == "terminations" and re.search(
        r"\b(shutdown|shut down|restart|power off|turn off|boot|bios|driver|laptop|phone|device|how to)\b",
        text or "",
        re.IGNORECASE,
    ):
        return False
    if metric == "terminations":
        return bool(
            BUSINESS_METRIC_REQUIRED_RE["terminations"].search(text or "")
            or RESTRUCTURING_WITH_WORKFORCE_RE.search(text or "")
        )
    terms = metric_required_terms(metric)
    if not terms:
        return True
    return term_present(text, terms)


def profile_match_terms(competitor_profile: dict[str, Any]) -> list[str]:
    terms = [
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or "",
        competitor_profile.get("competitor_company") or "",
        competitor_profile.get("competitor_product") or "",
        competitor_profile.get("manufacturer") or "",
    ]
    for key in [
        "product_names",
        "service_names",
        "campaign_names",
        "hashtags",
        "competitor_keywords",
    ]:
        terms.extend(profile_values(competitor_profile, key))
    cleaned = []
    for term in dict.fromkeys(str(term).strip() for term in terms):
        if not valid_match_term(term):
            continue
        cleaned.append(term)
        compact = compact_product_term(term)
        if compact:
            cleaned.append(compact)
    return [term for term in dict.fromkeys(cleaned) if term]


def article_matches_profile(article: dict[str, Any], competitor_profile: dict[str, Any]) -> bool:
    """
    Google News can return semantically related but wrong-company articles.
    Keep evidence only when it explicitly mentions the requested competitor,
    product, service, campaign, hashtag, or keyword.
    """
    terms = profile_match_terms(competitor_profile)
    if not terms:
        return False

    text = " ".join(
        str(article.get(field) or "")
        for field in [
            "title",
            "body_text",
            "description",
            "snippet",
            "source_name",
            "source",
        ]
    )
    return term_present(text, terms)


def requires_context_disambiguation(competitor_profile: dict[str, Any]) -> bool:
    name = normalize(
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or ""
    )
    if len(name.split()) != 1:
        return False
    return not product_or_service_terms(competitor_profile)


def wikipedia_context_terms(wikipedia_context: dict[str, Any]) -> list[str]:
    if not isinstance(wikipedia_context, dict):
        return []
    values: list[str] = []
    for key in [
        "entity_name",
        "industry",
        "entity_type",
        "primary_category",
        "subcategory",
        "competitor_category",
        "manufacturer",
    ]:
        value = wikipedia_context.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ["search_terms", "aliases", "positive_terms", "categories"]:
        value = wikipedia_context.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
    return [
        term for term in dict.fromkeys(str(term).strip() for term in values)
        if valid_match_term(term)
    ]


def resolve_wikipedia_search_term(competitor_profile: dict[str, Any]) -> str:
    info = infer_competitor_entity_info(competitor_profile)
    fallback = (
        info.get("company")
        or competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or ""
    ).strip()

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback

    name = competitor_profile.get("competitor_name") or competitor_profile.get("competitor") or ""
    prompt = f"""
Return the best Wikipedia search term for this competitor intelligence target.
Use the canonical parent company when the target is a product/model.

Input:
{json.dumps(competitor_profile, indent=2, default=str)}

Return ONLY strict JSON:
{{"search_term":"canonical Wikipedia title or search term"}}

Examples of behavior:
- Product/model target -> parent company Wikipedia term.
- Company target -> canonical company Wikipedia term.
- Ambiguous acronym -> most likely business entity from the profile context.
"""
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        payload = parse_json_object(response.choices[0].message.content or "{}")
        term = str(payload.get("search_term") or "").strip()
        return term or fallback or name
    except Exception as exc:
        print(f"[COMPETITOR] Wikipedia search-term LLM skipped: {exc}")
        return fallback or name


def get_competitor_wikipedia_context(competitor_profile: dict[str, Any]) -> dict[str, Any]:
    search_term = resolve_wikipedia_search_term(competitor_profile)
    if not search_term:
        return {}
    try:
        resolved = wikipedia_resolve(search_term)
        return resolved or {}
    except Exception as exc:
        print(f"[COMPETITOR] Wikipedia context skipped: {exc}")
        return {}


def competitor_query_terms(competitor_profile: dict[str, Any]) -> list[str]:
    terms = [
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or "",
    ]
    for key in ["product_names", "service_names", "competitor_keywords"]:
        value = competitor_profile.get(key)
        if isinstance(value, list):
            terms.extend(str(item) for item in value[:3])
        elif isinstance(value, str):
            terms.extend(part.strip() for part in value.split(",")[:3])
    return [term for term in dict.fromkeys(term.strip() for term in terms) if term]


def explicit_focus_terms(competitor_profile: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in [
        "product_names",
        "service_names",
        "campaign_names",
        "hashtags",
        "competitor_keywords",
    ]:
        terms.extend(profile_values(competitor_profile, key))
    return [term for term in dict.fromkeys(term.strip() for term in terms) if term]


def product_or_service_terms(competitor_profile: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ["product_names", "service_names"]:
        terms.extend(profile_values(competitor_profile, key))
    return [term for term in dict.fromkeys(term.strip() for term in terms) if term]



def load_brand_mentions(brand_id: str, limit: int = 300) -> list[dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT title, body_text, source, sentiment_label, sentiment_score,
                   primary_category, emotion, relevance_score, published_at, url
            FROM brand_mentions
            WHERE brand_id = %s
            ORDER BY collected_at DESC
            LIMIT %s
            """,
            (brand_id, limit),
        )
        return [
            {
                "title": row[0] or "",
                "body_text": row[1] or "",
                "source": row[2] or "",
                "sentiment_label": row[3] or "",
                "sentiment_score": row[4],
                "primary_category": row[5] or "",
                "emotion": row[6] or "",
                "relevance_score": row[7],
                "published_at": row[8].isoformat() if row[8] else "",
                "url": row[9] or "",
            }
            for row in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()


def load_competitor_mentions(
    terms: list[str],
    brand_terms: list[str],
    limit: int = 300,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT title, body_text, source, sentiment_label, sentiment_score,
                   primary_category, emotion, relevance_score, published_at, url
            FROM brand_mentions
            ORDER BY collected_at DESC
            LIMIT 1000
            """
        )
        matched = []
        direct_comparisons = []
        for row in cur.fetchall():
            mention = {
                "title": row[0] or "",
                "body_text": row[1] or "",
                "source": row[2] or "",
                "sentiment_label": row[3] or "",
                "sentiment_score": row[4],
                "primary_category": row[5] or "",
                "emotion": row[6] or "",
                "relevance_score": row[7],
                "published_at": row[8].isoformat() if row[8] else "",
                "url": row[9] or "",
            }
            text = " ".join([mention["title"], mention["body_text"]])
            if mention_matches(text, terms):
                if is_direct_comparison(text, brand_terms, terms):
                    mention["match_type"] = "direct_comparison"
                    direct_comparisons.append(mention)
                else:
                    mention["match_type"] = "keyword_mention"
                matched.append(mention)
            if len(matched) >= limit:
                break
        return matched, direct_comparisons[:50]
    finally:
        cur.close()
        conn.close()
