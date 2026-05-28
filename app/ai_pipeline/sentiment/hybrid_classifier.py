"""
Hybrid Classifier — RoBERTa (local) for sentiment + Groq LLM for categories/emotions/aspects
Drop-in replacement for vader_sentiment.py
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import json
import time
import requests
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
from dotenv import load_dotenv
from pathlib import Path



# Load env from absolute path
env_path = r"F:/WORK/NEWPROJECTS/new_brand_monitoring/app/backend/.env"
print(f"DEBUG: Loading .env from {env_path}")
load_dotenv(dotenv_path=env_path)

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
print(f"DEBUG: GROQ_API_KEY={'set' if GROQ_API_KEY else 'missing'}")
GROQ_BASE_URL  = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
BATCH_SIZE = 10  # items sent to Groq per call

# ── Category definitions ──────────────────────────────────────────────────────

NEWS_CATEGORIES = {
    "corporate_reputation": "Company reputation, brand image, public perception, trust",
    "product_service":      "Product launches, service quality, features, innovation",
    "leadership":           "CEO, executives, management decisions, leadership changes",
    "financial_performance":"Earnings, revenue, stock price, profits, financial results",
    "legal_regulatory":     "Lawsuits, regulations, compliance, legal issues, policy",
    "esg":                  "Environmental, social, governance, sustainability, CSR",
    "competition":          "Competitors, market share, industry ranking, rivalry",
    "general":              "General news without specific business category",
}

REVIEW_CATEGORIES = {
    "performance":       "Bugs, crashes, speed, stability, loading, freezing, battery",
    "ui_ux":             "Design, layout, navigation, interface, fonts, dark mode, intuitive",
    "features":          "Functionality, missing features, updates, tools, capabilities",
    "ads_monetization":  "Ads, popups, subscriptions, pricing, paywalls, cost, premium",
    "support":           "Customer support, developer response, help center, service",
    "security_privacy":  "Data, permissions, login, trust, safety, privacy policy",
    "general":           "General feedback without specific category",
}

SOCIAL_CATEGORIES = {
    "brand_mention":    "Direct mention of brand, product, or company name",
    "sentiment_opinion":"User opinion, review, or feeling about a brand/product",
    "complaint":        "Complaints, issues, problems reported by users",
    "praise":           "Positive feedback, appreciation, recommendation",
    "question":         "User asking about a product or brand",
    "viral_trend":      "Trending content, memes, viral mentions",
    "general":          "General social content without specific category",
}

VALID_EMOTIONS = ["joy", "anger", "disgust", "frustration", "trust", "indifference"]


# ── 1. RoBERTa Sentiment (local) ──────────────────────────────────────────────

def load_sentiment_model():
    print("📥 Loading RoBERTa sentiment model...")
    start = time.time()

    if torch.cuda.is_available():
        device = 0
        device_name = f"CUDA ({torch.cuda.get_device_name(0)})"
        batch_size = 32
    else:
        device = -1
        device_name = "CPU"
        batch_size = 16

    allow_download = os.getenv("ALLOW_HF_DOWNLOADS", "0") == "1"
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            SENTIMENT_MODEL,
            local_files_only=not allow_download,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            SENTIMENT_MODEL,
            local_files_only=not allow_download,
        )
        clf = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,
            truncation=True,
            max_length=128,
            batch_size=batch_size,
            device=device,
        )
    except Exception as exc:
        if allow_download:
            raise
        print(f"RoBERTa local load failed without network: {exc}")
        print("Set ALLOW_HF_DOWNLOADS=1 once if you need to download the model.")
        return None
    print(f"✅ RoBERTa loaded in {time.time()-start:.1f}s on {device_name}")
    return clf


def classify_sentiment_batch(clf, texts: list) -> list:
    """Run RoBERTa on a list of texts. Returns list of dicts."""
    safe_texts = [t if t and isinstance(t, str) else "no content" for t in texts]
    if clf is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        analyzer = SentimentIntensityAnalyzer()
        processed = []
        for text in safe_texts:
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]
            label = "positive" if compound > 0.05 else "negative" if compound < -0.05 else "neutral"
            processed.append({
                "label": label,
                "confidence": round(max(scores["pos"], scores["neu"], scores["neg"]), 3),
                "sentiment_score": round(compound, 3),
                "scores": {
                    "positive": round(scores["pos"], 3),
                    "neutral": round(scores["neu"], 3),
                    "negative": round(scores["neg"], 3),
                },
            })
        return processed

    try:
        results = clf(safe_texts)
    except Exception as e:
        print(f"⚠️ Sentiment batch error: {e}. Falling back one-by-one.")
        results = [clf(t) for t in safe_texts]

    processed = []
    for res_list in results:
        scores = {r["label"]: r["score"] for r in res_list}
        top_label = max(scores, key=scores.get)
        sentiment_score = (
            scores.get("positive", 0) * 1.0
            + scores.get("neutral",  0) * 0.0
            + scores.get("negative", 0) * -1.0
        )
        processed.append({
            "label":           top_label,
            "confidence":      round(scores[top_label], 3),
            "sentiment_score": round(sentiment_score, 3),
            "scores":          {k: round(v, 3) for k, v in scores.items()},
        })
    return processed


# ── 2. Groq LLM (replaces local LLM) ─────────────────────────────────────────

def call_groq(prompt: str) -> str | None:
    """Call Groq API using OpenAI-compatible endpoint."""
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in .env")
        return None

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    try:
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.Timeout:
        print("❌ Groq request timed out")
        return None
    except Exception as e:
        print(f"❌ Groq error: {e}")
        return None


def parse_llm_json(text: str | None):
    """Safely extract JSON array or object from LLM response text."""
    if not text:
        return None
    text = text.strip()

    # Strip markdown code fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # Find outermost [ ] or { }
    start_bracket = text.find("[")
    start_brace   = text.find("{")

    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        end  = text.rfind("]") + 1
        text = text[start_bracket:end]
    elif start_brace != -1:
        end  = text.rfind("}") + 1
        text = text[start_brace:end]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except json.JSONDecodeError:
        print(f"⚠️ JSON parse failed. Raw snippet: {text[:200]}")
        return None


def build_prompt(items: list, category_definitions: dict, mode: str) -> str:
    items_text = ""
    for item in items:
        text = (item.get("text") or item.get("title") or "")[:500].replace('"', "'")
        items_text += f'\n  {{"id": "{item["id"]}", "text": "{text}"}}'

    cat_descriptions = "\n".join(
        f'  - "{k}" = {v}' for k, v in category_definitions.items()
    )
    cat_keys = ", ".join(category_definitions.keys())
    emotion_keys = ", ".join(VALID_EMOTIONS)

    subject = {
        "news":    "news article",
        "reviews": "app/product review",
        "social":  "social media post",
    }.get(mode, "content item")

    return f"""You are a reputation intelligence analyst classifying {subject}s.

