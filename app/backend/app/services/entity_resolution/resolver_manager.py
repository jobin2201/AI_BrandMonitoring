from __future__ import annotations

import os
import re
from datetime import datetime
import uuid

import psycopg2
from dotenv import load_dotenv

from app.services.observability.api_call_logger import log_api_call
from app.services.observability.db_operation_logger import log_db_operation
from app.services.observability.entity_trace_logger import EntityTraceLogger
from app.services.observability.resolver_trace_store import append_resolver_event

from .entity_cache import get_cached_entity, set_cached_entity
from .entity_detector import resolve_with_gliner
from .llm_entity_resolver import groq_resolve
from .wikipedia_resolver import wikipedia_resolve

load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))

FORBIDDEN_GENERIC_ENTITY_NAMES = {
    "apple",
    "boat",
    "shell",
    "dove",
    "jaguar",
    "puma",
    "meta",
    "x",
}

FORBIDDEN_CONTEXT_TERMS = {
    "animal",
    "fruit",
    "song",
    "music",
    "lyrics",
    "nursery rhyme",
    "movie",
    "wildlife",
    "generic noun",
}


def normalize_input(value: str) -> str:
    normalized = (value or "").lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


PRODUCT_HINT_WORDS = {
    "airpods", "buds", "edge", "galaxy", "gaming", "iphone", "ipad",
    "laptop", "macbook", "model", "omen", "phone", "pixel", "reno",
    "smartwatch", "thinkpad", "tuf", "watch",
}


def looks_like_product_query(query: str, result: dict | None = None) -> bool:
    tokens = normalize_input(query).split()
    if len(tokens) < 2:
        return False
    result = result or {}
    if str(result.get("entity_type") or "").lower() == "product":
        return True
    entity_name = normalize_input(str(result.get("entity_name") or ""))
    query_name = " ".join(tokens)
    resolved_to_parent = bool(entity_name and entity_name != query_name)
    has_model_token = any(any(char.isdigit() for char in token) for token in tokens)
    has_product_hint = any(token in PRODUCT_HINT_WORDS for token in tokens)
    return resolved_to_parent and (has_model_token or has_product_hint)


def product_identity_tokens(product: str, company: str = "") -> list[str]:
    product_tokens = normalize_input(product).split()
    company_tokens = set(normalize_input(company).split())
    return list(dict.fromkeys(
        token for token in product_tokens
        if token and token not in company_tokens
    ))


def sanitize_identity_ignore_terms(result: dict) -> dict:
    cleaned = dict(result)
    protected_values = [
        cleaned.get("entity_name") or "",
        cleaned.get("company") or "",
        cleaned.get("product") or "",
        *(cleaned.get("aliases") or []),
        *(cleaned.get("search_terms") or []),
        *(cleaned.get("product_tokens") or []),
    ]
    protected_phrases = {
        normalize_input(str(value or ""))
        for value in protected_values
        if normalize_input(str(value or ""))
    }
    protected_tokens = {
        token
        for phrase in protected_phrases
        for token in phrase.split()
    }

    def sanitize(values) -> list[str]:
        kept = []
        for value in _list(values):
            normalized = normalize_input(value)
            if not normalized:
                continue
            tokens = set(normalized.split())
            if normalized in protected_phrases or (tokens and tokens.issubset(protected_tokens)):
                continue
            kept.append(value)
        return list(dict.fromkeys(kept))

    cleaned["ignore_terms"] = sanitize(cleaned.get("ignore_terms"))
    cleaned["negative_terms"] = sanitize(cleaned.get("negative_terms"))
    return cleaned


def preserve_product_identity(query: str, result: dict) -> dict:
    preserved = dict(result or {})
    if not looks_like_product_query(query, preserved):
        return sanitize_identity_ignore_terms(preserved)

    resolved_name = str(preserved.get("entity_name") or "").strip()
    company = str(
        preserved.get("manufacturer")
        or preserved.get("company")
        or (resolved_name if normalize_input(resolved_name) != normalize_input(query) else "")
    ).strip()
    product = " ".join(str(query or "").split()).strip()
    tokens = product_identity_tokens(product, company)
    preserved.update({
        "entity_type": "product",
        "company": company,
        "product": product,
        "manufacturer": company or preserved.get("manufacturer") or "",
        "product_tokens": tokens,
        "required_tokens": list(tokens),
        "aliases": list(dict.fromkeys([*(_list(preserved.get("aliases"))), product])),
        "search_terms": list(dict.fromkeys([*(_list(preserved.get("search_terms"))), product])),
    })
    return sanitize_identity_ignore_terms(preserved)


