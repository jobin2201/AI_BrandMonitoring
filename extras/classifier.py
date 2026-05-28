"""
Reputation Intelligence — Hybrid Classifier
RoBERTa (local) → fast, accurate sentiment scoring
Your LLM (API)  → smart categorization, emotion, aspect detection
"""
import requests
import json
import time
import torch
from collections import Counter
from transformers import pipeline
import config


# ═══════════════════════════════════════════════════════
# CATEGORY & EMOTION DEFINITIONS
# ═══════════════════════════════════════════════════════

VALID_EMOTIONS = config.VALID_EMOTIONS


def get_category_set(mode="reviews"):
    """Return appropriate category definitions based on content type."""
    if mode == "news":
        return config.NEWS_CATEGORIES
    return config.REVIEW_CATEGORIES


# ═══════════════════════════════════════════════════════
# 1. ROBERTA SENTIMENT (local, fast)
# ═══════════════════════════════════════════════════════

SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"


def load_sentiment_model():
    print("   📥 Loading RoBERTa sentiment model...")
    start = time.time()

    # Auto-detect best device
    if torch.cuda.is_available():
        device = 0
        device_name = f"CUDA GPU ({torch.cuda.get_device_name(0)})"
        batch_size = 64
    else:
        device = -1
        device_name = "CPU"
        batch_size = 32

    clf = pipeline(
        "sentiment-analysis",
        model=SENTIMENT_MODEL,
        tokenizer=SENTIMENT_MODEL,
        top_k=None,
        truncation=True,
        max_length=128,           # was 512 — most reviews are far shorter; 4x faster on CPU
        batch_size=batch_size,
        device=device,
    )
    print(f"   ✅ RoBERTa loaded in {time.time()-start:.1f}s on {device_name} (batch={batch_size})")
    return clf


def classify_sentiment_batch(clf, texts: list) -> list:
    valid_texts = [t if t and isinstance(t, str) else "neutral text" for t in texts]
    try:
        results = clf(valid_texts)
    except Exception as e:
        print(f"   ⚠️ Sentiment batch error: {e}. Falling back to single processing.")
        results = [clf(t) for t in valid_texts]

    processed = []
    for res_list in results:
        scores = {r["label"]: r["score"] for r in res_list}
        top_label = max(scores, key=scores.get)
        sentiment_score = (
            scores.get("positive", 0) * 1.0
            + scores.get("neutral", 0) * 0.0
            + scores.get("negative", 0) * -1.0
        )
        processed.append({
            "label": top_label,
            "confidence": round(scores[top_label], 3),
            "sentiment_score": round(sentiment_score, 3),
            "scores": {k: round(v, 3) for k, v in scores.items()},
        })
    return processed


# ═══════════════════════════════════════════════════════
# 2. LLM API (your local LLM)
# ═══════════════════════════════════════════════════════

def call_llm(prompt, format_type="json"):
    """Call your local LLM API."""
    headers = {
        'accept': 'application/json',
        'API-key': config.LLM_API_KEY,
        'Content-Type': 'application/json'
    }
    url = f"{config.LLM_BASE_URL}/generate/generate?request={requests.utils.quote(prompt)}"
    payload = {}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        if response.status_code != 200:
            print(f"   ⚠️ LLM API error: {response.status_code}")
            return None
        return response.json()
    except requests.ConnectionError:
        print(f"   ❌ Cannot connect to LLM at {config.LLM_BASE_URL}")
        return None
    except requests.Timeout:
        print(f"   ❌ LLM request timed out")
        return None
    except Exception as e:
        print(f"   ❌ LLM request error: {e}")
        return None


def parse_llm_json(response_data):
    """Extract and parse JSON from LLM response."""
    if response_data is None:
        return None

    text = ""
    if isinstance(response_data, str):
        text = response_data
    elif isinstance(response_data, dict):
        text = (response_data.get("response") or
                response_data.get("text") or
                response_data.get("output") or
                response_data.get("generated_text") or
                response_data.get("result") or
                str(response_data))
    elif isinstance(response_data, list):
        return response_data
    else:
        text = str(response_data)

    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    start_bracket = text.find("[")
    start_brace = text.find("{")

    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        end = text.rfind("]") + 1
        text = text[start_bracket:end]
    elif start_brace != -1:
        end = text.rfind("}") + 1
        text = text[start_brace:end]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except json.JSONDecodeError:
        print(f"   ⚠️ Failed to parse LLM JSON. Raw: {text[:200]}")
        return None


def build_categorization_prompt(reviews_batch, category_definitions, valid_emotions):
    """Build LLM prompt with dynamic categories."""
    reviews_text = ""
    for review in reviews_batch:
        text = review["text"][:600].replace('"', "'")
        reviews_text += f'\n  {{"id": {review["id"]}, "text": "{text}"}}'

    cat_descriptions = "\n".join([
        f'  - "{k}" = {v}' for k, v in category_definitions.items()
    ])

    prompt = f"""You are a reputation intelligence analyst. Categorize each item below.

For EACH item, return a JSON object with:
- "id": the item id
- "primary_category": one of [{", ".join(category_definitions.keys())}]
{cat_descriptions}
- "emotion": one of [{", ".join(valid_emotions)}]
- "aspect_sentiments": object mapping relevant categories to a score from -1.0 (very negative) to 1.0 (very positive). Only include categories the item actually discusses. Be precise.

Items:
[{reviews_text}
]

Respond ONLY with a valid JSON array. No explanation, no markdown."""

    return prompt


