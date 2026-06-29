"""
Brand Monitoring Service.

The scheduler uses run_monitoring_cycle() for due brands only.
The UI/API uses run_single_brand_monitor() so a new search never reruns every
active brand and burns source quotas.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
import requests
from dotenv import load_dotenv

from app.services.entity_resolution.brand_matcher import (
    BrandProfile,
    load_brand_profile,
    match_brand_profile,
    unique_terms,
)
from app.services.entity_resolution.embedding_matcher import score_semantic_similarity
from app.services.entity_resolution.entity_detector import has_company_entity
from app.services.sentiment_service import enrich_item_sentiment
from app.services.source_quota_service import can_use_source, increment_source_usage
from app.services.observability.monitoring_logger import (
    log_dedupe_run,
    log_filter_run,
    log_source_run,
    log_storage_run,
    load_source_run,
    print_monitor_summary,
)
from app.services.competitor_intelligence.scheduler_pause import (
    pause_status as competitor_pause_status,
    should_cancel_monitoring as should_cancel_for_competitor,
)
from app.services.reputation_signals.scheduler_pause import (
    pause_status as reputation_pause_status,
    should_cancel_monitoring as should_cancel_for_reputation,
)
from app.services.monitor_priority_gate import monitor_checkpoint
from app.utils.time_utils import now_ist

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "15"))
_MENTION_MATCH_COLUMNS_READY = False
_MONITOR_RUNTIME_COLUMNS_READY = False
_SCHEDULED_CHECKPOINT: dict | None = None

MIN_SOURCE_RESULTS = {
    "newsapi": 10,
    "google_news": 10,
    "reddit": 10,
    "youtube": 5,
}

FALLBACK_SOURCE_THRESHOLDS = {
    "newsapi": 0.35,
    "google_news": 0.35,
    "reddit": 0.35,
    "youtube": 0.35,
}

MIN_FALLBACK_SCORE = 0.30
MIN_FALLBACK_ENTITY_SCORE = 0.40

SOURCE_WEIGHTS = {
    "newsapi": 0.9,
    "google_news": 0.95,
    "reddit": 0.6,
    "youtube": 0.5,
}

MAX_NEWSAPI_QUERY_LENGTH = 450

TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "gbraid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ocid",
    "ref",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
    "utm_id",
}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def make_monitor_request_id() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def normalize_url(url: str | None) -> str:
    if not url:
        return ""

    try:
        parts = urlsplit(url.strip())
        netloc = parts.netloc.lower()
        query_params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_PARAMS
        ]
        return urlunsplit(
            (
                parts.scheme.lower() or "https",
                netloc,
                parts.path,
                urlencode(query_params, doseq=True),
                "",
            )
        )
    except Exception:
        return url.strip()


def ensure_monitor_runtime_columns(cur):
    global _MONITOR_RUNTIME_COLUMNS_READY
    if _MONITOR_RUNTIME_COLUMNS_READY:
        return

    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS last_status TEXT")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS last_error TEXT")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ")
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.brand_mentions') IS NOT NULL
               AND to_regclass('public.monitored_brands') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_brand_mentions_brand'
            ) THEN
                ALTER TABLE brand_mentions
                ADD CONSTRAINT fk_brand_mentions_brand
                FOREIGN KEY (brand_id)
                REFERENCES monitored_brands(id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.monitor_runs') IS NOT NULL
               AND to_regclass('public.monitored_brands') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_monitor_runs_brand'
            ) THEN
                ALTER TABLE monitor_runs
                ADD CONSTRAINT fk_monitor_runs_brand
                FOREIGN KEY (brand_id)
                REFERENCES monitored_brands(id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.sentiment_results') IS NOT NULL
               AND to_regclass('public.articles') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_sentiment_article'
            ) THEN
                ALTER TABLE sentiment_results
                ADD CONSTRAINT fk_sentiment_article
                FOREIGN KEY (article_id)
                REFERENCES articles(article_id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    _MONITOR_RUNTIME_COLUMNS_READY = True


def get_table_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def start_monitor_run(brand_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        columns = get_table_columns(cur, "monitor_runs")
        if not columns:
            return None

        insert_values = {}
        if "brand_id" in columns:
            insert_values["brand_id"] = brand_id
        if "status" in columns:
            insert_values["status"] = "running"
        if "started_at" in columns:
            insert_values["started_at"] = datetime.now(timezone.utc)

        if not insert_values:
            return None

        names = list(insert_values.keys())
        placeholders = ", ".join(["%s"] * len(names))
        returning = " RETURNING id" if "id" in columns else ""
        cur.execute(
            f"INSERT INTO monitor_runs ({', '.join(names)}) VALUES ({placeholders}){returning}",
            tuple(insert_values[name] for name in names),
        )
        row = cur.fetchone() if "id" in columns else None
        conn.commit()
        return str(row[0]) if row else None
    except Exception as exc:
        conn.rollback()
        print(f"[MONITOR_RUNS] Could not create run log: {exc}")
        return None
    finally:
        cur.close()
        conn.close()


def finish_monitor_run(run_id: str | None, status: str, mentions_found: int = 0, error_message: str | None = None):
    if not run_id:
        return

    conn = get_conn()
    cur = conn.cursor()
    try:
        columns = get_table_columns(cur, "monitor_runs")
        updates = {}
        if "status" in columns:
            updates["status"] = status
        if "mentions_found" in columns:
            updates["mentions_found"] = mentions_found
        if "error_message" in columns:
            updates["error_message"] = error_message
        if "completed_at" in columns:
            updates["completed_at"] = datetime.now(timezone.utc)

        if not updates or "id" not in columns:
            return

        set_sql = ", ".join([f"{name} = %s" for name in updates])
        cur.execute(
            f"UPDATE monitor_runs SET {set_sql} WHERE id = %s",
            (*updates.values(), run_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[MONITOR_RUNS] Could not update run log: {exc}")
    finally:
        cur.close()
        conn.close()


def _fetch_brand_profiles(where_sql: str, params: tuple = ()) -> list[BrandProfile]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id
        FROM monitored_brands
        WHERE {where_sql}
        ORDER BY COALESCE(last_run_at, created_at) ASC
        """,
        params,
    )
    brand_ids = [str(row[0]) for row in cur.fetchall()]
    cur.close()

    profiles = [load_brand_profile(conn, brand_id=brand_id) for brand_id in brand_ids]
    conn.close()
    return profiles


