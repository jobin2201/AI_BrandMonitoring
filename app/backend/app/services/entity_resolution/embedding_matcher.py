"""
Semantic similarity scorer using sentence-transformers.

Runs after brand_matcher.py to catch contextually relevant mentions that the
rule-based matcher considers borderline.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"

BRAND_CONTEXT_TEMPLATES = {
    "default": "{brand_name} company technology product review",
    "tesla": "{brand_name} electric vehicle car battery autopilot cybertruck model y company technology",
    "dell": "{brand_name} computers laptops servers monitors enterprise technology company",
    "nike": "{brand_name} sportswear sneakers shoes apparel athlete football brand",
    "apple": "{brand_name} iphone mac ipad consumer technology software hardware company",
    "samsung": "{brand_name} electronics smartphones galaxy appliances semiconductor company",
}


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    print(f"[EMBEDDING] Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    print("[EMBEDDING] Model loaded")
    return model


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


@lru_cache(maxsize=256)
def get_brand_embedding_cached(brand_name: str, aliases_key: tuple[str, ...]) -> np.ndarray:
    model = get_model()
    context = BRAND_CONTEXT_TEMPLATES.get(
        brand_name.lower(),
        BRAND_CONTEXT_TEMPLATES["default"],
    ).format(brand_name=brand_name)

    if aliases_key:
        context += " " + " ".join(aliases_key)

    return model.encode(context, normalize_embeddings=True)


def get_brand_embedding(brand_name: str, aliases: list[str] | None = None) -> np.ndarray:
    aliases_key = tuple(alias for alias in (aliases or []) if alias)
    return get_brand_embedding_cached(brand_name, aliases_key)


def score_semantic_similarity(
    brand_name: str,
    title: str = "",
    text: str = "",
    aliases: list[str] | None = None,
    brand_context: str = "",
    threshold: float = 0.35,
) -> dict:
    try:
        model = get_model()
        combined = " ".join(part for part in [title, text] if part).strip()
        if not combined:
            return {"semantic_score": 0.0, "semantic_match": False, "method": "embedding"}

        if brand_context:
            brand_vec = model.encode(brand_context, normalize_embeddings=True)
        else:
            brand_vec = get_brand_embedding(brand_name, aliases)
        mention_vec = model.encode(combined[:512], normalize_embeddings=True)
        score = cosine_similarity(brand_vec, mention_vec)

        return {
            "semantic_score": round(score, 4),
            "semantic_match": score >= threshold,
            "method": "embedding",
        }
    except Exception as exc:
        print(f"[EMBEDDING] Error scoring '{brand_name}': {exc}")
        return {"semantic_score": 0.0, "semantic_match": False, "method": "embedding_error"}
