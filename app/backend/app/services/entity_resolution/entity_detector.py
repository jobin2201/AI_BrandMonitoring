from __future__ import annotations

from functools import lru_cache

LABELS = ["car brand", "company", "automobile brand", "organization", "product"]


@lru_cache(maxsize=1)
def get_gliner_model():
    try:
        from gliner import GLiNER

        print("[GLINER] Loading urchade/gliner_medium-v2.1...")
        model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
        print("[GLINER] Model loaded")
        return model
    except Exception as exc:
        print(f"[GLINER] Model unavailable; entity detection disabled for this process: {exc}")
        return None


def detect_brand_entities(text: str) -> list[dict]:
    if not text:
        return []

    try:
        model = get_gliner_model()
        if model is None:
            return []
        if hasattr(model, "predict_entities"):
            return model.predict_entities(text[:1000], LABELS)
        if hasattr(model, "predict"):
            return model.predict(text[:1000], labels=LABELS)
        return []
    except Exception as exc:
        print(f"[GLINER] Entity detection skipped: {exc}")
        return []


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
