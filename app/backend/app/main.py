import asyncio
import os
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from app.api.routes.articles import router as articles_router
from app.api.reddit.reddit_scraper import router as reddit_router
from app.api.youtube.youtube_scraper import router as youtube_router
from app.api.google_news.google_news_scraper import router as google_news_router
from app.api.routes.monitors import router as monitors_router
from app.api.routes.competitors import router as competitors_router
from app.api.routes.reputation import router as reputation_router
from app.api.routes.bw_workspace import router as bw_workspace_router
from app.services.monitor_service import MONITOR_INTERVAL_MINUTES, run_monitoring_cycle
from app.services.entity_resolution.entity_detector import get_gliner_model
from app.services.entity_resolution.llm_entity_resolver import print_groq_limits
from app.services.competitor_intelligence.scheduler_pause import (
    is_scheduler_paused as is_competitor_scheduler_paused,
    pause_status as competitor_pause_status,
)
from app.services.reputation_signals.scheduler_pause import (
    is_scheduler_paused as is_reputation_scheduler_paused,
    pause_status as reputation_pause_status,
)

app = FastAPI(title="Brand Monitoring API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles_router, prefix="/api")
app.include_router(reddit_router, prefix="/api/reddit")
app.include_router(youtube_router, prefix="/api/youtube")
app.include_router(google_news_router, prefix="/api", tags=["google-news"])
app.include_router(monitors_router, prefix="/api/monitors", tags=["monitors"])
app.include_router(competitors_router, prefix="/api/competitors", tags=["Competitors"])
app.include_router(reputation_router, prefix="/api/reputation", tags=["Reputation Signals"])
app.include_router(bw_workspace_router, prefix="/api/bw", tags=["BW Workspace"])

scheduler = BackgroundScheduler()


def _env_enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def automatic_monitoring_enabled() -> bool:
    return all([
        _env_enabled("ENABLE_SCHEDULER"),
        _env_enabled("MONITORING_SCHEDULER_ENABLED"),
        _env_enabled("AUTO_MONITORING_ENABLED"),
    ])


def scheduled_monitoring_cycle():
    if is_competitor_scheduler_paused() or is_reputation_scheduler_paused():
        print(
            "[SCHEDULER] Paused - skipping cycle. "
            f"competitor={competitor_pause_status()} "
            f"reputation={reputation_pause_status()}"
        )
        return
    return run_monitoring_cycle()


@app.on_event("startup")
def start_scheduler():
    get_gliner_model()
    print_groq_limits()
    if not automatic_monitoring_enabled():
        print(
            "[SCHEDULER] Automatic brand monitoring disabled by env. "
            "Manual/live monitor runs are still available."
        )
        return
    scheduler.add_job(
        scheduled_monitoring_cycle,
        trigger="interval",
        minutes=MONITOR_INTERVAL_MINUTES,
        id="brand_monitor",
        replace_existing=True,
    )
    scheduler.start()
    print(f"Brand monitoring scheduler started (every {MONITOR_INTERVAL_MINUTES} min)")


@app.on_event("shutdown")
def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()


@app.get("/")
def home():
    return {"message": "Brand Monitoring API Running"}
