from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "urchade/gliner_base"

LABELS = [
    "brand",
    "company",
    "organization",
    "airline",
    "product",
    "automobile brand",
    "technology company",
    "consumer brand",
]


@lru_cache(maxsize=1)
def get_gliner_model():
    try:
        from gliner import GLiNER

        print(f"[GLINER] Loading {MODEL_NAME}...")
        model = GLiNER.from_pretrained(MODEL_NAME)
        print("[GLINER] Model loaded")
        return model
    except Exception as exc:
        print(f"[GLINER] Model unavailable; entity detection disabled for this process: {exc}")
        return None


def build_gliner_context(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned.split()) <= 3:
        return (
            f"Analyze entities in news and social media brand monitoring context: "
            f"{cleaned} is mentioned as a possible brand, company, organization, airline, or product."
        )
    return f"Analyze entities in news and social media brand monitoring context: {cleaned}"


def detect_brand_entities(text: str, min_score: float = 0.5) -> list[dict]:
    if not text:
        return []

    try:
        model = get_gliner_model()
        if model is None:
            return []
        context_text = build_gliner_context(text)
        if hasattr(model, "predict_entities"):
            entities = model.predict_entities(context_text[:1000], LABELS)
        elif hasattr(model, "predict"):
            entities = model.predict(context_text[:1000], labels=LABELS)
        else:
            entities = []
        filtered = [
            entity for entity in (entities or [])
            if float(entity.get("score") or entity.get("confidence") or 0.0) >= min_score
        ]
        print(f"[GLINER] Detected {len(filtered)}/{len(entities or [])} entities above {min_score}")
        return filtered
    except Exception as exc:
        print(f"[GLINER] Entity detection skipped: {exc}")
        return []


def resolve_with_gliner(query: str, min_confidence: float = 0.5) -> dict | None:
    print("[ENTITY] Trying GLiNER...")
    entities = detect_brand_entities(query, min_score=min_confidence)
    if not entities:
        print("[ENTITY] GLiNER failed or found no entities")
        return None

    best = None
    for entity in entities:
        label = (entity.get("label") or "").lower()
        score = float(entity.get("score") or entity.get("confidence") or 0.0)
        text = (entity.get("text") or "").strip()
        if not text:
            continue
        if not any(allowed in label for allowed in ["brand", "company", "airline", "automobile", "organization", "product"]):
            continue
        if best is None or score > best["confidence"]:
            best = {"entity_name": text, "label": label, "confidence": score}

    if not best:
        print("[ENTITY] GLiNER found no brand/company entity")
        return None

    print(f"[ENTITY] GLiNER confidence: {best['confidence']:.2f}")
    if best["confidence"] < min_confidence:
        print("[ENTITY] GLiNER low confidence")
        return None

    print("[ENTITY] GLiNER success")
    entity_name = best["entity_name"]
    label = best["label"]
    entity_type = "product" if "product" in label else (
        "company" if any(term in label for term in ["company", "organization", "airline", "brand", "automobile"])
        else "brand"
    )
    return {
        "entity_name": entity_name,
        "entity_type": entity_type,
        "industry": "unknown",
        "description": f"{entity_name} identified by GLiNER as {best['label']}",
        "search_terms": [entity_name],
        "ignore_terms": [],
        "positive_terms": [],
        "negative_terms": [],
        "source": "gliner",
        "confidence": best["confidence"],
    }


def has_company_entity(text: str, brand_name: str, aliases: list[str] | None = None) -> bool:
    terms = [brand_name.lower(), *[alias.lower() for alias in (aliases or [])]]
    entities = detect_brand_entities(text)
    for entity in entities or []:
        entity_text = (entity.get("text") or "").lower()
        label = (entity.get("label") or "").lower()
        if any(term and term in entity_text for term in terms) and any(
            allowed in label for allowed in ["company", "brand", "automobile", "organization"]
        ):
            return True
    return False
