"""
main.py — Entry point: khởi động Flask server + APScheduler cron jobs.
"""
import json
import os

# ✅ Tạo thư mục TRƯỚC KHI logging.basicConfig ghi file
os.makedirs("logs", exist_ok=True)
os.makedirs("data/raw", exist_ok=True)

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
        logger.warning("⚠️  config.json chưa tồn tại — scheduler tạm dừng đến khi có cấu hình")
        return {}


def _scheduled_scrape():
    """Job thu thập dữ liệu tự động theo lịch."""
    config = _load_config()
    if not config:
        return
    from app.job import run_scrape_job, scrape_status
    if scrape_status["running"]:
        logger.info("⏰ Scheduler scrape: bỏ qua vì scraper đang chạy")
        return
    logger.info("⏰ Scheduler: bắt đầu thu thập dữ liệu tự động")
    run_scrape_job(config)


def _scheduled_report():
    """Job tạo báo cáo tự động theo lịch."""
    config = _load_config()
    if not config:
        return
    from app.agent import run_daily_report
    logger.info("⏰ Scheduler: bắt đầu tạo báo cáo tự động")
    run_daily_report(config)


def start_scheduler(cron_scrape: str, cron_report: str) -> BackgroundScheduler:
    """
    Khởi động APScheduler với 2 jobs độc lập.
    Mỗi job tự đọc lại config.json khi chạy nên cron mới có hiệu lực sau restart.
    """
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


# ── Bootstrap ─────────────────────────────────────────────────────────────────

init_db()
app = create_app()

_cfg = _load_config()
cron_scrape = _cfg.get("cron_scrape", "0 16 * * *")
cron_report = _cfg.get("cron_report", "10 16 * * *")

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scheduler = start_scheduler(cron_scrape, cron_report)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Flask đang chạy trên http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
