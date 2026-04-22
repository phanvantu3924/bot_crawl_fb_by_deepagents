"""
main.py — Entry point: Flask server + APScheduler cron jobs.
"""
import json
import os

os.makedirs("logs", exist_ok=True)
os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)
os.makedirs("data/reports", exist_ok=True)

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import create_app
from app.storage import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _load_config() -> dict:
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("⚠️  config.json chưa có — scheduler tạm dừng")
        return {}


def _scheduled_scrape():
    config = _load_config()
    if not config:
        return
    from app.job import run_scrape_job, scrape_status
    if scrape_status["running"]:
        logger.info("⏰ Scraper đang chạy — bỏ qua lịch này")
        return
    logger.info("⏰ Scheduler: bắt đầu thu thập")
    run_scrape_job(config)


def _scheduled_report():
    config = _load_config()
    if not config:
        return
    from app.agent import run_daily_report
    logger.info("⏰ Scheduler: bắt đầu tạo báo cáo")
    run_daily_report(config)


def start_scheduler(cron_scrape: str, cron_report: str) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(
        _scheduled_scrape,
        CronTrigger.from_crontab(cron_scrape),
        id="scrape_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _scheduled_report,
        CronTrigger.from_crontab(cron_report),
        id="report_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info(f"⏰ APScheduler OK | scrape: '{cron_scrape}' | report: '{cron_report}'")
    return scheduler


# ── Bootstrap ──────────────────────────────────────────────────────────────────

init_db()
app = create_app()

_cfg        = _load_config()
cron_scrape = _cfg.get("cron_scrape", "0 8 * * *")
cron_report = _cfg.get("cron_report", "30 8 * * *")

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scheduler = start_scheduler(cron_scrape, cron_report)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Flask đang chạy trên http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
