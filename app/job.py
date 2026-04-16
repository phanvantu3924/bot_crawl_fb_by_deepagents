"""
job.py — Tiến trình thu thập dữ liệu chạy trong background thread.
Lưu song song: JSON local → SQLite → Google Sheets.
"""
import logging
from datetime import datetime

from .scraper import FacebookScraper
from .sheets import GoogleSheetsManager, get_current_sheet_name
from .storage import save_raw_posts, upsert_posts

logger = logging.getLogger(__name__)

scrape_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_group": "",
    "posts_collected": 0,
    "errors": [],
    "last_run": None,
    "log": [],
}


def emit_log(msg: str, level: str = "info"):
    """Ghi log ra console và đẩy về giao diện Web."""
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level}
    scrape_status["log"].append(entry)
    if len(scrape_status["log"]) > 200:
        scrape_status["log"] = scrape_status["log"][-200:]
    getattr(logger, level)(msg)


def run_scrape_job(config: dict):
    """Tiến trình chính: quét FB → JSON local → SQLite → Google Sheets."""
    try:
        emit_log("🚀 Bắt đầu phiên thu thập dữ liệu")
        emit_log(f"📋 {len(config['groups'])} nhóm | Từ khóa: {', '.join(config['keywords'])}")

        # ── Google Sheets ─────────────────────────────────────────────────────
        emit_log("📊 Kết nối Google Sheets...")
        sheets = GoogleSheetsManager(
            credentials_json=config["sheets_creds"],
            spreadsheet_id=config["sheets_id"],
        )
        sheets.ensure_sheet_exists()
        emit_log(f"✅ Sheets OK (tab: {get_current_sheet_name()})")

        # ── Trình duyệt ───────────────────────────────────────────────────────
        emit_log("🌐 Khởi động Chrome...")
        scraper = FacebookScraper(
            cookie_string=config["cookie"],
            headless=config.get("headless", True),
        )

        total_new = 0
        groups = config["groups"]
        scrape_status["total"] = len(groups)

        for i, group_url in enumerate(groups):
            if not scrape_status["running"]:
                emit_log("⏹ Dừng theo yêu cầu", "warning")
                break

            group_name = group_url.strip("/").split("/")[-1]
            scrape_status.update({"current_group": group_name, "progress": i})
            emit_log(f"🔍 [{i+1}/{len(groups)}] {group_name}")

            try:
                posts = scraper.scrape_group(
                    group_url=group_url,
                    keywords=config["keywords"],
                    max_posts=int(config.get("max_posts", 50)),
                    days_back=int(config.get("days_back", 1)),
                )

                if not posts:
                    emit_log(f"⚠️ Không có bài phù hợp từ {group_name}", "warning")
                    continue

                dicts = [p.to_dict() if hasattr(p, "to_dict") else p for p in posts]

                raw_new    = save_raw_posts(dicts)       # JSON local
                db_new     = upsert_posts(dicts)         # SQLite
                sheets_new = sheets.append_posts(posts)  # Google Sheets

                total_new += raw_new
                scrape_status["posts_collected"] = total_new

                if raw_new > 0:
                    emit_log(
                        f"✅ {group_name}: +{raw_new} bài mới "
                        f"(JSON +{raw_new} | SQLite +{db_new} | Sheets +{sheets_new})"
                    )
                else:
                    emit_log(f"ℹ️ {group_name}: không có bài mới")

            except Exception as e:
                err = f"❌ Lỗi {group_name}: {e}"
                emit_log(err, "error")
                scrape_status["errors"].append(err)

        scraper.close()
        scrape_status["progress"] = len(groups)
        scrape_status["last_run"] = datetime.now().isoformat()
        emit_log(f"🎉 Hoàn thành! {total_new} bài mới đã lưu")

    except Exception as e:
        emit_log(f"💥 Lỗi nghiêm trọng: {e}", "error")
        scrape_status["errors"].append(str(e))
    finally:
        scrape_status["running"] = False
