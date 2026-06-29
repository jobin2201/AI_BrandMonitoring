
import redis
import os
import json
import re
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
CACHE_TTL = 7 * 24 * 60 * 60  # 7 days

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def normalize_cache_key(query):
    normalized = (query or "").lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()

def get_cached_entity(query):
    key = f"entity:{normalize_cache_key(query)}"
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as exc:
        print(f"[CACHE] Redis read skipped: {exc}")
    return None

def set_cached_entity(query, value):
    key = f"entity:{normalize_cache_key(query)}"
    try:
        redis_client.setex(key, CACHE_TTL, json.dumps(value))
    except Exception as exc:
        print(f"[CACHE] Redis write skipped: {exc}")
