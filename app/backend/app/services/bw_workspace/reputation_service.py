from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.bw_workspace.reputation_cache import (
    get_cached_reputation,
    set_cached_reputation,
)
from app.services.bw_workspace.reputation_health import (
    calculate_crisis_score,
    calculate_reputation_health,
)
from app.services.bw_workspace.reputation_postprocessor import postprocess_reputation
from app.services.bw_workspace.reputation_summary import build_reputation_summary
from app.services.reputation_signals.engine.identity import run_brand_reputation_analysis
from app.services.reputation_signals.scheduler_pause import scheduler_pause


def generate_bw_reputation(
    company_name: str,
    brand_id: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cache_key = f"{company_name.strip().casefold()}:{brand_id}"
    if not force_refresh:
        cached = get_cached_reputation(cache_key)
        if cached:
            return cached

    with scheduler_pause("bw_reputation_signals"):
        raw = run_brand_reputation_analysis(brand_id)
    processed = postprocess_reputation(raw)
    health = calculate_reputation_health(processed)
    crisis = calculate_crisis_score(processed)
    summary = build_reputation_summary(processed)
    result = {
        **processed,
        "bw_reputation": True,
        "bw_generated_at": datetime.now(timezone.utc).isoformat(),
        "bw_health": health,
        "bw_crisis": crisis,
        "bw_summary": summary,
        "bw_cache": {"hit": False},
    }
    set_cached_reputation(cache_key, result)
    return result
