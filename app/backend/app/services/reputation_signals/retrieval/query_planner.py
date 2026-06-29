from __future__ import annotations

import os
import re
from typing import Any

from app.services.competitor_intelligence.intelligence_common import (
    enrich_competitor_profile,
    infer_competitor_entity_info,
    normalize,
)
from app.services.reputation_signals.engine.common import _as_list, _unique_strings

def _subjects(profile: dict[str, Any]) -> dict[str, str]:
    if isinstance(profile.get("_reputation_subjects"), dict):
        return profile["_reputation_subjects"]

    enriched = enrich_competitor_profile(profile)
    info = infer_competitor_entity_info(enriched)
    company = info.get("company") or enriched.get("competitor_name") or enriched.get("competitor") or ""
    product = info.get("product") or enriched.get("competitor_product") or ""
    return {
        "company": company.strip(),
        "product": product.strip(),
        "primary": (product or company).strip(),
    }


def _limited_unique_queries(queries: list[str], limit: int | None = None) -> list[str]:
    max_queries = limit or int(os.getenv("REPUTATION_MAX_QUERIES_PER_CATEGORY", "5"))
    cleaned: list[str] = []
    seen = set()
    for query in queries:
        text = " ".join(str(query or "").split()).strip()
        if not text:
            continue
        key = normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_queries:
            break
    return cleaned


