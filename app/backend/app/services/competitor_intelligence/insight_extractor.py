from __future__ import annotations

import os
import re
from collections import Counter

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))

STOPWORDS = {
    "able", "about", "after", "again", "also", "among", "been", "being",
    "brand", "brands", "could", "each", "from", "gets", "give", "given",
    "goes", "going", "good", "have", "having", "into", "just", "last",
    "like", "made", "make", "many", "more", "most", "much", "news",
    "official", "only", "over", "said", "says", "show", "some", "than",
    "that", "their", "them", "then", "there", "these", "they", "thing",
    "this", "those", "through", "time", "today", "using", "very", "want",
    "were", "what", "when", "where", "which", "while", "will", "with",
    "work", "would", "your", "review", "reviews", "first", "best",
    "latest", "launch", "launched", "video", "watch", "shorts", "update",
    "updates", "india", "global", "file", "files", "wall", "street",
    "article", "report", "reports", "users", "user", "people", "company",
    "companies", "socialism", "politics", "political", "stake", "stakes",
    "opinion", "opinions", "attack", "attacks", "controversy", "viral",
    "billionaire", "millionaire", "rumor", "rumors", "anonymous",
}

NOISY_TOPIC_TERMS = {
    "socialism", "politics", "political", "opinion", "stake", "stakes",
    "personal", "attack", "attacks", "controversy", "rumor", "rumors",
    "confidential", "filing", "paperwork", "exchange", "reportedly",
    "public", "sec",
}

JUNK_TEXT_RE = re.compile(
    r"\b(socialism|communism|democrat|republican|politics|election|political|taxing empty million dollar mansions)\b",
    re.IGNORECASE,
)

EVENT_ONLY_TOPIC_TERMS = {
    "ipo", "public", "confidential", "filing", "sec", "exchange",
    "paperwork", "market", "debut", "reportedly",
}

BUSINESS_TOPIC_WORDS = {
    "acquisition", "agent", "agents", "ai", "api", "app", "assistant",
    "battery", "camera", "capital", "charging", "codex", "cost",
    "customer", "developer", "developers", "display", "enterprise",
    "feature", "features", "funding", "growth", "hiring", "integration",
    "launch", "layoffs", "model", "models", "performance", "plan", "plans",
    "pricing", "privacy", "product", "products", "quality", "reasoning",
    "reliability", "revenue", "safety", "security", "service", "software",
    "subscription", "support", "token", "tokens", "tool", "tools",
    "upgrade", "valuation", "workforce",
}

DOMAIN_PHRASES = [
    "after sales",
    "ai features",
    "ai models",
    "app experience",
    "api pricing",
    "artificial intelligence",
    "battery drain",
    "battery life",
    "build quality",
    "camera quality",
    "charging speed",
    "codex",
    "customer service",
    "delivery experience",
    "developer tools",
    "display quality",
    "engine performance",
    "enterprise ai",
    "fuel efficiency",
    "generative ai",
    "ipo",
    "hiring",
    "hiring plans",
    "job cuts",
    "low price",
    "model pricing",
    "open source",
    "performance",
    "pricing",
    "pricing plan",
    "product quality",
    "reliability",
    "reasoning models",
    "resale value",
    "safety rating",
    "service center",
    "software support",
    "subscription pricing",
    "token pricing",
    "user experience",
    "warranty support",
    "workforce reduction",
]


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def load_mentions_for_brand(brand_id: str, limit: int = 200) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT title, body_text, source, sentiment_label, sentiment_score,
                   primary_category, emotion, relevance_score
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
                "source": row[2],
                "sentiment_label": row[3],
                "sentiment_score": row[4],
                "primary_category": row[5],
                "emotion": row[6],
                "relevance_score": row[7],
            }
            for row in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()


