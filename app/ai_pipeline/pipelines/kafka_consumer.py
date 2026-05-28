# import os
# import json
# import psycopg2
# from kafka import KafkaConsumer
# from dotenv import load_dotenv
# from app.ai_pipeline.sentiment.vader_sentiment import analyse

# # Load environment variables
# from pathlib import Path
# env_path = Path(__file__).resolve().parents[2] / "backend/.env"
# load_dotenv(dotenv_path=env_path)

# # Kafka Config
# KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")

# # PostgreSQL Config
# POSTGRES_HOST = os.getenv("POSTGRES_HOST")
# POSTGRES_PORT = os.getenv("POSTGRES_PORT")
# POSTGRES_DB = os.getenv("POSTGRES_DB")
# POSTGRES_USER = os.getenv("POSTGRES_USER")
# POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

# # Connect to PostgreSQL
# conn = psycopg2.connect(
#     host=POSTGRES_HOST,
#     port=POSTGRES_PORT,
#     database=POSTGRES_DB,
#     user=POSTGRES_USER,
#     password=POSTGRES_PASSWORD
# )

# cursor = conn.cursor()

# # Kafka Consumer
# consumer = KafkaConsumer(
#     "brand.news.global",
#     bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
#     value_deserializer=lambda x: json.loads(x.decode("utf-8")),
#     auto_offset_reset="earliest",
#     group_id="nlp-pipeline-v5"
# )

# print("Consumer is listening...")

# for message in consumer:

#     data = message.value

#     articles = data.get("articles", [])

#     print(f"Received {len(articles)} articles")

#     for article in articles:
#         try:
#             source_name = article.get("source", {}).get("name")
#             title = article.get("title")
#             url = article.get("url")
#             author = article.get("author")
#             published_at = article.get("publishedAt")

#             cursor.execute("""
#                 INSERT INTO articles (
#                     source_name,
#                     url,
#                     title,
#                     author,
#                     published_at
#                 )
#                 VALUES (%s, %s, %s, %s, %s)
#                 ON CONFLICT (url) DO NOTHING
#             """, (
#                 source_name,
#                 url,
#                 title,
#                 author,
#                 published_at
#             ))
#             conn.commit()
#             print("Inserted:", title)

#             # Sentiment analysis
#             text = f"{title}"
#             result = analyse(text)
#             sentiment_label = result["label"]
#             compound_score = result["compound"]

#             cursor.execute("""
#                 INSERT INTO sentiment_results (
#                     article_id,
#                     sentiment_label,
#                     compound_score
#                 )
#                 VALUES (
#                     (
#                         SELECT article_id
#                         FROM articles
#                         WHERE url = %s
#                     ),
#                     %s,
#                     %s
#                 )
#             """, (
#                 url,
#                 sentiment_label,
#                 compound_score
#             ))
#             conn.commit()
#             print(f"Sentiment: {sentiment_label} ({compound_score})")

#         except Exception as e:
#             print("Error:", e)
import os
import json
import uuid
import psycopg2
from kafka import KafkaConsumer, errors as kafka_errors
from dotenv import load_dotenv
from pathlib import Path

# Load env
env_path = Path(__file__).resolve().parents[2] / "backend/.env"
load_dotenv(dotenv_path=env_path)

from app.ai_pipeline.sentiment.hybrid_classifier import ReviewClassifier

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    database=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
)
cursor = conn.cursor()

classifier = ReviewClassifier()


try:
    consumer = KafkaConsumer(
        "brand.news.global",
        "brand.reddit.global",
        "brand.youtube.global",
        "brand.reviews.global",
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        auto_offset_reset="latest",  # Always process new messages only
        group_id="nlp-pipeline-v5",
    )
except kafka_errors.NoBrokersAvailable:
    print("❌ No Kafka brokers available at:", KAFKA_BOOTSTRAP_SERVERS)
    print("Please ensure your Kafka server is running and accessible.")
    import sys
    sys.exit(1)

TOPIC_MODE = {
    "brand.news.global":    "news",
    "brand.reddit.global":  "social",
    "brand.youtube.global": "social",
    "brand.reviews.global": "reviews",
}


