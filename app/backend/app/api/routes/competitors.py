from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.competitor_intelligence.comparison_engine import (
    compare_with_competitor,
)
from app.services.competitor_intelligence.competitor_detector import (
    discover_competitors,
)
from app.services.competitor_intelligence.intelligence_engine import (
    generate_competitor_intelligence,
)
from app.services.competitor_intelligence.scheduler_pause import scheduler_pause

router = APIRouter()


class CompareRequest(BaseModel):
    brand_id: str
    competitor: str | None = None
    competitor_name: str | None = None
    product_names: list[str] = Field(default_factory=list)
    service_names: list[str] = Field(default_factory=list)
    ceo_names: list[str] = Field(default_factory=list)
    executive_names: list[str] = Field(default_factory=list)
    campaign_names: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    competitor_keywords: list[str] = Field(default_factory=list)


def format_competitor(item: dict[str, Any]) -> dict[str, Any]:
    name = item.get("competitor_name") or item.get("name") or ""
    competitor_type = item.get("competitor_type") or item.get("type") or "direct"
    return {
        "id": item.get("id"),
        "name": name,
        "competitor_name": name,
        "type": competitor_type,
        "competitor_type": competitor_type,
        "confidence": item.get("confidence"),
        "mention_count": item.get("mention_count"),
        "category_relevance": item.get("category_relevance"),
        "brand_overlap_score": item.get("brand_overlap_score"),
        "expected_domain": item.get("expected_domain"),
        "candidate_domain": item.get("candidate_domain"),
        "confidence_breakdown": item.get("confidence_breakdown") or {},
        "reason": item.get("reason"),
        "source": item.get("source"),
        "discovered_at": item.get("discovered_at"),
    }


@router.post("/discover/{brand_id}")
def discover_brand_competitors(brand_id: str, refresh: bool = False, limit: int = 8):
    try:
        with scheduler_pause("competitor_discovery"):
            competitors = discover_competitors(brand_id, limit=limit, refresh=refresh)
        return {
            "brand_id": brand_id,
            "competitors": [format_competitor(item) for item in competitors],
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Competitor discovery failed: {exc}") from exc


@router.post("/compare")
def compare_competitor(payload: CompareRequest):
    competitor_name = (payload.competitor_name or payload.competitor or "").strip()
    if not competitor_name:
        raise HTTPException(status_code=400, detail="competitor is required")

    try:
        competitor_profile = payload.dict()
        competitor_profile["competitor_name"] = competitor_name
        with scheduler_pause("competitor_comparison"):
            return compare_with_competitor(payload.brand_id, competitor_profile)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Competitor comparison failed: {exc}") from exc


@router.post("/intelligence")
def competitor_intelligence(payload: CompareRequest):
    competitor_name = (payload.competitor_name or payload.competitor or "").strip()
    if not competitor_name:
        raise HTTPException(status_code=400, detail="competitor is required")

    try:
        competitor_profile = payload.dict()
        competitor_profile["competitor_name"] = competitor_name
        with scheduler_pause("competitor_intelligence"):
            return generate_competitor_intelligence(payload.brand_id, competitor_profile)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Competitor intelligence failed: {exc}") from exc


@router.get("/comparison/{comparison_id}")
def read_comparison(comparison_id: str):
    raise HTTPException(
        status_code=410,
        detail="Competitor comparisons are temporary and are no longer stored in the database.",
    )


@router.get("/{brand_id}")
def get_brand_competitors(brand_id: str):
    try:
        with scheduler_pause("competitor_list"):
            return {
                "brand_id": brand_id,
                "competitors": [format_competitor(item) for item in discover_competitors(brand_id)],
                "stored": False,
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load competitors: {exc}") from exc