# ═══════════════════════════════════════════════════════
# 3. KEYWORD FALLBACK (if LLM is down)
# ═══════════════════════════════════════════════════════

def fallback_categorize(review, category_definitions):
    """Simple keyword fallback if LLM is unreachable."""
    text = review.get("text", "").lower()
    rating = review.get("rating", 3)

    best_cat = "general"
    best_count = 0
    for cat, desc in category_definitions.items():
        if cat == "general":
            continue
        keywords = desc.lower().replace(",", "").split()
        count = sum(1 for kw in keywords if len(kw) > 3 and kw in text)
        if count > best_count:
            best_count = count
            best_cat = cat

    emotion = "indifference"
    if rating >= 4:
        emotion = "joy"
    elif rating == 1:
        emotion = "anger"
    elif rating == 2:
        emotion = "frustration"
    elif rating == 3:
        emotion = "indifference"

    return {
        "primary_category": best_cat,
        "emotion": emotion,
        "aspect_sentiments": {},
    }


# ═══════════════════════════════════════════════════════
# 4. HYBRID CLASSIFIER
# ═══════════════════════════════════════════════════════

BATCH_SIZE = 12


class ReviewClassifier:
    def __init__(self):
        print("\n📦 Loading Hybrid Classifier...\n")
        self.sentiment_clf = load_sentiment_model()

        print("   🔗 Testing LLM API connection...")
        test_prompt = 'Return JSON: [{"id":1,"primary_category":"general","emotion":"joy","aspect_sentiments":{}}]'
        test = call_llm(test_prompt)
        if test is not None:
            print("   ✅ LLM API connected!\n")
            self.llm_available = True
        else:
            print("   ❌ LLM API unreachable. Using keyword fallback.\n")
            self.llm_available = False

        print("   ✅ Classifier ready!\n")

    def classify_batch(self, reviews: list, mode: str = "reviews") -> list:
        """
        Classify a batch of reviews/articles.
        mode: 'reviews' or 'news' — determines category set
        """
        print(f"\n🔍 Classifying {len(reviews)} items (mode: {mode})...\n")
        start_time = time.time()

        if not reviews:
            return []

        texts = [r["text"] for r in reviews]
        total = len(texts)
        category_definitions = get_category_set(mode)
        valid_cats = list(category_definitions.keys())

        # ── STEP 1: RoBERTa Sentiment ──
        print(f"   🧠 RoBERTa: Analyzing sentiment for {total} items...")
        sentiments = classify_sentiment_batch(self.sentiment_clf, texts)
        print(f"   ✅ Sentiment done.\n")

        # ── STEP 2: LLM Categorization ──
        print(f"   🤖 LLM: Categorizing items...")
        llm_results = {}

        if self.llm_available:
            for i in range(0, total, BATCH_SIZE):
                batch = reviews[i:i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
                print(f"      📤 Batch {batch_num}/{total_batches} ({len(batch)} items)...")

                prompt = build_categorization_prompt(batch, category_definitions, VALID_EMOTIONS)
                response = call_llm(prompt)
                parsed = parse_llm_json(response)

                if parsed and isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "id" in item:
                            llm_results[item["id"]] = item
                else:
                    print(f"      ⚠️ Batch {batch_num} failed, using fallback...")
                    for review in batch:
                        llm_results[review["id"]] = fallback_categorize(review, category_definitions)

                if i + BATCH_SIZE < total:
                    time.sleep(0.5)
        else:
            print("      Using keyword fallback for all items...")
            for review in reviews:
                llm_results[review["id"]] = fallback_categorize(review, category_definitions)

        print(f"   ✅ Categorization done.\n")

        # ── STEP 3: Merge Results ──
        results = []
        for i, review in enumerate(reviews):
            sent = sentiments[i]
            llm = llm_results.get(review["id"], fallback_categorize(review, category_definitions))

            cat = llm.get("primary_category", "general")
            if cat not in valid_cats:
                cat = "general"

            emotion = llm.get("emotion", "indifference")
            if emotion not in VALID_EMOTIONS:
                emotion = "indifference"

            aspect_sentiments = llm.get("aspect_sentiments", {})
            if not isinstance(aspect_sentiments, dict):
                aspect_sentiments = {}
            clean_aspects = {}
            for k, v in aspect_sentiments.items():
                if k in valid_cats and k != "general":
                    try:
                        clean_aspects[k] = round(max(-1.0, min(1.0, float(v))), 2)
                    except (ValueError, TypeError):
                        pass

            result = {
                **review,
                "primary_category": cat,
                "sentiment": sent["label"],
                "sentiment_score": sent["sentiment_score"],
                "sentiment_confidence": sent["confidence"],
                "sentiment_breakdown": sent["scores"],
                "aspects_detected": {k: 1.0 for k in clean_aspects},
                "aspect_sentiments": clean_aspects,
                "emotion": emotion,
                "emotion_confidence": 0.8 if self.llm_available else 0.5,
            }
            results.append(result)

        elapsed = time.time() - start_time
        print(f"   ✅ Classified {total} items in {elapsed:.1f}s\n")
        return results

    def generate_overall_summary(self, classified_data: list, mode: str = "reviews") -> dict:
        """
        Generate an AI executive summary across all classified items.
        Returns a structured dict, or None if the LLM is unreachable / parse fails.
        """
        if not classified_data:
            return None
        if not self.llm_available:
            print("   ⚠️ LLM unavailable — cannot generate AI summary.")
            return None

        total = len(classified_data)
        pos = [r for r in classified_data if r.get("sentiment") == "positive"]
        neg = [r for r in classified_data if r.get("sentiment") == "negative"]
        neu = [r for r in classified_data if r.get("sentiment") == "neutral"]
        avg_score = sum(r.get("sentiment_score", 0) for r in classified_data) / total

        # Per-category stats
        cat_groups = {}
        for r in classified_data:
            cat_groups.setdefault(r.get("primary_category", "general"), []).append(
                r.get("sentiment_score", 0)
            )
        cat_summary = {
            k: {"avg_score": round(sum(v) / len(v), 2), "count": len(v)}
            for k, v in cat_groups.items()
        }

        # Emotion distribution
        emotions = {}
        for r in classified_data:
            e = r.get("emotion", "indifference")
            emotions[e] = emotions.get(e, 0) + 1

        # Top exemplars
        neg_sorted = sorted(neg, key=lambda r: r.get("sentiment_score", 0))[:5]
        pos_sorted = sorted(pos, key=lambda r: r.get("sentiment_score", 0), reverse=True)[:5]

        def _fmt_examples(items):
            if not items:
                return "  (none)"
            lines = []
            for r in items:
                text = (r.get("text", "") or "")[:300].replace('"', "'").replace("\n", " ")
                lines.append(f'  - "{text}"')
            return "\n".join(lines)

        subject = "customer reviews" if mode == "reviews" else "news articles"

        prompt = f"""You are an executive reputation analyst. Write a strategic summary based on {total} analyzed {subject}.

DATA OVERVIEW
- Total items: {total}
- Positive: {len(pos)} ({len(pos)/total*100:.1f}%)
- Neutral:  {len(neu)} ({len(neu)/total*100:.1f}%)
- Negative: {len(neg)} ({len(neg)/total*100:.1f}%)
- Average sentiment score (-1 to +1): {avg_score:.2f}

CATEGORY BREAKDOWN (avg score, count)
{json.dumps(cat_summary, indent=2)}

EMOTION DISTRIBUTION
{json.dumps(emotions, indent=2)}

TOP NEGATIVE EXAMPLES
{_fmt_examples(neg_sorted)}

TOP POSITIVE EXAMPLES
{_fmt_examples(pos_sorted)}

Return ONLY a JSON object with these fields:
- "headline": one-sentence executive verdict (max 30 words)
- "overall_status": one of ["healthy", "monitor", "warning", "critical"]
- "key_strengths": array of 2-4 short strings describing what users/audiences value (max 25 words each)
- "key_concerns": array of 2-4 short strings describing top complaints or risks (max 25 words each)
- "patterns": array of 1-3 short strings describing emerging themes or notable findings
- "recommendations": array of 2-4 short actionable strings for the team
- "drawbacks_narrative": a single flowing paragraph (3-6 sentences, 60-120 words) describing the main drawbacks and pain points users experience. Reference real issues. Plain prose, no bullets, no markdown.
- "improvements_narrative": a single flowing paragraph (3-6 sentences, 60-120 words) describing how the product/brand could be improved, prioritized by impact. Plain prose, no bullets, no markdown.

Be specific. Reference real issues from the examples, not generic advice.
Respond ONLY with valid JSON. No markdown, no explanation."""

        print(f"\n🤖 Generating AI executive summary for {total} items...")
        response = call_llm(prompt)
        parsed = parse_llm_json(response)

        if isinstance(parsed, list) and parsed:
            result = parsed[0] if isinstance(parsed[0], dict) else None
        elif isinstance(parsed, dict):
            result = parsed
        else:
            result = None

        if result:
            print("   ✅ AI summary generated.")
            # Stash the size so the UI can flag staleness later
            result["_based_on"] = total
        else:
            print("   ⚠️ AI summary failed to generate / parse.")
        return result

    def cluster_by_category(self, reviews: list) -> list:
        """Group reviews by their LLM-assigned primary_category."""
        print("📊 Grouping items by category...")
        cat_to_id = {}
        counter = 0
        for review in reviews:
            cat = review.get("primary_category", "general")
            if cat not in cat_to_id:
                cat_to_id[cat] = counter
                counter += 1
            review["topic_cluster"] = cat_to_id[cat]
        print(f"   ✅ Grouped into {len(cat_to_id)} categories.\n")
        return reviews