def get_active_brand_profiles() -> list[BrandProfile]:
    """Fetch every active monitor. Intended for manual/admin use only."""
    return _fetch_brand_profiles("is_active = TRUE")


def get_due_brand_profiles() -> list[BrandProfile]:
    """Fetch active monitors whose interval has elapsed."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    return _fetch_brand_profiles(
        "is_active = TRUE AND (last_run_at IS NULL OR last_run_at <= %s)",
        (cutoff,),
    )


def get_brand_profile(brand_id: str) -> BrandProfile:
    conn = get_conn()
    try:
        return load_brand_profile(conn, brand_id=brand_id)
    finally:
        conn.close()


def get_brand_profile_by_name(brand_name: str) -> BrandProfile:
    conn = get_conn()
    try:
        return load_brand_profile(conn, brand_name=brand_name)
    finally:
        conn.close()


def url_already_collected(url: str) -> bool:
    normalized_url = normalize_url(url)
    if not normalized_url:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM brand_mentions WHERE url = %s LIMIT 1", (normalized_url,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def save_mention(brand_id: str, source: str, item: dict):
    """Save a single mention to brand_mentions table."""
    global _MENTION_MATCH_COLUMNS_READY
    url = normalize_url(item.get("url", ""))
    if url and url_already_collected(url):
        return False

    conn = get_conn()
    cur = conn.cursor()
    if not _MENTION_MATCH_COLUMNS_READY:
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_reason TEXT")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS matched_terms TEXT[]")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS sentiment_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS emotion_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS relevance_score DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS semantic_score DOUBLE PRECISION")
        conn.commit()
        _MENTION_MATCH_COLUMNS_READY = True

    item = enrich_item_sentiment(item)
    cur.execute(
        """
        INSERT INTO brand_mentions (
            brand_id, source, title, url, body_text,
            author, published_at, sentiment_label, sentiment_score,
            primary_category, emotion, match_confidence, match_reason, matched_terms,
            sentiment_confidence, emotion_confidence, relevance_score, semantic_score
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (url) DO NOTHING
        """,
        (
            brand_id,
            source,
            item.get("title"),
            url,
            item.get("body_text") or item.get("text", ""),
            item.get("author"),
            item.get("published_at"),
            item.get("sentiment_label"),
            item.get("sentiment_score"),
            item.get("primary_category"),
            item.get("emotion"),
            item.get("match_confidence"),
            item.get("match_reason"),
            item.get("matched_terms") or [],
            item.get("sentiment_confidence"),
            item.get("emotion_confidence"),
            item.get("relevance_score"),
            item.get("semantic_score"),
        ),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return inserted


def update_monitor_success(brand_id: str):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    next_run_at = now + timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    ensure_monitor_runtime_columns(cur)
    cur.execute(
        """
        UPDATE monitored_brands
        SET last_run_at = %s,
            next_run_at = %s,
            last_status = 'success',
            last_error = NULL
        WHERE id = %s
        """,
        (now, next_run_at, brand_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_monitor_failure(brand_id: str, error_message: str):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    next_run_at = now + timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    ensure_monitor_runtime_columns(cur)
    cur.execute(
        """
        UPDATE monitored_brands
        SET last_run_at = %s,
            next_run_at = %s,
            last_status = 'failed',
            last_error = %s
        WHERE id = %s
        """,
        (now, next_run_at, error_message[:2000], brand_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def profile_search_terms(profile: BrandProfile) -> list[str]:
    return unique_terms([profile.brand_name, *profile.aliases])


def is_english_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False

    ascii_chars = sum(1 for char in cleaned if char.isascii())
    letters_or_space = sum(1 for char in cleaned if char.isascii() and (char.isalpha() or char.isspace()))
    if len(cleaned) < 80:
        return ascii_chars / max(len(cleaned), 1) > 0.85 and letters_or_space > 8

    try:
        from langdetect import detect

        return detect(cleaned[:1000]) == "en"
    except Exception:
        return ascii_chars / max(len(cleaned), 1) > 0.85 and letters_or_space > 8


def has_negative_ambiguous_context(profile: BrandProfile, text: str) -> bool:
    negative_terms = profile.exclusions
    if not negative_terms:
        return False
    lowered = text.lower()
    return any(term in lowered for term in negative_terms)


def source_quality_score(source: str, item: dict, profile: BrandProfile) -> float:
    source_name = (item.get("author") or item.get("channel_name") or item.get("source_name") or "").lower()
    if any(channel.channel_name.lower() == source_name for channel in profile.official_channels):
        return 0.4

    trusted_publishers = ["reuters", "associated press", "ap news", "bloomberg", "cnbc", "the verge", "techcrunch", "bbc", "cnn"]
    if source in {"newsapi", "google_news"} and any(name in source_name for name in trusted_publishers):
        return 0.25

    spam_terms = ["meme", "lyrics", "topic", "fan", "unofficial"]
    if any(term in source_name for term in spam_terms):
        return -0.2

    return 0.0


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, float(value or 0.0)))


def entity_match_score(profile: BrandProfile, text: str) -> float:
    lowered = (text or "").lower()
    brand = (profile.brand_name or "").lower()
    aliases = [alias.lower() for alias in (profile.aliases or []) if alias]

    if brand and brand in lowered:
        return 1.0
    if any(alias in lowered for alias in aliases):
        return 0.8
    return 0.2


def final_relevance_score(rel: float, sem: float, entity: float, source: str, quality_bonus: float = 0.0) -> float:
    source_quality = clamp_score(SOURCE_WEIGHTS.get(source, 0.5) + quality_bonus)
    return clamp_score(
        0.35 * clamp_score(rel)
        + 0.35 * clamp_score(sem)
        + 0.20 * clamp_score(entity)
        + 0.10 * source_quality
    )


def normalize_cluster_title(title: str) -> str:
    normalized = (title or "").lower()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"\|.*$", " ", normalized)
    normalized = re.sub(r"\s+-\s+[^-]{2,80}$", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    stopwords = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
        "from", "with", "by", "at", "as", "is", "are", "was", "were",
    }
    tokens = [token for token in normalized.split() if token not in stopwords]
    return " ".join(tokens)


def dedupe_news_clusters(items: list[dict], source: str, request_id: int | None = None) -> list[dict]:
    if source not in {"newsapi", "google_news"} or len(items) <= 1:
        return items

    clusters: list[dict] = []
    for item in items:
        title_key = normalize_cluster_title(item.get("title") or "")
        url = normalize_url(item.get("url") or "")
        domain = urlsplit(url).netloc if url else ""
        matched_cluster = None

        for cluster in clusters:
            similarity = SequenceMatcher(None, title_key, cluster["title_key"]).ratio()
            same_domain = domain and domain == cluster["domain"]
            if title_key and (similarity >= 0.86 or (same_domain and similarity >= 0.72)):
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append({
                "title_key": title_key,
                "domain": domain,
                "items": [item],
            })
        else:
            matched_cluster["items"].append(item)

    representatives = []
    for cluster in clusters:
        ranked = sorted(
            cluster["items"],
            key=lambda candidate: (
                candidate.get("relevance_score", 0),
                candidate.get("semantic_score", 0),
                bool(candidate.get("url")),
            ),
            reverse=True,
        )
        representative = ranked[0]
        representative["duplicate_cluster_size"] = len(cluster["items"])
        representatives.append(representative)

    dropped = len(items) - len(representatives)
    if dropped:
        print(f"[FILTER] {source}: clustered {len(items)} articles into {len(representatives)} unique news stories")
        if request_id:
            log_dedupe_run(request_id, source, {
                "before": len(items),
                "after": len(representatives),
                "duplicates_removed": dropped,
                "clusters": [
                    {
                        "representative": cluster["items"][0].get("title"),
                        "size": len(cluster["items"]),
                    }
                    for cluster in clusters
                ],
            })
    return representatives


def title_body_relevance_bonus(profile: BrandProfile, title: str, body: str) -> float:
    terms = [profile.brand_name, *profile.aliases]
    title_lower = title.lower()
    body_lower = body.lower()
    bonus = 0.0
    if any(term.lower() in title_lower for term in terms if term):
        bonus += 0.12
    if any(term.lower() in body_lower for term in terms if term):
        bonus += 0.06
    if profile.context_keywords and any(term.lower() in title_lower for term in profile.context_keywords):
        bonus += 0.1
    return bonus


def build_newsapi_query(profile: BrandProfile) -> str:
    def quote(term: str) -> str:
        return f'"{term}"'

    def compose_query(
        include: list[str],
        context: list[str] | None = None,
        exclusions: list[str] | None = None,
    ) -> str:
        include_query = " OR ".join(quote(term) for term in include if term)
        query = include_query
        if context:
            context_query = " OR ".join(quote(term) for term in context if term)
            if context_query:
                query = f"({query}) AND ({context_query})"
        if exclusions:
            exclusion_query = " ".join(f'NOT "{phrase}"' for phrase in exclusions if phrase)
            if exclusion_query:
                query = f"({query}) {exclusion_query}"
        return query

    terms = profile_search_terms(profile)
    context_terms = list(profile.context_keywords or [])
    exclusion_terms = list(profile.exclusions or [])
    query = compose_query(terms, context_terms, exclusion_terms)

    if len(query) <= MAX_NEWSAPI_QUERY_LENGTH:
        return query

    # NewsAPI rejects long boolean queries. Keep the compact fallback broad
    # enough for multi-word products/models too, e.g. "Skoda Kushaq" plus
    # aliases such as "Skoda" or "Skoda Auto India".
    primary_terms = unique_terms([profile.brand_name, *profile.aliases])[:4]

    compact_context = unique_terms(context_terms)[:4]
    compact_exclusions = unique_terms(exclusion_terms)[:5]
    variants = [
        compose_query(primary_terms, compact_context, compact_exclusions),
        compose_query(primary_terms, compact_context, []),
        compose_query(primary_terms, [], compact_exclusions),
        compose_query(primary_terms, [], []),
        compose_query([profile.brand_name], [], []),
    ]

    for candidate in variants:
        if candidate and len(candidate) <= MAX_NEWSAPI_QUERY_LENGTH:
            print(
                f"[MONITOR][NewsAPI] Query shortened from {len(query)} "
                f"to {len(candidate)} chars"
            )
            return candidate

    fallback = quote((profile.brand_name or terms[0] or "").strip())
    print(f"[MONITOR][NewsAPI] Query shortened from {len(query)} to {len(fallback)} chars")
    return fallback


def get_with_retries(url: str, *, params: dict | None = None, timeout: int = 15, attempts: int = 3):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            res = requests.get(url, params=params, timeout=timeout)
            if res.ok:
                return res
            print(f"[HTTP] GET {url} attempt {attempt}/{attempts} -> {res.status_code}: {res.text[:180]}")
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[HTTP] GET {url} attempt {attempt}/{attempts} failed: {exc}")
        if attempt < attempts:
            time.sleep(1.5 * attempt)
    if last_exc:
        raise last_exc
    return None


def score_item_metadata(profile: BrandProfile, source: str, item: dict) -> tuple[dict, dict, dict]:
    title = item.get("title") or ""
    text = item.get("body_text") or item.get("text") or ""
    channel_name = item.get("author") or item.get("channel_name") or ""

    match = match_brand_profile(
        profile,
        source=source,
        title=title,
        text=text,
        channel_name=channel_name,
    )

    rule_confidence = float(match.get("confidence") or 0.0)
    semantic_result = score_semantic_similarity(
        brand_name=profile.brand_name,
        title=title,
        text=text,
        aliases=profile.aliases,
        brand_context=profile.brand_context,
        threshold=0.35,
    )

    semantic_score = float(semantic_result.get("semantic_score") or 0.0)
    quality_score = source_quality_score(source, item, profile)
    combined_text = " ".join([title, text, channel_name])
    entity_score = entity_match_score(profile, combined_text)
    rel_score = rule_confidence + title_body_relevance_bonus(profile, title, text)
    if has_negative_ambiguous_context(profile, " ".join([title, text, channel_name])):
        rel_score -= 0.2
    relevance_score = final_relevance_score(
        rel=rel_score,
        sem=semantic_score,
        entity=entity_score,
        source=source,
        quality_bonus=quality_score,
    )
    item["match_confidence"] = rule_confidence
    item["match_reason"] = match["reason"]
    item["matched_terms"] = match["matched_terms"]
    item["semantic_score"] = semantic_score
    item["entity_score"] = entity_score
    item["relevance_score"] = round(relevance_score, 4)
    item["source_quality_score"] = quality_score
    return item, match, semantic_result


def filter_items(profile: BrandProfile, source: str, items: list[dict], request_id: int | None = None) -> list[dict]:
    filtered = []
    fallback_candidates = []
    discarded_titles = []
    discard_reasons = {
        "non_english": 0,
        "low_final_score": 0,
        "weak_entity_match": 0,
    }
    minimum = MIN_SOURCE_RESULTS.get(source, 0)
    fallback_threshold = FALLBACK_SOURCE_THRESHOLDS.get(source, 0.25)

    for item in items:
        combined_text = " ".join(
            value
            for value in [
                item.get("title") or "",
                item.get("body_text") or item.get("text") or "",
                item.get("author") or item.get("channel_name") or "",
            ]
            if value
        )
        if combined_text and not is_english_text(combined_text):
            print(f"[FILTER] Dropped non-English ({source}): {(item.get('title') or '')[:60]}")
            discard_reasons["non_english"] += 1
            if len(discarded_titles) < 25:
                discarded_titles.append({"title": item.get("title"), "reason": "non_english"})
            continue

        scored_item, rule_result, semantic_result = score_item_metadata(profile, source, item)
        is_relevant = scored_item.get("relevance_score", 0) >= fallback_threshold
        title = scored_item.get("title") or ""

        if is_relevant:
            if (
                profile.context_keywords
                and scored_item.get("relevance_score", 0) < 0.85
                and has_company_entity(combined_text, profile.brand_name, profile.aliases)
            ):
                scored_item["relevance_score"] = max(scored_item.get("relevance_score", 0), 0.85)
                scored_item["match_reason"] = f"{scored_item.get('match_reason', '')} + gliner_company_entity"
            filtered.append(scored_item)
            continue

        final_score = scored_item.get("relevance_score", 0)
        entity_score = scored_item.get("entity_score", 0)
        if final_score >= MIN_FALLBACK_SCORE and entity_score >= MIN_FALLBACK_ENTITY_SCORE:
            fallback_candidates.append(scored_item)
        elif entity_score < MIN_FALLBACK_ENTITY_SCORE:
            discard_reasons["weak_entity_match"] += 1
        discard_reasons["low_final_score"] += 1
        if len(discarded_titles) < 25:
            discarded_titles.append({
                "title": title,
                "reason": "weak_entity_match" if entity_score < MIN_FALLBACK_ENTITY_SCORE else "low_final_score",
                "final_score": final_score,
                "semantic_score": scored_item.get("semantic_score", 0),
                "entity_score": entity_score,
                "rule_score": scored_item.get("match_confidence", 0),
            })

        print(
            f"[FILTER] Ranked low ({source}): final={scored_item.get('relevance_score', 0):.2f} "
            f"rule={scored_item.get('match_confidence', 0):.2f} sem={scored_item.get('semantic_score', 0):.2f} "
            f"entity={scored_item.get('entity_score', 0):.2f} | {title[:60]}"
        )

    if len(filtered) < minimum and fallback_candidates:
        needed = minimum - len(filtered)
        fallback_candidates = sorted(
            fallback_candidates,
            key=lambda item: item.get("relevance_score", 0),
            reverse=True,
        )
        filtered.extend(fallback_candidates[:needed])
        print(f"[FILTER] {source}: added {min(needed, len(fallback_candidates))} ranked fallback items")

    if not filtered and fallback_candidates:
        rescue_count = min(max(minimum, 5), len(fallback_candidates))
        filtered = sorted(
            fallback_candidates,
            key=lambda item: item.get("relevance_score", 0),
            reverse=True,
        )[:rescue_count]
        print(f"[FILTER] {source}: rescue fallback returned {len(filtered)} ranked items")

    filtered = sorted(filtered, key=lambda item: item.get("relevance_score", 0), reverse=True)
    filtered = dedupe_news_clusters(filtered, source, request_id=request_id)
    if request_id:
        log_filter_run(request_id, source, {
            "brand": profile.brand_name,
            "raw_found": len(items),
            "after_filter": len(filtered),
            "discarded": max(0, len(items) - len(filtered)),
            "discard_reasons": {key: value for key, value in discard_reasons.items() if value},
            "kept_titles": [item.get("title") for item in filtered[:30]],
            "discarded_titles": discarded_titles,
        })
    print(f"[FILTER] {source}: {len(filtered)}/{len(items)} kept")
    return filtered


def collect_newsapi(profile: BrandProfile, request_id: int | None = None) -> list[dict]:
    if not NEWS_API_KEY:
        print("[MONITOR][NewsAPI] NEWS_API_KEY missing; skipping NewsAPI.")
        if request_id:
            log_source_run(request_id, "newsapi", {
                "brand": profile.brand_name,
                "query": build_newsapi_query(profile),
                "status_code": None,
                "total_results": 0,
                "returned_articles": 0,
                "reason": "NEWS_API_KEY missing",
            })
        return []

    params = {
        "q": build_newsapi_query(profile),
        "apiKey": NEWS_API_KEY,
        "pageSize": 30,
        "language": "en",
        "sortBy": "publishedAt",
    }

    try:
        res = get_with_retries(
            "https://newsapi.org/v2/everything",
            params=params,
            timeout=25,
            attempts=2,
        )
        if not res:
            print(f"[MONITOR][NewsAPI] No response for '{profile.brand_name}' after retries.")
            if request_id:
                log_source_run(request_id, "newsapi", {
                    "brand": profile.brand_name,
                    "query": params["q"],
                    "status_code": None,
                    "total_results": 0,
                    "returned_articles": 0,
                    "reason": "No response after retries",
                })
            return []
        payload = res.json()
        if payload.get("status") == "error":
            print(f"[MONITOR][NewsAPI] API error for '{profile.brand_name}': {payload.get('code')} - {payload.get('message')}")
            if request_id:
                log_source_run(request_id, "newsapi", {
                    "brand": profile.brand_name,
                    "query": params["q"],
                    "url": res.url,
                    "status_code": res.status_code,
                    "total_results": 0,
                    "returned_articles": 0,
                    "reason": payload.get("message"),
                    "api_code": payload.get("code"),
                })
            return []
        articles = payload.get("articles", [])
        print(f"[MONITOR][NewsAPI] {len(articles)} raw articles for '{profile.brand_name}'")
        items = [
            {
                "title": article.get("title"),
                "url": article.get("url"),
                "body_text": article.get("description") or "",
                "author": article.get("source", {}).get("name") or article.get("author"),
                "published_at": article.get("publishedAt"),
            }
            for article in articles
        ]
        filtered = filter_items(profile, "newsapi", items, request_id=request_id)
        if request_id:
            log_source_run(request_id, "newsapi", {
                "brand": profile.brand_name,
                "query": params["q"],
                "url": res.url,
                "status_code": res.status_code,
                "total_results": payload.get("totalResults", len(articles)),
                "returned_articles": len(articles),
                "after_filter": len(filtered),
                "reason": "ok" if articles else "API returned empty result set",
            })
        return filtered
    except Exception as exc:
        print(f"[MONITOR][NewsAPI] Error for '{profile.brand_name}' after retries: {exc}")
        if request_id:
            log_source_run(request_id, "newsapi", {
                "brand": profile.brand_name,
                "query": params["q"],
                "status_code": None,
                "total_results": 0,
                "returned_articles": 0,
                "reason": str(exc),
                "error": str(exc),
            })
        return []


def collect_reddit(profile: BrandProfile, request_id: int | None = None) -> list[dict]:
    try:
        res = requests.post(
            "http://localhost:8000/api/reddit/scrape-store-reddit",
            params={"brand": profile.brand_name},
            timeout=240,
        )
        posts = res.json() if res.ok else []
        items = [
            {
                "title": post.get("content") or post.get("title", ""),
                "url": post.get("url"),
                "body_text": post.get("content", ""),
                "author": post.get("username"),
                "published_at": post.get("date"),
                "sentiment_label": post.get("sentiment_label"),
                "sentiment_score": post.get("sentiment_score"),
            }
            for post in posts
        ]
        filtered = filter_items(profile, "reddit", items, request_id=request_id)
        if request_id:
            log_source_run(request_id, "reddit", {
                "brand": profile.brand_name,
                "urls_found": None,
                "posts_scraped": len(posts),
                "after_filter": len(filtered),
                "discarded": max(0, len(posts) - len(filtered)),
                "errors": [] if res.ok else [res.text[:300]],
            })
        return filtered
    except Exception as exc:
        print(f"[MONITOR][Reddit] Error for '{profile.brand_name}': {exc}")
        if request_id:
            log_source_run(request_id, "reddit", {
                "brand": profile.brand_name,
                "urls_found": None,
                "posts_scraped": 0,
                "after_filter": 0,
                "discarded": 0,
                "errors": [str(exc)],
            })
        return []


def collect_youtube(profile: BrandProfile, request_id: int | None = None) -> list[dict]:
    try:
        official_channels = [
            channel.channel_name
            for channel in profile.official_channels
            if getattr(channel, "channel_name", None)
        ]
        res = requests.post(
            "http://localhost:8000/api/youtube/scrape-store-youtube",
            params={
                "brand": profile.brand_name,
                "entity_name": profile.brand_name,
                "ignore_terms": ",".join(profile.exclusions),
                "official_channels": ",".join(official_channels),
                "request_id": request_id,
            },
            timeout=60,
        )
        videos = res.json() if res.ok else []
        items = [
            {
                "title": video.get("title"),
                "url": video.get("video_url") or video.get("url"),
                "author": video.get("youtuber") or video.get("channelTitle"),
                "channel_name": video.get("youtuber") or video.get("channelTitle"),
                "published_at": video.get("published"),
            }
            for video in videos
        ]
        filtered = filter_items(profile, "youtube", items, request_id=request_id)
        if request_id:
            log_source_run(request_id, "youtube_monitor_filter", {
                "brand": profile.brand_name,
                "videos_returned_by_route": len(videos),
                "after_monitor_filter": len(filtered),
                "errors": [] if res.ok else [res.text[:300]],
            })
        return filtered
    except Exception as exc:
        print(f"[MONITOR][YouTube] Error for '{profile.brand_name}': {exc}")
        if request_id:
            log_source_run(request_id, "youtube", {
                "brand": profile.brand_name,
                "videos_found": 0,
                "videos_after_filter": 0,
                "discard_reasons": {},
                "error": str(exc),
            })
        return []


def collect_google_news(profile: BrandProfile, request_id: int | None = None) -> list[dict]:
    try:
        res = get_with_retries(
            "http://localhost:8000/api/google-news/search",
            params={"brand": profile.brand_name},
            timeout=60,
            attempts=2,
        )
        raw_items = res.json() if res and res.ok else []
        if not raw_items:
            print(f"[MONITOR][GoogleNews] Local route returned 0 items; trying direct scraper fallback for '{profile.brand_name}'.")
            try:
                import asyncio
                from app.api.google_news.google_news_scraper import _google_news_search_async

                raw_items = asyncio.run(_google_news_search_async(profile.brand_name))
            except Exception as direct_exc:
                print(f"[MONITOR][GoogleNews] Direct scraper fallback failed for '{profile.brand_name}': {direct_exc}")
                raw_items = []
        items = [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "body_text": item.get("body_text") or item.get("description") or "",
                "author": item.get("source_name") or item.get("author"),
                "published_at": item.get("published_at"),
            }
            for item in raw_items
        ]
        filtered = filter_items(profile, "google_news", items, request_id=request_id)
        if request_id:
            log_source_run(request_id, "google_news", {
                "brand": profile.brand_name,
                "raw_found": len(raw_items),
                "after_filter": len(filtered),
                "discarded": max(0, len(raw_items) - len(filtered)),
                "kept_titles": [item.get("title") for item in filtered[:30]],
            })
        return filtered
    except Exception as exc:
        print(f"[MONITOR][GoogleNews] Error for '{profile.brand_name}': {exc}")
        if request_id:
            log_source_run(request_id, "google_news", {
                "brand": profile.brand_name,
                "raw_found": 0,
                "after_filter": 0,
                "discarded": 0,
                "error": str(exc),
            })
        return []


SOURCE_COLLECTORS: tuple[tuple[str, Callable[[BrandProfile, int | None], list[dict]]], ...] = (
    ("newsapi", collect_newsapi),
    ("google_news", collect_google_news),
    ("reddit", collect_reddit),
    ("youtube", collect_youtube),
)


def collect_with_quota(
    source: str,
    collector: Callable[[BrandProfile, int | None], list[dict]],
    profile: BrandProfile,
    request_id: int | None = None,
) -> list[dict]:
    started_at = now_ist()
    source_start = time.time()
    if not can_use_source(source):
        print(f"[MONITOR][QUOTA] {source} quota exceeded; skipping {profile.brand_name}.")
        if request_id:
            log_source_run(request_id, source, {
                "brand": profile.brand_name,
                "called": False,
                "started_at": started_at,
                "finished_at": now_ist(),
                "duration_seconds": round(time.time() - source_start, 2),
                "raw_found": 0,
                "accepted": 0,
                "error": "quota exceeded",
            })
        return []

    items = collector(profile, request_id)
    increment_source_usage(source)
    if request_id:
        existing_log = load_source_run(request_id, source)
        log_source_run(request_id, source, {
            **existing_log,
            "brand": profile.brand_name,
            "called": True,
            "started_at": existing_log.get("started_at") or started_at,
            "finished_at": now_ist(),
            "duration_seconds": round(time.time() - source_start, 2),
            "accepted": len(items),
        })
    return items


def run_single_brand_monitor(
    brand_id: str,
    start_source_index: int = 0,
    scheduled: bool = False,
) -> dict:
    """Run all collectors for one brand only."""
    profile = get_brand_profile(brand_id)
    request_id = make_monitor_request_id()
    run_started_at = now_ist()
    run_start = time.time()
    counts = {}
    run_id = start_monitor_run(profile.brand_id)
    total_mentions = 0
    saved_mentions = 0
    duplicate_mentions = 0
    summary = {
        "entity_resolution": {"ok": True, "source": "profile loaded"},
        "sources": {},
        "storage": {"saved": 0, "duplicates": 0},
    }

    print(f"[MONITOR] Starting single-brand cycle for {profile.brand_name} (request {request_id})...")
    print(f"[MONITOR] Terms: {profile_search_terms(profile)}")

    try:
        for source_index, (source, collector) in enumerate(SOURCE_COLLECTORS[start_source_index:], start=start_source_index):
            if scheduled:
                with monitor_checkpoint(source):
                    items = collect_with_quota(source, collector, profile, request_id=request_id)
            else:
                items = collect_with_quota(source, collector, profile, request_id=request_id)
            for item in items:
                if save_mention(profile.brand_id, source, item):
                    saved_mentions += 1
                else:
                    duplicate_mentions += 1
            counts[source] = len(items)
            total_mentions += len(items)
            source_log = load_source_run(request_id, source)
            summary["sources"][source] = {
                "called": True,
                "raw_found": (
                    source_log.get("videos_found")
                    or source_log.get("raw_found")
                    or source_log.get("returned_articles")
                    or source_log.get("posts_scraped")
                    or len(items)
                ),
                "accepted": len(items),
                "duration_seconds": source_log.get("duration_seconds"),
                "discard_reasons": source_log.get("discard_reasons") or {},
                "error": source_log.get("error"),
            }
            print(f"[MONITOR]   {source}: {len(items)} matched items")
            if scheduled and (should_cancel_for_competitor() or should_cancel_for_reputation()):
                next_source_index = source_index + 1
                partial_duration = round(time.time() - run_start, 2)
                summary["storage"] = {
                    "saved": saved_mentions,
                    "duplicates": duplicate_mentions,
                    "duration_seconds": partial_duration,
                    "interrupted": True,
                    "next_source_index": next_source_index,
                }
                log_storage_run(request_id, {
                    "brand": profile.brand_name,
                    "started_at": run_started_at,
                    "finished_at": now_ist(),
                    "duration_seconds": partial_duration,
                    "collected_mentions": total_mentions,
                    "saved": saved_mentions,
                    "duplicates": duplicate_mentions,
                    "counts": counts,
                    "status": "interrupted_for_high_priority_task",
                    "next_source_index": next_source_index,
                })
                finish_monitor_run(
                    run_id,
                    "interrupted",
                    mentions_found=total_mentions,
                    error_message="Interrupted for high-priority competitor/reputation task",
                )
                print_monitor_summary(profile.brand_name, request_id, summary)
                print(
                    f"[MONITOR] Interrupted: {profile.brand_name} after {source}; "
                    f"next_source_index={next_source_index}\n"
                )
                return {
                    "brand_id": profile.brand_id,
                    "brand_name": profile.brand_name,
                    "request_id": request_id,
                    "counts": counts,
                    "total_mentions": total_mentions,
                    "saved_mentions": saved_mentions,
                    "status": "interrupted",
                    "next_source_index": next_source_index,
                }

        run_duration = round(time.time() - run_start, 2)
        summary["storage"] = {
            "saved": saved_mentions,
            "duplicates": duplicate_mentions,
            "duration_seconds": run_duration,
        }
        log_storage_run(request_id, {
            "brand": profile.brand_name,
            "started_at": run_started_at,
            "finished_at": now_ist(),
            "duration_seconds": run_duration,
            "collected_mentions": total_mentions,
            "saved": saved_mentions,
            "duplicates": duplicate_mentions,
            "counts": counts,
        })
        update_monitor_success(profile.brand_id)
        finish_monitor_run(run_id, "success", mentions_found=total_mentions)
        print_monitor_summary(profile.brand_name, request_id, summary)
        print(f"[MONITOR] Done: {profile.brand_name}\n")

        return {
            "brand_id": profile.brand_id,
            "brand_name": profile.brand_name,
            "request_id": request_id,
            "counts": counts,
            "total_mentions": total_mentions,
            "saved_mentions": saved_mentions,
        }
    except Exception as exc:
        error_message = str(exc)
        update_monitor_failure(profile.brand_id, error_message)
        finish_monitor_run(run_id, "failed", mentions_found=total_mentions, error_message=error_message)
        summary["storage"] = {
            "saved": saved_mentions,
            "duplicates": duplicate_mentions,
            "duration_seconds": round(time.time() - run_start, 2),
        }
        print_monitor_summary(profile.brand_name, request_id, summary)
        print(f"[MONITOR] Failed: {profile.brand_name}: {error_message}\n")
        raise


def run_brand_monitor_by_name(brand_name: str) -> dict:
    profile = get_brand_profile_by_name(brand_name)
    return run_single_brand_monitor(profile.brand_id)


def run_monitoring_cycle():
    """
    Scheduler entrypoint.

    Only due brands are refreshed. UI-triggered refreshes must use
    run_single_brand_monitor() instead.
    """
    global _SCHEDULED_CHECKPOINT
    if _SCHEDULED_CHECKPOINT:
        brand_ids = list(_SCHEDULED_CHECKPOINT.get("brand_ids") or [])
        brand_index = int(_SCHEDULED_CHECKPOINT.get("brand_index") or 0)
        source_index = int(_SCHEDULED_CHECKPOINT.get("source_index") or 0)
        if brand_index >= len(brand_ids):
            print("[MONITOR] Scheduled checkpoint already complete; clearing checkpoint.")
            _SCHEDULED_CHECKPOINT = None
            return {"status": "checkpoint_complete", "brands": 0}
        profiles = [
            get_brand_profile(brand_id)
            for brand_id in brand_ids[brand_index:]
        ]
        print(
            "[MONITOR] Resuming scheduled checkpoint: "
            f"brand_index={brand_index}, source_index={source_index}, "
            f"remaining_brands={len(profiles)}"
        )
    else:
        profiles = get_due_brand_profiles()
        brand_ids = [profile.brand_id for profile in profiles]
        brand_index = 0
        source_index = 0

    if not profiles:
        print("[MONITOR] No due active brands to monitor.")
        _SCHEDULED_CHECKPOINT = None
        return {"status": "no_due_brands", "brands": 0}

    print(f"[MONITOR] Starting scheduled cycle for {len(profiles)} due brand(s)...")
    results = []
    for offset, profile in enumerate(profiles):
        absolute_brand_index = brand_index + offset
        current_source_index = source_index if offset == 0 else 0
        if should_cancel_for_competitor() or should_cancel_for_reputation():
            _SCHEDULED_CHECKPOINT = {
                "brand_ids": brand_ids,
                "brand_index": absolute_brand_index,
                "source_index": current_source_index,
                "reason": "interrupted_before_brand_for_high_priority_task",
                "saved_at": now_ist(),
            }
            print(
                "[MONITOR] Scheduled cycle interrupted for high-priority task. "
                f"competitor={competitor_pause_status()} "
                f"reputation={reputation_pause_status()}"
            )
            return {
                "status": "interrupted_for_high_priority_task",
                "brands": len(results),
                "remaining_brands": len(profiles) - len(results),
                "checkpoint": _SCHEDULED_CHECKPOINT,
                "results": results,
            }
        try:
            result = run_single_brand_monitor(
                profile.brand_id,
                start_source_index=current_source_index,
                scheduled=True,
            )
            results.append(result)
            if result.get("status") == "interrupted":
                next_source_index = int(result.get("next_source_index") or 0)
                next_brand_index = absolute_brand_index
                if next_source_index >= len(SOURCE_COLLECTORS):
                    next_brand_index = absolute_brand_index + 1
                    next_source_index = 0
                _SCHEDULED_CHECKPOINT = {
                    "brand_ids": brand_ids,
                    "brand_index": next_brand_index,
                    "source_index": next_source_index,
                    "reason": "interrupted_after_source_for_high_priority_task",
                    "saved_at": now_ist(),
                }
                print(
                    "[MONITOR] Saved scheduled checkpoint. "
                    f"brand_index={next_brand_index}, source_index={next_source_index}"
                )
                return {
                    "status": "interrupted_for_high_priority_task",
                    "brands": len(results),
                    "remaining_brands": max(0, len(brand_ids) - next_brand_index),
                    "checkpoint": _SCHEDULED_CHECKPOINT,
                    "results": results,
                }
        except Exception as exc:
            results.append({
                "brand_id": profile.brand_id,
                "brand_name": profile.brand_name,
                "status": "failed",
                "error": str(exc),
            })
        if should_cancel_for_competitor() or should_cancel_for_reputation():
            _SCHEDULED_CHECKPOINT = {
                "brand_ids": brand_ids,
                "brand_index": absolute_brand_index + 1,
                "source_index": 0,
                "reason": "interrupted_after_brand_for_high_priority_task",
                "saved_at": now_ist(),
            }
            print(
                "[MONITOR] Scheduled cycle stopped after current brand for high-priority task. "
                f"competitor={competitor_pause_status()} "
                f"reputation={reputation_pause_status()}"
            )
            return {
                "status": "interrupted_for_high_priority_task",
                "brands": len(results),
                "remaining_brands": len(profiles) - len(results),
                "checkpoint": _SCHEDULED_CHECKPOINT,
                "results": results,
            }

    print("[MONITOR] Scheduled cycle complete.\n")
    _SCHEDULED_CHECKPOINT = None
    return {"status": "cycle completed", "brands": len(results), "results": results}
