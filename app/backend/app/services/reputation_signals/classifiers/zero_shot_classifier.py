from __future__ import annotations

import os
from typing import Any


_ZERO_SHOT_PIPELINE = None
_ZERO_SHOT_ERROR = ""


def _load_zero_shot_pipeline():
    global _ZERO_SHOT_PIPELINE, _ZERO_SHOT_ERROR
    if _ZERO_SHOT_PIPELINE is not None:
        return _ZERO_SHOT_PIPELINE
    if _ZERO_SHOT_ERROR:
        return None
    try:
        from transformers import pipeline

        model = os.getenv("REPUTATION_ZERO_SHOT_MODEL", "facebook/bart-large-mnli")
        _ZERO_SHOT_PIPELINE = pipeline("zero-shot-classification", model=model)
        return _ZERO_SHOT_PIPELINE
    except Exception as exc:
        _ZERO_SHOT_ERROR = str(exc)
        print(f"[REPUTATION] Zero-shot classifier unavailable: {exc}")
        return None


def classify_zero_shot(text: str, labels: list[str]) -> dict[str, Any]:
    classifier = _load_zero_shot_pipeline()
    if classifier is None:
        return {
            "available": False,
            "text": text,
            "label": "none",
            "confidence": 0.0,
            "scores": {},
            "error": _ZERO_SHOT_ERROR,
        }

    try:
        result = classifier(text[:1200], candidate_labels=labels, multi_label=False)
    except Exception as exc:
        print(f"[REPUTATION] Zero-shot classification skipped: {exc}")
        return {
            "available": False,
            "text": text,
            "label": "none",
            "confidence": 0.0,
            "scores": {},
            "error": str(exc),
        }

    result_labels = result.get("labels") or []
    scores = result.get("scores") or []
    score_map = {
        label: round(float(score), 4)
        for label, score in zip(result_labels, scores)
    }
    return {
        "available": True,
        "text": text,
        "label": result_labels[0] if result_labels else "none",
        "confidence": round(float(scores[0]), 4) if scores else 0.0,
        "scores": score_map,
    }