def _brand_intelligence(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("_brand_intelligence")
    return value if isinstance(value, dict) else {}


def _intelligence_values(intelligence: dict[str, Any], *keys: str, limit: int = 8) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(_as_list(intelligence.get(key)))
    return _unique_strings(values)[:limit]


def _product_aliases(product: str, company: str = "") -> list[str]:
    product = " ".join(str(product or "").split()).strip()
    company = " ".join(str(company or "").split()).strip()
    if not product:
        return []

    aliases = [product]
    product_tokens = product.split()
    company_tokens = normalize(company).split()
    company_token_set = {
        token for token in company_tokens
        if token not in {"inc", "ltd", "limited", "corp", "corporation", "company", "group"}
    }

    remaining_tokens = product_tokens[:]
    while remaining_tokens and normalize(remaining_tokens[0]) in company_token_set:
        remaining_tokens = remaining_tokens[1:]
    if remaining_tokens and len(remaining_tokens) != len(product_tokens):
        remaining_name = " ".join(remaining_tokens)
        aliases.append(remaining_name)
        compact_remaining = "".join(normalize(remaining_name).split())
        if compact_remaining and compact_remaining != normalize(remaining_name):
            aliases.append(compact_remaining)
            aliases.append(compact_remaining.upper())
            aliases.append(compact_remaining.title())

    if remaining_tokens:
        family = remaining_tokens[0]
        if len(family) >= 3 and not any(char.isdigit() for char in family):
            aliases.append(family)
            aliases.append(family.upper())
        if len(remaining_tokens) >= 2:
            compact_family_model = "".join(normalize(" ".join(remaining_tokens[:2])).split())
            if compact_family_model:
                aliases.append(compact_family_model)
                aliases.append(compact_family_model.upper())
                aliases.append(compact_family_model.title())

    normalized_compact = "".join(normalize(product).split())
    if normalized_compact and normalized_compact != normalize(product):
        aliases.append(normalized_compact)
        aliases.append(normalized_compact.upper())
        aliases.append(normalized_compact.title())

    return _unique_strings(aliases)


COMPANY_VALIDATED_CATEGORIES = {
    "esg",
    "investments",
    "regulatory",
    "layoffs",
    "fraud",
    "executive",
}


def _replace_alias_surface(query: str, alias: str, replacement: str) -> str:
    if not query or not alias or not replacement:
        return query
    pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
    return re.sub(pattern, replacement, query, flags=re.IGNORECASE)


def _company_scoped_query(query: str, company: str, product_aliases: list[str]) -> str:
    text = " ".join(str(query or "").split()).strip()
    company = " ".join(str(company or "").split()).strip()
    if not text or not company:
        return text
    scoped = text
    for alias in sorted(product_aliases, key=len, reverse=True):
        if normalize(alias) == normalize(company):
            continue
        scoped = _replace_alias_surface(scoped, alias, company)
    if normalize(company) not in normalize(scoped).split() and normalize(company) not in normalize(scoped):
        scoped = f"{company} {scoped}"
    return " ".join(scoped.split())


def _queries(profile: dict[str, Any]) -> dict[str, list[str]]:
    subjects = _subjects(profile)
    company = subjects["company"]
    product = subjects["product"]
    primary = subjects["primary"]
    intelligence = _brand_intelligence(profile)
    category_queries = intelligence.get("category_queries") if isinstance(intelligence.get("category_queries"), dict) else {}
    products = _intelligence_values(intelligence, "products", "product_lines", limit=8)
    executives = _intelligence_values(intelligence, "executives", "founders", "leadership", limit=8)
    investors = _intelligence_values(intelligence, "investors", "funding_entities", limit=8)
    partners = _intelligence_values(intelligence, "strategic_partners", "partners", "parent_company", limit=8)
    keywords = _intelligence_values(intelligence, "important_keywords", "industry_keywords", limit=10)

    product_aliases = _product_aliases(product or primary, company)
    product_focus = _unique_strings(product_aliases, products[:4]) or [primary]
    executive_focus = executives[:4] or [company]
    investment_focus = [company, *investors[:3], *partners[:2]]
    esg_focus = [company, *keywords[:4]]

    base_queries = {
        "product": [
            f"{primary} product recall defect complaint review",
            f"{primary} defect quality issue durability",
            f"{primary} battery issue overheating performance problem",
            f"{primary} benchmark review thermal throttling",
            f"{primary} product launch new collection collaboration",
            f"{primary} award best-selling top rated review",
            f"{primary} new feature app update service launch",
            f"{primary} subscription tier pricing user experience update",
            *[f"{name} review quality complaint" for name in product_focus if name and name != primary],
            *[f"{name} launch award customer feedback" for name in product_focus if name and name != primary],
        ],
        "esg": [
            f"{company} sustainability initiative CSR social impact",
            f"{company} environmental program climate emissions renewable energy",
            f"{company} community partnership education inclusion",
            f"{company} employee welfare diversity safety human rights",
            f"{company} governance ethics transparency sustainability report",
            *[f"{company} {term} CSR sustainability" for term in esg_focus if term and normalize(term) != normalize(company)],
        ],
        "investments": [
            f"{company} investment expansion manufacturing partnership",
            f"{company} factory production capacity market expansion",
            f"{company} funding investors valuation IPO",
            f"{company} acquisition joint venture strategic investment",
            f"{company} divestment exit withdrawal stake sale",
            *[f"{entity} {company} investment funding valuation" for entity in investment_focus if entity and normalize(entity) != normalize(company)],
        ],
        "regulatory": [
            f"{company} investigation legal dispute lawsuit",
            f"{company} consumer court consumer protection complaint",
            f"{company} tax issue compliance violation regulatory action",
            f"{company} fine penalty court order settlement",
            f"{company} privacy antitrust product compliance recall notice",
        ],
        "complaints": [
            f"{primary} customer complaints refund delay poor service",
            f"{primary} worst experience complaint consumer issue",
            f"{primary} battery overheating not working issue",
            *[f"{name} customer complaint defect refund issue" for name in product_focus if name and name != primary],
        ],
        "security": [
            f"{company} data breach cyber attack privacy leak",
            f"{company} ransomware security incident customer data exposed",
            f"{company} app privacy issue data leak security",
            f"{primary} security vulnerability firmware BIOS driver",
            *[f"{name} privacy security issue data" for name in product_focus if name and name != primary],
        ],
        "layoffs": [
            f"{company} layoffs job cuts workforce reduction",
            f"{company} salary delay delayed pay unpaid wages",
            f"{company} hiring freeze restructuring employees workforce",
        ],
        "fraud": [
            f"{company} fraud investigation financial misconduct",
            f"{company} scam corruption bribery allegations",
            f"{company} tax fraud accounting irregularities legal case",
            f"{company} counterfeit fake product enforcement",
        ],
        "executive": [
            f"{company} leadership management executive changes",
            f"{company} CEO founder chairman board changes",
            f"{company} executive resignation appointment restructuring",
            f"{company} leadership controversy investigation misconduct",
            f"{company} management dispute organizational shakeup",
            *[f"{person} {company} interview leadership controversy" for person in executive_focus if person and normalize(person) != normalize(company)],
            *[f"{person} statement resignation investigation" for person in executive_focus if person and normalize(person) != normalize(company)],
        ],
    }

    expanded: dict[str, list[str]] = {}
    for category, queries in base_queries.items():
        llm_queries = [
            str(query or "")
            for query in _as_list(category_queries.get(category))
        ]
        if product and company and category in COMPANY_VALIDATED_CATEGORIES:
            llm_queries = [
                _company_scoped_query(query, company, product_aliases)
                for query in llm_queries
            ]
        expanded[category] = _limited_unique_queries([*llm_queries, *queries])
    return expanded