def make_request_id() -> int:
    return int(datetime.utcnow().timestamp() * 1_000_000)


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def _list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def learned_entity_to_result(row: dict, query: str) -> dict:
    canonical_name = row.get("canonical_name") or query
    aliases = _list(row.get("aliases"))
    search_terms = list(dict.fromkeys([canonical_name, *aliases]))
    entity_type = row.get("entity_type") or "entity"
    industry = row.get("industry") or "unknown"
    return {
        "entity_name": canonical_name,
        "industry": industry,
        "description": f"{canonical_name} is a learned {entity_type} in the {industry} industry.",
        "aliases": aliases,
        "search_terms": search_terms,
        "positive_terms": [],
        "ignore_terms": [],
        "negative_terms": [],
        "source": row.get("source") or "learned_entities",
        "confidence": float(row.get("confidence") or 0.9),
        "verified": bool(row.get("verified")),
        "entity_type": entity_type,
        "primary_category": row.get("primary_category") or "",
        "subcategory": row.get("subcategory") or "",
        "competitor_category": row.get("competitor_category") or "",
        "manufacturer": row.get("manufacturer") or "",
        "categories": _list(row.get("categories")),
    }


def lookup_learned_entity(normalized_query: str, query: str, request_id: int | None = None) -> dict | None:
    if not normalized_query:
        return None
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'learned_entities'
            """
        )
        learned_columns = {column for (column,) in cur.fetchall()}
        optional_columns = [
            column
            for column in [
                "primary_category",
                "subcategory",
                "competitor_category",
                "manufacturer",
                "categories",
            ]
            if column in learned_columns
        ]
        select_columns = [
            "user_input",
            "canonical_name",
            "entity_type",
            "industry",
            "aliases",
            "confidence",
            "source",
            "verified",
            *optional_columns,
        ]
        cur.execute(
            f"""
            SELECT {", ".join(select_columns)}
            FROM learned_entities
            WHERE normalized_input = %s
            ORDER BY verified DESC, confidence DESC NULLS LAST, updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (normalized_query,),
        )
        row = cur.fetchone()
        if not row:
            if request_id is not None:
                log_db_operation(request_id, "lookup_miss", "learned_entities", {"normalized_input": normalized_query})
            return None
        cur.execute(
            """
            UPDATE learned_entities
            SET usage_count = COALESCE(usage_count, 0) + 1,
                updated_at = NOW()
            WHERE normalized_input = %s
            """,
            (normalized_query,),
        )
        conn.commit()
        if request_id is not None:
            log_db_operation(
                request_id,
                "lookup_hit",
                "learned_entities",
                {"normalized_input": normalized_query, "canonical_name": row[1], "source": row[6]},
            )
        return learned_entity_to_result(dict(zip(select_columns, row)), query)
    except Exception as exc:
        print(f"[ENTITY_RESOLVER] DB lookup skipped: {exc}")
        if request_id is not None:
            log_db_operation(
                request_id,
                "lookup_error",
                "learned_entities",
                {"normalized_input": normalized_query, "error": str(exc)},
            )
        if conn:
            conn.rollback()
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def upsert_learned_entity(query: str, result: dict, request_id: int | None = None) -> None:
    normalized_query = normalize_input(query)
    if not normalized_query or not is_valid_entity_result(result, query):
        return

    canonical_name = result.get("entity_name") or query
    entity_type = result.get("entity_type") or "brand"
    industry = result.get("industry") or "unknown"
    primary_category = result.get("primary_category") or result.get("category") or ""
    subcategory = result.get("subcategory") or result.get("segment") or ""
    competitor_category = result.get("competitor_category") or result.get("comparison_category") or ""
    manufacturer = result.get("manufacturer") or ""
    categories = _list(result.get("categories"))
    aliases = list(dict.fromkeys([
        *_list(result.get("aliases")),
        *_list(result.get("search_terms")),
    ]))
    aliases = [alias for alias in aliases if normalize_input(alias) != normalize_input(canonical_name)]
    confidence = float(result.get("confidence") or 0.0)
    source = result.get("source") or "resolver"
    verified = confidence >= 0.8 and source != "fallback"

    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'learned_entities'
            """
        )
        learned_columns = {column for (column,) in cur.fetchall()}
        optional_updates = []
        optional_values = []
        optional_insert_columns = []
        optional_insert_values = []
        for column, value in [
            ("primary_category", primary_category),
            ("subcategory", subcategory),
            ("competitor_category", competitor_category),
            ("manufacturer", manufacturer),
            ("categories", categories),
        ]:
            if column in learned_columns:
                optional_updates.append(f"{column} = %s")
                optional_values.append(value)
                optional_insert_columns.append(column)
                optional_insert_values.append(value)

        cur.execute(
            f"""
            UPDATE learned_entities
            SET user_input = %s,
                canonical_name = %s,
                entity_type = %s,
                industry = %s,
                aliases = %s,
                confidence = %s,
                source = %s,
                verified = %s,
                {", ".join(optional_updates) + "," if optional_updates else ""}
                usage_count = COALESCE(usage_count, 0) + 1,
                updated_at = NOW()
            WHERE normalized_input = %s
            """,
            (
                query,
                canonical_name,
                entity_type,
                industry,
                aliases,
                confidence,
                source,
                verified,
                *optional_values,
                normalized_query,
            ),
        )
        if cur.rowcount == 0:
            operation = "insert"
            cur.execute(
                f"""
                INSERT INTO learned_entities (
                    id, user_input, canonical_name, entity_type, industry,
                    aliases, confidence, source, verified, usage_count,
                    {", ".join(optional_insert_columns) + "," if optional_insert_columns else ""}
                    normalized_input, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 1,
                    {", ".join(["%s"] * len(optional_insert_values)) + "," if optional_insert_values else ""}
                    %s, NOW(), NOW()
                )
                """,
                (
                    str(uuid.uuid4()),
                    query,
                    canonical_name,
                    entity_type,
                    industry,
                    aliases,
                    confidence,
                    source,
                    verified,
                    *optional_insert_values,
                    normalized_query,
                ),
            )
        else:
            operation = "update"
        conn.commit()
        print(f"[ENTITY_RESOLVER] UPSERT -> {canonical_name}")
        if request_id is not None:
            log_db_operation(
                request_id,
                operation,
                "learned_entities",
                {
                    "normalized_input": normalized_query,
                    "canonical_name": canonical_name,
                    "industry": industry,
                    "confidence": confidence,
                    "source": source,
                    "verified": verified,
                    "primary_category": primary_category,
                    "subcategory": subcategory,
                    "competitor_category": competitor_category,
                    "manufacturer": manufacturer,
                    "categories": categories,
                },
            )
    except Exception as exc:
        print(f"[ENTITY_RESOLVER] DB upsert skipped: {exc}")
        if request_id is not None:
            log_db_operation(
                request_id,
                "upsert_error",
                "learned_entities",
                {"normalized_input": normalized_query, "error": str(exc)},
            )
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def normalize_entity_result(result: dict, query: str, source: str) -> dict:
    normalized = {
        "entity_name": result.get("entity_name") or result.get("entity") or query,
        "entity_type": result.get("entity_type") or "brand",
        "industry": result.get("industry") or "unknown",
        "primary_category": result.get("primary_category") or result.get("category") or "",
        "subcategory": result.get("subcategory") or result.get("segment") or "",
        "competitor_category": result.get("competitor_category") or result.get("comparison_category") or "",
        "manufacturer": result.get("manufacturer") or "",
        "categories": _list(result.get("categories")),
        "description": result.get("description") or "",
        "aliases": _list(result.get("aliases")),
        "search_terms": _list(result.get("search_terms")) or [result.get("entity_name") or query],
        "positive_terms": _list(result.get("positive_terms")) or _list(result.get("context_terms")),
        "ignore_terms": _list(result.get("ignore_terms")) or _list(result.get("exclude_terms")),
        "negative_terms": _list(result.get("negative_terms")),
        "source": result.get("source") or source,
        "confidence": float(result.get("confidence") or 0.8),
        "verified": bool(result.get("verified")),
        "company": result.get("company") or "",
        "product": result.get("product") or "",
        "product_tokens": _list(result.get("product_tokens")),
        "required_tokens": _list(result.get("required_tokens")),
    }
    return preserve_product_identity(query, normalized)


def is_valid_entity_result(result: dict | None, query: str) -> bool:
    if not result or not isinstance(result, dict):
        return False

    entity_name = (result.get("entity_name") or "").strip()
    if not entity_name:
        return False

    lowered_entity = entity_name.lower()
    lowered_query = query.strip().lower()
    description = (result.get("description") or "").lower()
    industry = (result.get("industry") or "").lower()
    search_terms = _list(result.get("search_terms"))
    ignore_terms = _list(result.get("ignore_terms")) + _list(result.get("negative_terms"))
    confidence = float(result.get("confidence") or 0.0)
    source = (result.get("source") or "").lower()
    verified = bool(result.get("verified"))

    if confidence < 0.65:
        return False

    if source in {"learned_entities", "db", "db_hit"} and verified:
        return True

    if lowered_entity == lowered_query and lowered_query in FORBIDDEN_GENERIC_ENTITY_NAMES:
        has_disambiguating_context = bool(search_terms and any(term.lower() != lowered_query for term in search_terms))
        has_industry = industry not in {"", "unknown", "general"}
        if not has_disambiguating_context and not has_industry:
            return False

    if any(term in description or term in industry for term in FORBIDDEN_CONTEXT_TERMS):
        has_company_signal = any(
            signal in description or signal in industry
            for signal in ["company", "brand", "corporation", "manufacturer", "technology", "automotive", "finance", "fashion"]
        )
        if not has_company_signal:
            return False

    if not search_terms:
        return False

    if lowered_query in FORBIDDEN_GENERIC_ENTITY_NAMES and not ignore_terms:
        return False

    return True


def cache_validated(query: str, result: dict, request_id: int | None = None) -> dict:
    result = preserve_product_identity(query, result)
    normalized_query = normalize_input(query)
    print("[ENTITY_RESOLVER] CACHE SAVE")
    set_cached_entity(normalized_query, result)
    upsert_learned_entity(query, result, request_id=request_id)
    return result


def needs_enrichment(result: dict, query: str) -> bool:
    lowered_query = query.strip().lower()
    if lowered_query in FORBIDDEN_GENERIC_ENTITY_NAMES:
        return True
    if (result.get("industry") or "").lower() in {"", "unknown", "general"}:
        return True
    if len(_list(result.get("search_terms"))) <= 1:
        return True
    if not (_list(result.get("ignore_terms")) or _list(result.get("negative_terms"))):
        return lowered_query in FORBIDDEN_GENERIC_ENTITY_NAMES
    return False


def is_weak_cached_profile(result: dict | None) -> bool:
    if not result:
        return False
    industry = (result.get("industry") or "").lower()
    positive_terms = _list(result.get("positive_terms")) or _list(result.get("context_terms"))
    return industry in {"", "unknown", "general"} and not positive_terms


def merge_entity_results(primary: dict, enrichment: dict, query: str) -> dict:
    primary = normalize_entity_result(primary, query, primary.get("source") or "primary")
    enrichment = normalize_entity_result(enrichment, query, enrichment.get("source") or "enrichment")
    return {
        **primary,
        "entity_name": enrichment.get("entity_name") or primary["entity_name"],
        "entity_type": enrichment.get("entity_type") or primary["entity_type"],
        "industry": enrichment.get("industry") if enrichment.get("industry") != "unknown" else primary["industry"],
        "primary_category": enrichment.get("primary_category") or primary["primary_category"],
        "subcategory": enrichment.get("subcategory") or primary["subcategory"],
        "competitor_category": enrichment.get("competitor_category") or primary["competitor_category"],
        "manufacturer": enrichment.get("manufacturer") or primary["manufacturer"],
        "categories": list(dict.fromkeys([*primary["categories"], *enrichment["categories"]])),
        "description": enrichment.get("description") or primary["description"],
        "aliases": list(dict.fromkeys([*primary["aliases"], *enrichment["aliases"]])),
        "search_terms": list(dict.fromkeys([*primary["search_terms"], *enrichment["search_terms"]])),
        "positive_terms": list(dict.fromkeys([*primary["positive_terms"], *enrichment["positive_terms"]])),
        "ignore_terms": list(dict.fromkeys([*primary["ignore_terms"], *enrichment["ignore_terms"]])),
        "negative_terms": list(dict.fromkeys([*primary["negative_terms"], *enrichment["negative_terms"]])),
        "source": f"{primary['source']}+{enrichment['source']}",
        "confidence": max(primary["confidence"], enrichment["confidence"]),
    }


def resolve_brand(query: str) -> dict:
    request_id = make_request_id()
    trace = EntityTraceLogger(request_id)
    normalized_query = normalize_input(query)
    print(f"[ENTITY] Resolving: {query}")
    print(f"[ENTITY_RESOLVER] NORMALIZED: {normalized_query}")
    trace.log("normalize", {"input": query, "normalized": normalized_query})
    append_resolver_event(request_id, "resolve_started", {"input": query, "normalized": normalized_query})

    def finish(result: dict, source: str) -> dict:
        result = preserve_product_identity(query, result)
        if source != "fallback":
            set_cached_entity(normalized_query, result)
        trace.log("final", {"source": source, "result": result})
        trace_path = trace.save()
        append_resolver_event(request_id, "resolve_finished", {"source": source, "trace_path": trace_path})
        print(f"[ENTITY_RESOLVER] TRACE SAVED -> {trace_path}")
        return result

    learned_entity = lookup_learned_entity(normalized_query, query, request_id=request_id)
    trace.log("db_lookup", {"normalized": normalized_query, "hit": bool(learned_entity), "entity": learned_entity})
    if learned_entity:
        normalized_db = normalize_entity_result(learned_entity, query, "learned_entities")
        if is_valid_entity_result(normalized_db, query) and not is_weak_cached_profile(normalized_db):
            print(f"[ENTITY_RESOLVER] DB HIT -> {normalized_db.get('entity_name')}")
            set_cached_entity(normalized_query, normalized_db)
            print(f"[ENTITY] FINAL: {normalized_db}")
            return finish(normalized_db, "db")
        if is_weak_cached_profile(normalized_db):
            print("[ENTITY] Weak cached profile -> enriching")
            trace.log("db_lookup_weak_profile", {"entity": normalized_db})
        else:
            print("[ENTITY_RESOLVER] DB HIT ignored invalid entity")
            trace.log("db_lookup_invalid", {"entity": normalized_db})

    cached = get_cached_entity(normalized_query)
    trace.log("cache_lookup", {"normalized": normalized_query, "hit": bool(cached), "entity": cached})
    if cached:
        normalized_cached = normalize_entity_result(cached, query, cached.get("source") or "cache")
        if is_valid_entity_result(normalized_cached, query) and not is_weak_cached_profile(normalized_cached):
            print("[ENTITY_RESOLVER] CACHE HIT")
            print(f"[ENTITY] FINAL: {normalized_cached}")
            return finish(normalized_cached, "cache")
        if is_weak_cached_profile(normalized_cached):
            print("[ENTITY] Weak cached profile -> enriching")
            trace.log("cache_lookup_weak_profile", {"entity": normalized_cached})
        else:
            print("[CACHE] Ignored invalid cached entity")
            trace.log("cache_lookup_invalid", {"entity": normalized_cached})

    print("[ENTITY_RESOLVER] GLiNER USED")
    trace.log("gliner", {"used": True})
    gliner_result = resolve_with_gliner(query)
    trace.log("gliner_result", {"output": gliner_result})
    print(f"[ENTITY] GLiNER USED -> {gliner_result}")
    if gliner_result:
        normalized_gliner = normalize_entity_result(gliner_result, query, "gliner")
        gliner_lookup_key = normalize_input(normalized_gliner.get("entity_name") or "")
        if gliner_lookup_key and gliner_lookup_key != normalized_query:
            learned_from_gliner = lookup_learned_entity(gliner_lookup_key, query, request_id=request_id)
            trace.log(
                "db_lookup_from_gliner",
                {"normalized": gliner_lookup_key, "hit": bool(learned_from_gliner), "entity": learned_from_gliner},
            )
            if learned_from_gliner:
                normalized_db = normalize_entity_result(learned_from_gliner, query, "learned_entities")
                if is_valid_entity_result(normalized_db, query) and not is_weak_cached_profile(normalized_db):
                    print(f"[ENTITY_RESOLVER] DB HIT -> {normalized_db.get('entity_name')}")
                    set_cached_entity(normalized_query, normalized_db)
                    print(f"[ENTITY] FINAL: {normalized_db}")
                    return finish(normalized_db, "db_from_gliner")
                if is_weak_cached_profile(normalized_db):
                    print("[ENTITY] Weak cached profile -> enriching")
                    trace.log("db_from_gliner_weak_profile", {"entity": normalized_db})

        if is_valid_entity_result(normalized_gliner, query):
            if needs_enrichment(normalized_gliner, query):
                print("[ENTITY] GLiNER success but needs context enrichment")
                trace.log("gliner_needs_enrichment", {"entity": normalized_gliner})
            else:
                print(f"[ENTITY] FINAL: {normalized_gliner}")
                return finish(cache_validated(query, normalized_gliner, request_id=request_id), "gliner")
        else:
            print("[ENTITY] GLiNER result did not pass validation")
            trace.log("gliner_invalid", {"entity": normalized_gliner})

    groq_result = None
    try:
        print("[ENTITY] Trying Groq...")
        print("[ENTITY_RESOLVER] GROQ USED")
        trace.log("groq", {"used": True, "reason": "db_cache_miss_or_enrichment"})
        print("[ENTITY] GROQ CALLED -> resolving ambiguity")
        groq_result = groq_resolve(query)
        log_api_call(request_id, "groq", {"query": query}, groq_result or {})
        trace.log("groq_result", {"response": groq_result})
        normalized_groq = normalize_entity_result(groq_result, query, "groq")
        print("[GROQ] JSON valid")
        if gliner_result and is_valid_entity_result(normalized_gliner, query):
            merged = merge_entity_results(normalized_gliner, normalized_groq, query)
            trace.log("groq_merge", {"gliner": normalized_gliner, "groq": normalized_groq, "merged": merged})
            if is_valid_entity_result(merged, query):
                print("[GROQ] Enrichment success")
                print(f"[ENTITY] FINAL: {merged}")
                return finish(cache_validated(query, merged, request_id=request_id), "groq_enrichment")

        if is_valid_entity_result(normalized_groq, query):
            print("[GROQ] Success")
            print(f"[ENTITY] FINAL: {normalized_groq}")
            return finish(cache_validated(query, normalized_groq, request_id=request_id), "groq")
        print("[GROQ] Result failed validation")
        trace.log("groq_invalid", {"entity": normalized_groq})
    except Exception as exc:
        print(f"[ENTITY] Groq failed: {exc}")
        log_api_call(request_id, "groq", {"query": query}, {"error": str(exc)})
        trace.log("groq_error", {"error": str(exc)})

    if gliner_result and is_valid_entity_result(normalized_gliner, query):
        print(f"[ENTITY] FINAL: {normalized_gliner}")
        return finish(cache_validated(query, normalized_gliner, request_id=request_id), "gliner_fallback")

    try:
        print("[ENTITY] Falling back to Wikipedia")
        trace.log("wikipedia", {"used": True})
        wiki_result = wikipedia_resolve(query)
        log_api_call(request_id, "wikipedia", {"query": query}, wiki_result or {})
        trace.log("wikipedia_result", {"response": wiki_result})
        normalized_wiki = normalize_entity_result(wiki_result or {}, query, "wikipedia")
        if is_valid_entity_result(normalized_wiki, query):
            print(f"[ENTITY] FINAL: {normalized_wiki}")
            return finish(cache_validated(query, normalized_wiki, request_id=request_id), "wikipedia")
        print("[ENTITY] Wikipedia result failed validation")
        trace.log("wikipedia_invalid", {"entity": normalized_wiki})
    except Exception as exc:
        print(f"[ENTITY] Wikipedia failed: {exc}")
        log_api_call(request_id, "wikipedia", {"query": query}, {"error": str(exc)})
        trace.log("wikipedia_error", {"error": str(exc)})

    fallback = {
        "entity_name": query,
        "industry": "unknown",
        "description": "",
        "aliases": [],
        "search_terms": [query],
        "positive_terms": ["company", "brand", "product", "service"],
        "ignore_terms": [],
        "negative_terms": [],
        "source": "fallback",
        "confidence": 0.0,
    }
    print(f"[ENTITY] FINAL fallback, not cached: {fallback}")
    trace.log("upsert", {"status": "skipped", "reason": "fallback_not_cached"})
    return finish(fallback, "fallback")
