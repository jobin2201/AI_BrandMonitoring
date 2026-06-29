from __future__ import annotations

import time
import traceback

from fastapi import APIRouter, HTTPException

from app.services.reputation_signals.reputation_engine import (
    _empty_reputation_result,
    run_brand_reputation_analysis,
)
from app.services.reputation_signals.scheduler_pause import scheduler_pause


router = APIRouter()


@router.post("/signals/{brand_id}")
def generate_reputation_signals(brand_id: str):
    started = time.perf_counter()
    print(f"[REPUTATION][API] START /signals/{brand_id}")
    try:
        with scheduler_pause("reputation_signals"):
            result = run_brand_reputation_analysis(brand_id)
            print(
                f"[REPUTATION][API] DONE /signals/{brand_id} "
                f"duration={round(time.perf_counter() - started, 2)}s "
                f"error={bool(result.get('error')) if isinstance(result, dict) else False}"
            )
            return result
    except LookupError as exc:
        print(f"[REPUTATION][API] NOT_FOUND /signals/{brand_id}: {exc}")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        print(
            f"[REPUTATION][API] ERROR /signals/{brand_id} "
            f"duration={round(time.perf_counter() - started, 2)}s error={exc}"
        )
        return _empty_reputation_result(
            brand_id,
            {},
            f"Reputation signals failed: {exc}",
            traceback.format_exc(),
        )