For EACH item return a JSON object with:
- "id": the item id (string, exactly as given)
- "primary_category": one of [{cat_keys}]
{cat_descriptions}
- "emotion": one of [{emotion_keys}]
- "aspect_sentiments": object mapping relevant categories to score -1.0 to 1.0

Items:
[{items_text}
]

Respond ONLY with a valid JSON array. No explanation, no markdown."""


# ── 3. Keyword Fallback ───────────────────────────────────────────────────────

def fallback_categorize(item: dict, category_definitions: dict) -> dict:
    text = (item.get("text") or item.get("title") or "").lower()
    best_cat, best_count = "general", 0
    for cat, desc in category_definitions.items():
        if cat == "general":
            continue
        keywords = desc.lower().replace(",", "").split()
        count = sum(1 for kw in keywords if len(kw) > 3 and kw in text)
        if count > best_count:
            best_cat, best_count = cat, count

    # Ensure brand is present in text/title/source_name for DB matching
    brand = item.get("brand") or ""
    def ensure_brand(val):
        if not val:
            return brand
        val_lc = val.lower()
        if brand and brand.lower() not in val_lc:
            return f"{brand} {val}".strip()
        return val

    # Patch fields in fallback mode
    item["title"] = ensure_brand(item.get("title"))
    item["text"] = ensure_brand(item.get("text"))
    item["source_name"] = ensure_brand(item.get("source_name"))

    return {
        "primary_category":  best_cat,
        "emotion":           "indifference",
        "aspect_sentiments": {},
    }


# ── 4. ReviewClassifier ───────────────────────────────────────────────────────

class ReviewClassifier:
    """
    Unified classifier for news, reviews, and social media content.
    Uses RoBERTa for sentiment, Groq for categorization/emotion/aspects.
    """

    def __init__(self):
        self.sentiment_clf = load_sentiment_model()

        # Quick connectivity check
        test = call_groq("Reply with the word OK only.")
        self.llm_available = test is not None and "OK" in (test or "").upper()
        if self.llm_available:
            print(f"✅ Groq LLM connected ({GROQ_MODEL})")
        else:
            print("⚠️ Groq unavailable — keyword fallback active")

    def _get_categories(self, mode: str) -> dict:
        return {
            "news":    NEWS_CATEGORIES,
            "reviews": REVIEW_CATEGORIES,
            "social":  SOCIAL_CATEGORIES,
        }.get(mode, NEWS_CATEGORIES)

    def classify(self, items: list, mode: str = "news") -> list:
        """
        Classify a list of items.

        Each item must have at minimum:
          - "id"   (str)
          - "text" or "title" (str)

        mode: "news" | "reviews" | "social"
        Returns the original items enriched with sentiment + category fields.
        """
        if not items:
            return []

        print(f"\n🔍 Classifying {len(items)} items (mode={mode})...")
        category_defs = self._get_categories(mode)
        valid_cats    = list(category_defs.keys())

        # ── Step 1: Sentiment via RoBERTa ──
        texts = [
            (item.get("text") or item.get("title") or "") for item in items
        ]
        sentiments = classify_sentiment_batch(self.sentiment_clf, texts)

        # ── Step 2: Category / Emotion via Groq (batched) ──
        llm_results = {}
        if self.llm_available:
            for i in range(0, len(items), BATCH_SIZE):
                batch      = items[i : i + BATCH_SIZE]
                batch_num  = i // BATCH_SIZE + 1
                total_b    = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
                print(f"  📤 Groq batch {batch_num}/{total_b} ({len(batch)} items)...")

                prompt  = build_prompt(batch, category_defs, mode)
                raw     = call_groq(prompt)
                parsed  = parse_llm_json(raw)

                if parsed and isinstance(parsed, list):
                    for entry in parsed:
                        if isinstance(entry, dict) and "id" in entry:
                            llm_results[str(entry["id"])] = entry
                else:
                    print(f"  ⚠️ Batch {batch_num} failed — using keyword fallback")
                    for item in batch:
                        llm_results[str(item["id"])] = fallback_categorize(item, category_defs)

                if i + BATCH_SIZE < len(items):
                    time.sleep(0.3)   # respect Groq rate limits
        else:
            for item in items:
                llm_results[str(item["id"])] = fallback_categorize(item, category_defs)

        # ── Step 3: Merge ──
        results = []
        for idx, item in enumerate(items):
            sent = sentiments[idx]
            llm  = llm_results.get(str(item["id"]), fallback_categorize(item, category_defs))

            cat = llm.get("primary_category", "general")
            if cat not in valid_cats:
                cat = "general"

            emotion = llm.get("emotion", "indifference")
            if emotion not in VALID_EMOTIONS:
                emotion = "indifference"

            raw_aspects = llm.get("aspect_sentiments", {}) or {}
            clean_aspects = {}
            for k, v in raw_aspects.items():
                if k in valid_cats and k != "general":
                    try:
                        clean_aspects[k] = round(max(-1.0, min(1.0, float(v))), 2)
                    except (ValueError, TypeError):
                        pass

            results.append({
                **item,
                "primary_category":      cat,
                "sentiment":             sent["label"],
                "sentiment_score":       sent["sentiment_score"],
                "sentiment_confidence":  sent["confidence"],
                "sentiment_breakdown":   sent["scores"],
                "emotion":               emotion,
                "emotion_confidence":    0.85 if self.llm_available else 0.5,
                "aspect_sentiments":     clean_aspects,
                "llm_used":              "groq" if self.llm_available else "fallback",
            })

        print(f"✅ Done classifying {len(results)} items\n")
        return results
