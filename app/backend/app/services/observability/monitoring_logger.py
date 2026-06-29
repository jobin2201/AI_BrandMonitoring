from __future__ import annotations

import json
from pathlib import Path

from app.services.observability.entity_trace_logger import json_safe
from app.utils.time_utils import now_ist

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MONITORING_ROOT = BACKEND_ROOT / "logs" / "monitoring"
SOURCE_RUNS_DIR = MONITORING_ROOT / "source_runs"
FILTERING_DIR = MONITORING_ROOT / "filtering"
DEDUPLICATION_DIR = MONITORING_ROOT / "deduplication"
STORAGE_DIR = MONITORING_ROOT / "storage"
SCHEDULER_DIR = MONITORING_ROOT / "scheduler"
METRICS_DIR = BACKEND_ROOT / "logs" / "metrics"

for directory in [
    SOURCE_RUNS_DIR,
    FILTERING_DIR,
    DEDUPLICATION_DIR,
    STORAGE_DIR,
    SCHEDULER_DIR,
    METRICS_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(json_safe(payload), f, indent=2)
    return str(path)


def log_source_run(request_id: int, source: str, payload: dict):
    path = SOURCE_RUNS_DIR / source / f"run_{request_id}.json"
    return write_json(path, {
        **payload,
        "request_id": str(request_id),
        "source": source,
        "timestamp": now_ist(),
    })


def load_source_run(request_id: int, source: str) -> dict:
    path = SOURCE_RUNS_DIR / source / f"run_{request_id}.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def log_filter_run(request_id: int, source: str, payload: dict):
    path = FILTERING_DIR / f"filter_{request_id}_{source}.json"
    return write_json(path, {
        **payload,
        "request_id": str(request_id),
        "source": source,
        "timestamp": now_ist(),
    })


def log_dedupe_run(request_id: int, source: str, payload: dict):
    path = DEDUPLICATION_DIR / f"dedupe_{request_id}_{source}.json"
    return write_json(path, {
        **payload,
        "request_id": str(request_id),
        "source": source,
        "timestamp": now_ist(),
    })


def log_storage_run(request_id: int, payload: dict):
    path = STORAGE_DIR / f"store_{request_id}.json"
    return write_json(path, {
        **payload,
        "request_id": str(request_id),
        "timestamp": now_ist(),
    })


def append_scheduler_log(message: str):
    path = SCHEDULER_DIR / "scheduler.log"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{now_ist()} {message}\n")
    return str(path)


def print_monitor_summary(brand: str, request_id: int, summary: dict):
    print("\n=================================================")
    print("MONITOR RUN")
    print(f"Brand: {brand}")
    print(f"Request: {request_id}")
    print("=================================================\n")

    entity = summary.get("entity_resolution") or {}
    print("ENTITY RESOLUTION")
    print(f"{'✓' if entity.get('ok', True) else '✗'} {entity.get('source', 'profile loaded')}")
    print("")

    labels = {
        "newsapi": "NEWSAPI",
        "google_news": "GOOGLE NEWS",
        "reddit": "REDDIT",
        "youtube": "YOUTUBE",
    }
    for source, label in labels.items():
        data = summary.get("sources", {}).get(source, {})
        raw = data.get("raw_found", data.get("raw_items", 0))
        accepted = data.get("accepted", 0)
        duration = data.get("duration_seconds")
        print(label)
        print(f"{'✓' if data.get('called', True) else '✗'} Raw found: {raw}")
        print(f"{'✓' if accepted else '✗'} Accepted: {accepted}")
        if duration is not None:
            print(f"Duration: {duration}s")
        reasons = data.get("discard_reasons") or {}
        if reasons:
            print("Reason:")
            for reason, count in reasons.items():
                print(f"  {reason:<18}: {count}")
        error = data.get("error")
        if error:
            print(f"Error: {error}")
        print("")

    storage = summary.get("storage") or {}
    print("STORAGE")
    print(f"✓ Saved: {storage.get('saved', 0)} mentions")
    if storage.get("duration_seconds") is not None:
        print(f"Duration: {storage.get('duration_seconds')}s")
    if storage.get("duplicates"):
        print(f"Duplicates skipped: {storage.get('duplicates')}")

    print("\n=================================================")
    print("RUN COMPLETE")
    print("=================================================\n")
