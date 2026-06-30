from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.bw_workspace.repository import (
    STORAGE_DIR,
    ensure_storage_files,
    get_workspace,
    get_mentions,
    list_companies,
    save_mentions,
    save_workspace,
)
from app.services.bw_workspace.ai_intelligence import generate_workspace_intelligence
from app.services.bw_workspace.monitoring_scope import resolve_monitoring_scope
from app.services.bw_workspace.reputation_service import generate_bw_reputation


router = APIRouter()


class ProductInput(BaseModel):
    name: str = ""
    description: str = ""


class ExecutiveInput(BaseModel):
    name: str = ""
    role: str = ""


class WorkspaceInput(BaseModel):
    companyName: str = Field(min_length=1)
    industry: str = ""
    brands: list[str] = Field(default_factory=list)
    products: list[ProductInput] = Field(default_factory=list)
    ceo: ExecutiveInput = Field(default_factory=ExecutiveInput)
    ceos: list[ExecutiveInput] = Field(default_factory=list)
    executives: list[ExecutiveInput] = Field(default_factory=list)
    campaigns: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sources: dict[str, bool] = Field(default_factory=dict)


class MentionInput(BaseModel):
    keyword: str = ""
    keywordType: str = ""
    searchQuery: str = ""
    source: str
    title: str = ""
    content: str = ""
    url: str = ""
    author: str = ""
    sentiment: str = ""
    sentimentScore: float | None = None
    sentimentConfidence: float | None = None
    emotion: str = ""
    emotionConfidence: float | None = None
    primaryCategory: str = ""
    publishedAt: str = ""


class MentionsInput(BaseModel):
    mentions: list[MentionInput] = Field(default_factory=list)


class MonitoringScopeInput(BaseModel):
    selectedKeywords: list[str] = Field(default_factory=list)


class ReputationInput(BaseModel):
    brandId: str = Field(min_length=1)
    forceRefresh: bool = False


@router.on_event("startup")
def initialize_bw_storage() -> None:
    ensure_storage_files()


@router.get("/workspaces")
def get_bw_companies() -> dict[str, Any]:
    return {
        "companies": list_companies(),
        "storage_location": str(STORAGE_DIR),
    }


@router.get("/workspaces/{company_name}")
def get_bw_workspace(company_name: str) -> dict[str, Any]:
    workspace = get_workspace(company_name)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Company workspace not found")
    return workspace


@router.post("/workspaces")
def save_bw_workspace(payload: WorkspaceInput) -> dict[str, Any]:
    try:
        payload_data = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        workspace = save_workspace(payload_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": f'Workspace "{workspace["companyName"]}" saved successfully',
        "workspace": workspace,
        "storage_location": str(STORAGE_DIR),
    }


@router.get("/workspaces/{company_name}/mentions")
def get_bw_mentions(
    company_name: str,
    run_id: str = Query("latest", description="Use latest, all, or a specific monitoring run id"),
) -> dict[str, Any]:
    try:
        mentions = get_mentions(company_name, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    active_run_id = mentions[0].get("run_id") if mentions else ""
    return {
        "company_name": company_name,
        "run_id": active_run_id,
        "run_filter": run_id,
        "mentions": mentions,
        "total": len(mentions),
        "storage_location": str(STORAGE_DIR / "mentions.csv"),
    }


@router.post("/workspaces/{company_name}/mentions")
def save_bw_mentions(company_name: str, payload: MentionsInput) -> dict[str, Any]:
    mention_data = [
        item.model_dump() if hasattr(item, "model_dump") else item.dict()
        for item in payload.mentions
    ]
    try:
        result = save_mentions(company_name, mention_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "message": f'Monitoring results saved for "{company_name}"',
        **result,
    }


@router.post("/workspaces/{company_name}/monitoring-scope")
def get_bw_monitoring_scope(company_name: str, payload: MonitoringScopeInput) -> dict[str, Any]:
    workspace = get_workspace(company_name)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Company workspace not found")
    return resolve_monitoring_scope(workspace, payload.selectedKeywords)


@router.post("/workspaces/{company_name}/ai-analysis")
def generate_bw_ai_analysis(company_name: str) -> dict[str, Any]:
    try:
        return generate_workspace_intelligence(company_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI intelligence generation failed: {exc}",
        ) from exc


@router.post("/workspaces/{company_name}/reputation")
def generate_bw_reputation_signals(company_name: str, payload: ReputationInput) -> dict[str, Any]:
    if get_workspace(company_name) is None:
        raise HTTPException(status_code=404, detail="Company workspace not found")
    try:
        return generate_bw_reputation(
            company_name=company_name,
            brand_id=payload.brandId,
            force_refresh=payload.forceRefresh,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BW reputation generation failed: {exc}",
        ) from exc
