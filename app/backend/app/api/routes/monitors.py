from fastapi import APIRouter, Query
import psycopg2, os, uuid
from dotenv import load_dotenv
from app.services.monitor_service import run_single_brand_monitor
from app.services.sentiment_service import enrich_item_sentiment
from app.services.entity_resolution.brand_profile_generator import build_brand_profile

router = APIRouter()
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'))

def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),     port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),   user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def ensure_brand_metadata_tables(cur):
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brand_channels (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          brand_id UUID REFERENCES monitored_brands(id),
          source TEXT,
          channel_name TEXT,
          channel_url TEXT,
          verified BOOLEAN DEFAULT FALSE
        )
    """)
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_confidence DOUBLE PRECISION")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_reason TEXT")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS matched_terms TEXT[]")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS sentiment_confidence DOUBLE PRECISION")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS emotion_confidence DOUBLE PRECISION")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS relevance_score DOUBLE PRECISION")
    cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS semantic_score DOUBLE PRECISION")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS industry TEXT")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS context_terms TEXT[]")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS negative_terms TEXT[]")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS brand_context TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brand_exclusions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          brand_id UUID REFERENCES monitored_brands(id),
          phrase TEXT
        )
    """)


DEFAULT_BRAND_METADATA = {
    "dell": {
        "channels": [
            ("youtube", "Dell Technologies", "https://www.youtube.com/@DellTech", True),
            ("youtube", "Dell Technologies India", "https://www.youtube.com/@DellTechIndia", True),
            ("youtube", "Alienware", "https://www.youtube.com/@Alienware", True),
        ],
        "exclusions": [
            "Farmer in the Dell",
            "nursery rhyme",
            "kids songs",
            "karaoke",
            "lyrics",
        ],
    },
    "samsung": {
        "channels": [
            ("youtube", "Samsung", "https://www.youtube.com/@Samsung", True),
            ("youtube", "Samsung India", "https://www.youtube.com/@SamsungIndia", True),
            ("youtube", "Samsung Electronics", "https://www.youtube.com/@Samsung", True),
        ],
        "exclusions": [
            "sam sung",
            "song",
            "lyrics",
            "karaoke",
        ],
    },
}


def seed_default_brand_metadata(cur, brand_id, brand_name: str):
    defaults = DEFAULT_BRAND_METADATA.get(brand_name.strip().lower())
    if not defaults:
        return

    for source, channel_name, channel_url, verified in defaults["channels"]:
        cur.execute("""
            INSERT INTO brand_channels (brand_id, source, channel_name, channel_url, verified)
            SELECT %s, %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM brand_channels
                WHERE brand_id = %s AND source = %s AND lower(channel_name) = lower(%s)
            )
        """, (brand_id, source, channel_name, channel_url, verified, brand_id, source, channel_name))

    for phrase in defaults["exclusions"]:
        cur.execute("""
            INSERT INTO brand_exclusions (brand_id, phrase)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM brand_exclusions
                WHERE brand_id = %s AND lower(phrase) = lower(%s)
            )
        """, (brand_id, phrase, brand_id, phrase))

@router.post("/")
def create_monitor(brand_name: str = Query(...), aliases: str = Query("")):
    """Create a new brand monitor. aliases = comma-separated e.g. 'Air Jordan,Nike SB'"""
    brand_name = brand_name.strip()
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    brand_profile = build_brand_profile(brand_name, alias_list)
    merged_aliases = list(dict.fromkeys([*alias_list, *brand_profile["aliases"]]))
    conn = get_conn(); cur = conn.cursor()
    ensure_brand_metadata_tables(cur)
    cur.execute("""
        INSERT INTO monitored_brands (
            brand_name, aliases, is_active, industry,
            context_terms, negative_terms, brand_context
        )
        VALUES (%s, %s, TRUE, %s, %s, %s, %s)
        ON CONFLICT (brand_name) DO UPDATE SET
            is_active=TRUE,
            aliases=CASE
                WHEN cardinality(EXCLUDED.aliases) > 0 THEN EXCLUDED.aliases
                ELSE monitored_brands.aliases
            END,
            industry=COALESCE(EXCLUDED.industry, monitored_brands.industry),
            context_terms=CASE
                WHEN cardinality(EXCLUDED.context_terms) > 0 THEN EXCLUDED.context_terms
                ELSE monitored_brands.context_terms
            END,
            negative_terms=CASE
                WHEN cardinality(EXCLUDED.negative_terms) > 0 THEN EXCLUDED.negative_terms
                ELSE monitored_brands.negative_terms
            END,
            brand_context=COALESCE(EXCLUDED.brand_context, monitored_brands.brand_context)
        RETURNING id
    """, (
        brand_name,
        merged_aliases,
        brand_profile["industry"],
        brand_profile["positive_terms"],
        brand_profile["negative_terms"],
        brand_profile["brand_context"],
    ))
    brand_id = cur.fetchone()[0]
    seed_default_brand_metadata(cur, brand_id, brand_name)
    for phrase in brand_profile["negative_terms"]:
        cur.execute("""
            INSERT INTO brand_exclusions (brand_id, phrase)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM brand_exclusions
                WHERE brand_id = %s AND lower(phrase) = lower(%s)
            )
        """, (brand_id, phrase, brand_id, phrase))
    conn.commit(); cur.close(); conn.close()
    return {
        "status": "created",
        "brand_id": str(brand_id),
        "brand_name": brand_name,
        "profile": brand_profile,
    }

