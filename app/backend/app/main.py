import asyncio
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
from app.services.monitor_service import MONITOR_INTERVAL_MINUTES, run_monitoring_cycle

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

scheduler = BackgroundScheduler()


@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(
        run_monitoring_cycle,
        trigger="interval",
        minutes=MONITOR_INTERVAL_MINUTES,
        id="brand_monitor",
        replace_existing=True,
    )
    scheduler.start()
    print(f"Brand monitoring scheduler started (every {MONITOR_INTERVAL_MINUTES} min)")


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown()


@app.get("/")
def home():
    return {"message": "Brand Monitoring API Running"}
