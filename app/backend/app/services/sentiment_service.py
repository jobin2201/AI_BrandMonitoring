"""
Local sentiment and emotion enrichment for monitor mentions.

This keeps the monitor UI useful even when Kafka classification has not caught
up yet. It never calls an external API. If a RoBERTa sentiment model is already
available locally, it is used; otherwise it falls back to VADER.
"""
from __future__ import annotations

import os
from functools import lru_cache

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}

EMOTION_KEYWORDS = {
    "joy": {"love", "great", "best", "excellent", "happy", "win", "wins", "amazing", "good"},
    "anger": {"angry", "hate", "furious", "outrage", "calls out", "slams", "bad", "worst"},
    "disgust": {"disgust", "gross", "shame", "scam", "dirty"},
    "frustration": {"issue", "problem", "broken", "failed", "struggling", "complaint", "slow"},
    "trust": {"trusted", "official", "reliable", "secure", "heritage", "verified"},
}


@lru_cache(maxsize=1)
def _vader() -> SentimentIntensityAnalyzer:
    return SentimentIntensityAnalyzer()


@lru_cache(maxsize=1)
def _roberta_pipeline():
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=True)
        return pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,
            truncation=True,
            max_length=128,
        )
    except Exception:
        return None


def _normalise_roberta_label(label: str) -> str:
    label = (label or "").lower()
    if "positive" in label:
        return "positive"
    if "negative" in label:
        return "negative"
    return "neutral"


def _classify_with_roberta(text: str) -> dict | None:
    clf = _roberta_pipeline()
    if clf is None:
        return None

    try:
        result = clf(text or "no content")
        scores = {entry["label"].lower(): float(entry["score"]) for entry in result[0]}
        positive = scores.get("positive", 0.0)
        negative = scores.get("negative", 0.0)
        neutral = scores.get("neutral", 0.0)

        if positive > 0.2 and negative > 0.2:
            label = "mixed"
            confidence = min(positive, negative)
        else:
            top_label = max(scores, key=scores.get)
            label = _normalise_roberta_label(top_label)
            confidence = scores[top_label]

        sentiment_score = round(positive - negative, 3)
        return {
            "sentiment_label": label,
            "sentiment_score": sentiment_score,
            "sentiment_confidence": round(confidence, 3),
            "sentiment_breakdown": {
                "positive": round(positive, 3),
                "neutral": round(neutral, 3),
                "negative": round(negative, 3),
            },
            "sentiment_model": "roberta_local",
        }
    except Exception:
        return None


def _classify_with_vader(text: str) -> dict:
    scores = _vader().polarity_scores(text or "")
    compound = scores["compound"]
    positive = scores["pos"]
    negative = scores["neg"]

    if positive > 0.2 and negative > 0.2:
        label = "mixed"
        confidence = max(positive, negative)
    elif compound > 0.05:
        label = "positive"
        confidence = positive
    elif compound < -0.05:
        label = "negative"
        confidence = negative
    else:
        label = "neutral"
        confidence = scores["neu"]

    return {
        "sentiment_label": label,
        "sentiment_score": round(compound, 3),
        "sentiment_confidence": round(confidence, 3),
        "sentiment_breakdown": {
            "positive": round(positive, 3),
            "neutral": round(scores["neu"], 3),
            "negative": round(negative, 3),
        },
        "sentiment_model": "vader",
    }


def classify_emotion(text: str, sentiment_label: str) -> dict:
    lowered = (text or "").lower()
    best_emotion = None
    best_hits = 0

    for emotion, keywords in EMOTION_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if hits > best_hits:
            best_emotion = emotion
            best_hits = hits

    if not best_emotion:
        if sentiment_label == "positive":
            best_emotion = "joy"
        elif sentiment_label == "negative":
            best_emotion = "frustration"
        elif sentiment_label == "mixed":
            best_emotion = "frustration"
        else:
            best_emotion = "indifference"

    confidence = 0.55 + min(best_hits, 3) * 0.1 if best_hits else 0.5
    return {
        "emotion": best_emotion,
        "emotion_confidence": round(min(confidence, 0.9), 2),
    }


def enrich_item_sentiment(item: dict) -> dict:
    text = " ".join(
        part for part in [item.get("title"), item.get("body_text"), item.get("text")] if part
    ).strip()

    sentiment = _classify_with_roberta(text) or _classify_with_vader(text)
    emotion = classify_emotion(text, sentiment["sentiment_label"])

    enriched = dict(item)
    if not enriched.get("sentiment_label"):
        enriched["sentiment_label"] = sentiment["sentiment_label"]
    if enriched.get("sentiment_score") is None:
        enriched["sentiment_score"] = sentiment["sentiment_score"]
    if enriched.get("sentiment_confidence") is None:
        enriched["sentiment_confidence"] = sentiment["sentiment_confidence"]
    if enriched.get("sentiment_breakdown") is None:
        enriched["sentiment_breakdown"] = sentiment["sentiment_breakdown"]
    if not enriched.get("emotion"):
        enriched["emotion"] = emotion["emotion"]
    if enriched.get("emotion_confidence") is None:
        enriched["emotion_confidence"] = emotion["emotion_confidence"]
    return enriched