@router.get("/")
def list_monitors():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, brand_name, aliases, is_active, created_at, last_run_at
        FROM monitored_brands ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [
        {"id": str(r[0]), "brand_name": r[1], "aliases": r[2], 
         "is_active": r[3], "created_at": r[4], "last_run_at": r[5]}
        for r in rows
    ]

@router.delete("/{brand_id}")
def delete_monitor(brand_id: str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE monitored_brands SET is_active=FALSE WHERE id=%s", (brand_id,))
    conn.commit(); cur.close(); conn.close()
    return {"status": "paused", "brand_id": brand_id}

@router.get("/mentions")
def get_mentions(brand_name: str = Query(...), source: str = Query(None), limit: int = 100):
    conn = get_conn(); cur = conn.cursor()
    ensure_brand_metadata_tables(cur)
    conn.commit()
    query = """
        SELECT bm.title, bm.url, bm.source, bm.published_at,
               COALESCE(bm.sentiment_label, sr.sentiment_label) AS sentiment_label,
               COALESCE(bm.sentiment_score, sr.compound_score) AS sentiment_score,
               COALESCE(bm.primary_category, sr.primary_category) AS primary_category,
               COALESCE(bm.emotion, sr.emotion) AS emotion,
               bm.match_confidence, bm.match_reason, bm.matched_terms,
               bm.relevance_score, bm.semantic_score,
               COALESCE(bm.sentiment_confidence, sr.sentiment_confidence) AS sentiment_confidence,
               COALESCE(bm.emotion_confidence, sr.emotion_confidence) AS emotion_confidence
        FROM brand_mentions bm
        JOIN monitored_brands mb ON bm.brand_id = mb.id
        LEFT JOIN articles a ON a.url = bm.url
        LEFT JOIN sentiment_results sr ON sr.article_id = a.article_id
        WHERE mb.brand_name ILIKE %s
    """
    params = [brand_name]
    if source:
        query += " AND bm.source = %s"
        params.append(source)
    query += " ORDER BY bm.collected_at DESC LIMIT %s"
    params.append(limit)
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    mentions = []
    for r in rows:
        mention = {
            "title": r[0], "url": r[1], "source": r[2], "published_at": r[3],
            "sentiment_label": r[4], "sentiment_score": r[5],
            "primary_category": r[6], "emotion": r[7],
            "match_confidence": r[8], "match_reason": r[9], "matched_terms": r[10] or [],
            "relevance_score": r[11], "semantic_score": r[12],
            "sentiment_confidence": r[13], "emotion_confidence": r[14],
        }
        if not mention["sentiment_label"] or mention["sentiment_score"] is None:
            mention = enrich_item_sentiment(mention)
        mentions.append(mention)
    return mentions

@router.post("/run-brand/{brand_id}")
def trigger_brand_now(brand_id: str):
    """Manually trigger monitoring for one brand only."""
    result = run_single_brand_monitor(brand_id)
    return {"status": "brand cycle completed", **result}


@router.post("/run-now")
def trigger_now():
    """Deprecated: use /run-brand/{brand_id} so UI actions do not rerun all brands."""
    return {
        "status": "deprecated",
        "message": "Use POST /api/monitors/run-brand/{brand_id} to refresh one brand.",
    }
