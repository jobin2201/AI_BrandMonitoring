from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator


_CHECKPOINT_LOCK = threading.RLock()
DEFAULT_CHECKPOINT_WAIT_SECONDS = 60.0


@contextmanager
def monitor_checkpoint(source: str = "") -> Iterator[None]:
    with _CHECKPOINT_LOCK:
        yield


def wait_for_monitor_checkpoint_idle(timeout_seconds: float | None = None) -> bool:
    if timeout_seconds is None:
        timeout_seconds = float(
            os.getenv(
                "PRIORITY_CHECKPOINT_WAIT_TIMEOUT_SECONDS",
                str(DEFAULT_CHECKPOINT_WAIT_SECONDS),
            )
        )

    acquired = _CHECKPOINT_LOCK.acquire(timeout=timeout_seconds)
    if not acquired:
        print(
            "[PRIORITY] Monitoring checkpoint did not become idle within "
            f"{timeout_seconds}s; high-priority task will continue."
        )
        return False

    try:
        return True
    finally:
        _CHECKPOINT_LOCK.release()