def normalise_items(topic: str, data: dict) -> list:
    print(f"[DEBUG] Raw Kafka message for topic {topic}: {json.dumps(data)[:500]}")
    items = []

    if topic == "brand.news.global":
        articles = data.get("articles", [])
        print(f"[DEBUG] Found {len(articles)} articles in NewsAPI payload.")
        for i, a in enumerate(articles):
            items.append({
                "id":           f"news_{i}_{a.get('url','')[-20:]}",
                "text":         a.get("description") or a.get("content") or a.get("title") or "",
                "title":        a.get("title"),
                "url":          a.get("url"),
                "source_name":  a.get("source", {}).get("name"),
                "author":       a.get("author"),
                "published_at": a.get("publishedAt"),
                "platform":     "newsapi",
            })

    elif topic == "brand.reddit.global":
        posts = data.get("posts", [data] if "title" in data else [])
        print(f"[DEBUG] Found {len(posts)} posts in Reddit payload.")
        for i, p in enumerate(posts):
            items.append({
                "id":           f"reddit_{i}_{p.get('id', i)}",
                "text":         p.get("selftext") or p.get("body") or p.get("content") or p.get("title") or "",
                "title":        p.get("title") or p.get("content"),
                "url":          p.get("url"),
                "source_name":  f"r/{p.get('subreddit', 'reddit')}" if p.get("subreddit") else "Reddit",
                "author":       p.get("author") or p.get("username"),
                "published_at": p.get("created_utc") or p.get("published_at") or p.get("date"),
                "platform":     "reddit",
            })

    elif topic == "brand.youtube.global":
        videos = data.get("videos", [data] if ("videoId" in data or "video_id" in data) else [])
        print(f"[DEBUG] Found {len(videos)} videos in YouTube payload.")
        for i, v in enumerate(videos):
            video_id = v.get("videoId") or v.get("video_id")
            items.append({
                "id":           f"yt_{i}_{video_id or i}",
                "text":         v.get("description") or v.get("title") or "",
                "title":        v.get("title"),
                "url":          v.get("video_url") or v.get("url") or f"https://youtube.com/watch?v={video_id or ''}",
                "source_name":  v.get("channelTitle") or v.get("youtuber"),
                "author":       v.get("channelTitle") or v.get("youtuber"),
                "published_at": v.get("publishedAt") or v.get("published"),
                "platform":     "youtube",
            })

    return items


def save_article(item: dict):
    """
    Insert into articles using your actual schema.
    - article_id is uuid → generate it here
    - body_text not text
    - url has unique constraint → ON CONFLICT DO NOTHING
    Returns the article_id uuid if inserted, or fetches existing one.
    """
    new_id = str(uuid.uuid4())

    cursor.execute("""
        INSERT INTO articles (
            article_id,
            source_name,
            url,
            title,
            body_text,
            author,
            published_at,
            platform
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url) DO NOTHING
        RETURNING article_id
    """, (
        new_id,
        item.get("source_name"),
        item.get("url"),
        item.get("title"),
        item.get("text", ""),      # body_text ← your actual column name
        item.get("author"),
        item.get("published_at"),
        item.get("platform", "unknown"),
    ))
    row = cursor.fetchone()
    conn.commit()
    if row:
        print(f"[DB] Inserted article: {item.get('title','')[:80]} | {item.get('url','')}")
    else:
        print(f"[DB] Duplicate article (not inserted): {item.get('title','')[:80]} | {item.get('url','')}")

    if row:
        # Fresh insert — return the new uuid
        return row[0]
    else:
        # Duplicate URL — fetch the existing article_id
        cursor.execute(
            "SELECT article_id FROM articles WHERE url = %s", (item.get("url"),)
        )
        existing = cursor.fetchone()
        return existing[0] if existing else None


def save_sentiment(article_id: str, item: dict):
    """
    Save classification to sentiment_results.
    article_id is uuid (str).
    ON CONFLICT updates existing row if re-processed.
    """
    cursor.execute("""
        INSERT INTO sentiment_results (
            id,
            article_id,
            sentiment_label,
            compound_score,
            primary_category,
            emotion,
            aspect_sentiments,
            sentiment_confidence,
            sentiment_breakdown,
            emotion_confidence,
            llm_used
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (article_id) DO UPDATE SET
            sentiment_label      = EXCLUDED.sentiment_label,
            compound_score       = EXCLUDED.compound_score,
            primary_category     = EXCLUDED.primary_category,
            emotion              = EXCLUDED.emotion,
            aspect_sentiments    = EXCLUDED.aspect_sentiments,
            sentiment_confidence = EXCLUDED.sentiment_confidence,
            sentiment_breakdown  = EXCLUDED.sentiment_breakdown,
            emotion_confidence   = EXCLUDED.emotion_confidence,
            llm_used             = EXCLUDED.llm_used
    """, (
        str(uuid.uuid4()),
        article_id,
        item.get("sentiment"),
        item.get("sentiment_score"),
        item.get("primary_category"),
        item.get("emotion"),
        json.dumps(item.get("aspect_sentiments", {})),
        item.get("sentiment_confidence"),
        json.dumps(item.get("sentiment_breakdown", {})),
        item.get("emotion_confidence"),
        item.get("llm_used", "unknown"),
    ))
    conn.commit()