def load_brand_stop_terms(brand_id: str) -> set[str]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'monitored_brands'
            """
        )
        columns = {row[0] for row in cur.fetchall()}
        optional_columns = [
            col for col in ["aliases", "ceo_names", "executive_names"]
            if col in columns
        ]
        select_sql = ", ".join(["brand_name", *optional_columns])
        cur.execute(
            f"""
            SELECT {select_sql}
            FROM monitored_brands
            WHERE id = %s
            LIMIT 1
            """,
            (brand_id,),
        )
        row = cur.fetchone()
        if not row:
            return set()
        terms = set()
        values = [row[0] or ""]
        for index, col in enumerate(optional_columns, start=1):
            value = row[index] or []
            if isinstance(value, list):
                values.extend(value)
            elif isinstance(value, str):
                values.append(value)
        for value in values:
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+.-]{2,}", value.lower()):
                terms.add(token)
        return terms
    finally:
        cur.close()
        conn.close()


def extract_terms(text: str, extra_stopwords: set[str] | None = None) -> list[str]:
    blocked = STOPWORDS.union(extra_stopwords or set())
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+.-]{2,}", text.lower())
    return [word for word in words if word not in blocked]


def extract_meaningful_topics(text: str, extra_stopwords: set[str] | None = None) -> list[str]:
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    topics: list[str] = []
    blocked = STOPWORDS.union(extra_stopwords or set())

    for phrase in DOMAIN_PHRASES:
        if phrase in normalized:
            topics.append(phrase)

    words = extract_terms(normalized, blocked)
    for size in (3, 2):
        for index in range(0, max(len(words) - size + 1, 0)):
            phrase_words = words[index:index + size]
            if not phrase_words:
                continue
            if phrase_words[0] in blocked or phrase_words[-1] in blocked:
                continue
            if not BUSINESS_TOPIC_WORDS.intersection(set(phrase_words)):
                continue
            phrase = " ".join(phrase_words)
            if len(phrase) >= 8:
                topics.append(phrase)

    topics.extend(word for word in words if len(word) >= 5 and word in BUSINESS_TOPIC_WORDS)
    return [
        topic for topic in topics
        if not NOISY_TOPIC_TERMS.intersection(set(topic.split()))
        and not EVENT_ONLY_TOPIC_TERMS.intersection(set(topic.split()))
    ]


def summarize_mentions(mentions: list[dict], extra_stopwords: set[str] | None = None) -> dict:
    positive = []
    negative = []
    neutral = []
    sentiment_counts = Counter()
    source_counts = Counter()
    category_counts = Counter()
    positive_examples = []
    negative_examples = []

    for mention in mentions:
        text = " ".join([mention.get("title") or "", mention.get("body_text") or ""])
        if JUNK_TEXT_RE.search(text):
            continue
        score = mention.get("sentiment_score")
        label = (mention.get("sentiment_label") or "").lower()
        sentiment_counts[label or "unknown"] += 1
        source_counts[mention.get("source") or "unknown"] += 1
        if mention.get("primary_category"):
            category_counts[mention.get("primary_category")] += 1
        topics = extract_meaningful_topics(text, extra_stopwords)
        if label == "positive" or (isinstance(score, (int, float)) and score > 0.2):
            positive.extend(topics)
            if len(positive_examples) < 5 and mention.get("title"):
                positive_examples.append(mention.get("title"))
        elif label == "negative" or (isinstance(score, (int, float)) and score < -0.2):
            negative.extend(topics)
            if len(negative_examples) < 5 and mention.get("title"):
                negative_examples.append(mention.get("title"))
        else:
            neutral.extend(topics)

    strength_topics = [term for term, _ in Counter(positive).most_common(12)]
    weakness_topics = [term for term, _ in Counter(negative).most_common(12)]
    common_topics = [term for term, _ in Counter([*positive, *negative, *neutral]).most_common(16)]
    return {
        "strength_topics": strength_topics,
        "weakness_topics": weakness_topics,
        "common_topics": common_topics,
        "strengths": strength_topics,
        "weaknesses": weakness_topics,
        "mention_count": len(mentions),
        "sentiment_counts": dict(sentiment_counts),
        "sentiment_distribution": dict(sentiment_counts),
        "source_counts": dict(source_counts),
        "category_counts": dict(category_counts),
        "positive_examples": positive_examples,
        "negative_examples": negative_examples,
    }


def extract_brand_insights(brand_id: str, limit: int = 200) -> dict:
    mentions = load_mentions_for_brand(brand_id, limit=limit)
    return summarize_mentions(mentions, load_brand_stop_terms(brand_id))
