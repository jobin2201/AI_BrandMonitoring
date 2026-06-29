from __future__ import annotations

import threading
import time
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.utils.time_utils import now_ist
from app.services.monitor_priority_gate import wait_for_monitor_checkpoint_idle


_LOCK = threading.RLock()
_PAUSE_COUNT = 0
_REASON = ""
_CANCEL_REQUESTED = False
_COOLDOWN_UNTIL = 0.0
_LOG_PATH = (
    Path(__file__).resolve().parents[3]
    / "logs"
    / "competitor_analysis"
    / "scheduler_pause"
    / "pause.log"
)


def _log(message: str) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"{now_ist()} {message}\n")
    except Exception as exc:
        print(f"[COMPETITOR][SCHEDULER_PAUSE] log failed: {exc}")


def pause_scheduler(reason: str = "competitor_intelligence") -> None:
    global _PAUSE_COUNT, _REASON, _CANCEL_REQUESTED
    with _LOCK:
        _PAUSE_COUNT += 1
        _REASON = reason
        _CANCEL_REQUESTED = True
        _log(f"PAUSE count={_PAUSE_COUNT} reason={reason}")


def resume_scheduler(reason: str = "competitor_intelligence") -> None:
    global _PAUSE_COUNT, _REASON, _COOLDOWN_UNTIL
    with _LOCK:
        _PAUSE_COUNT = max(0, _PAUSE_COUNT - 1)
        if _PAUSE_COUNT == 0:
            _REASON = ""
            cooldown_seconds = float(os.getenv("COMPETITOR_MONITOR_RESUME_COOLDOWN_SECONDS", "120"))
            _COOLDOWN_UNTIL = max(_COOLDOWN_UNTIL, time.monotonic() + cooldown_seconds)
        _log(f"RESUME count={_PAUSE_COUNT} reason={reason}")


def is_scheduler_paused() -> bool:
    with _LOCK:
        return _PAUSE_COUNT > 0 or time.monotonic() < _COOLDOWN_UNTIL


def should_cancel_monitoring() -> bool:
    global _CANCEL_REQUESTED
    with _LOCK:
        if _PAUSE_COUNT > 0:
            return True
        if _CANCEL_REQUESTED:
            _CANCEL_REQUESTED = False
            _log("MONITOR_CANCEL_CONSUMED")
            return True
        return False


def pause_status() -> dict:
    with _LOCK:
        cooldown_remaining = max(0.0, _COOLDOWN_UNTIL - time.monotonic())
        return {
            "paused": _PAUSE_COUNT > 0 or cooldown_remaining > 0,
            "count": _PAUSE_COUNT,
            "reason": _REASON,
            "cancel_requested": _CANCEL_REQUESTED,
            "cooldown_remaining_seconds": round(cooldown_remaining, 2),
            "source": "competitor_intelligence",
        }


@contextmanager
def scheduler_pause(reason: str = "competitor_intelligence") -> Iterator[None]:
    started = time.perf_counter()
    pause_scheduler(reason)
    try:
        wait_for_monitor_checkpoint_idle()
        _log(f"CHECKPOINT_IDLE reason={reason}")
        yield
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        _log(f"COMPLETE reason={reason} duration_ms={duration_ms}")
        resume_scheduler(reason)