# ── Main loop ──────────────────────────────────────────────────────────────────

print("🚀 Consumer listening on: brand.news.global, brand.reddit.global, brand.youtube.global")

def classify_items_safely(items: list, mode: str) -> list:
    try:
        return classifier.classify(items, mode=mode)
    except Exception as batch_error:
        print(f"Batch classification failed: {batch_error}")
        print("Retrying item-by-item so one bad item does not drop the whole batch.")

    classified = []
    for item in items:
        try:
            classified.extend(classifier.classify([item], mode=mode))
        except Exception as item_error:
            print(f"Classification failed for item, using safe fallback: {item_error}")
            print(f"    title: {(item.get('title') or '')[:120]}")
            fallback = dict(item)
            fallback.update({
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "sentiment_confidence": 0.0,
                "sentiment_breakdown": {"positive": 0.0, "neutral": 1.0, "negative": 0.0},
                "primary_category": "general",
                "emotion": "indifference",
                "emotion_confidence": 0.0,
                "aspect_sentiments": {},
                "llm_used": "fallback_after_error",
            })
            classified.append(fallback)
    return classified


def save_classified_item(item: dict) -> bool:
    try:
        item['sentiment'] = item.get('sentiment') or ''
        item['sentiment_confidence'] = item.get('sentiment_confidence') or 0
        item['emotion'] = item.get('emotion') or ''
        item['emotion_confidence'] = item.get('emotion_confidence') or 0

        print("\nDEBUG: Classifier output for item:")
        for k, v in item.items():
            print(f"    {k}: {v}")

        article_id = save_article(item)
        if article_id:
            save_sentiment(article_id, item)
            score = item.get("sentiment_score", 0)
            print(f"  SAVED {item.get('platform')} | {item.get('sentiment')} ({score:+.2f}) | {item.get('primary_category')} | {item.get('title','')[:60]}")
            return True

        print(f"  Skipped (no article_id): {item.get('url','')[:60]}")
        return False
    except Exception as item_error:
        print(f"Error saving classified item: {item_error}")
        print(f"    title: {(item.get('title') or '')[:120]}")
        conn.rollback()
        return False


for message in consumer:
    topic = message.topic
    data  = message.value
    mode  = TOPIC_MODE.get(topic, "news")

    try:
        items = normalise_items(topic, data)
        if not items:
            print(f"⚠️ [{topic}] Empty payload, skipping.")
            continue

        print(f"\n📨 [{topic}] {len(items)} items — classifying as '{mode}'...")

        classified = classify_items_safely(items, mode=mode)


        saved_count = 0
        for item in classified:
            if save_classified_item(item):
                saved_count += 1
            continue

            # Set defaults for classifier fields to avoid NULLs in DB
            item['sentiment'] = item.get('sentiment') or ''
            item['sentiment_confidence'] = item.get('sentiment_confidence') or 0
            item['emotion'] = item.get('emotion') or ''
            item['emotion_confidence'] = item.get('emotion_confidence') or 0

            # DEBUG: Print full classification result for each item
            print("\n🔎 DEBUG: Classifier output for item:")
            for k, v in item.items():
                print(f"    {k}: {v}")

            article_id = save_article(item)
            if article_id:
                save_sentiment(article_id, item)
                score = item.get("sentiment_score", 0)
                print(f"  ✅ {item.get('platform')} | {item.get('sentiment')} ({score:+.2f}) | {item.get('primary_category')} | {item.get('title','')[:60]}")
            else:
                print(f"  ⏭️  Skipped (no article_id): {item.get('url','')[:60]}")

    except Exception as e:
        print(f"❌ Error processing [{topic}]: {e}")
        conn.rollback()
