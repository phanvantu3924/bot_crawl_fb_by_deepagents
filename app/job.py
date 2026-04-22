"""
job.py — Background job thu thập dữ liệu từ Facebook Pages/Groups.

Hỗ trợ config mới:
  pages: [{url, name, topics}]   — pages với topics riêng
  groups: [url, url, ...]        — backward compat (dùng global keywords)
"""
import logging
from datetime import datetime
from typing import List

from .scraper import FacebookScraper
from .sheets import GoogleSheetsManager, get_current_sheet_name
from .storage import save_raw_posts, upsert_posts

logger = logging.getLogger(__name__)

scrape_status = {
    "running":         False,
    "progress":        0,
    "total":           0,
    "current_source":  "",
    "posts_collected": 0,
    "errors":          [],
    "last_run":        None,
    "log":             [],
}


def emit_log(msg: str, level: str = "info"):
    """Ghi log ra console và đẩy về giao diện Web."""
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level}
    scrape_status["log"].append(entry)
    if len(scrape_status["log"]) > 200:
        scrape_status["log"] = scrape_status["log"][-200:]
    getattr(logger, level)(msg)


def _get_sources(config: dict) -> List[dict]:
    """
    Chuẩn hóa danh sách nguồn cần scrape từ config.
    Hỗ trợ cả format mới (pages) và cũ (groups/keywords).

    Returns:
        List of {url, name, keywords} dicts.
    """
    sources = []
    global_keywords = config.get("keywords") or []

    # Format mới: pages với topics per-page
    for pc in config.get("pages") or []:
        url  = pc.get("url", "").strip()
        name = pc.get("name", url)
        # Merge page topics + global topics
        topics = list({
            *(pc.get("topics") or []),
            *(config.get("global_topics") or []),
        })
        if url:
            sources.append({"url": url, "name": name, "keywords": topics or global_keywords})

    # Backward compat: groups list
    groups_raw = config.get("groups") or ""
    if isinstance(groups_raw, str):
        group_urls = [u.strip() for u in groups_raw.split("\n") if u.strip()]
    else:
        group_urls = [u for u in groups_raw if u]

    for url in group_urls:
        sources.append({"url": url, "name": url.rstrip("/").split("/")[-1], "keywords": global_keywords})

    return sources


def run_scrape_job(config: dict):
    """Tiến trình chính: quét FB Pages/Groups → JSON local → SQLite → Google Sheets."""
    try:
        sources = _get_sources(config)
        if not sources:
            emit_log("⚠️ Không có URL nào để scrape. Kiểm tra lại config.", "warning")
            return

        emit_log(f"🚀 Bắt đầu thu thập: {len(sources)} nguồn")

        # ── Google Sheets ──────────────────────────────────────────────────────
        sheets = None
        if config.get("sheets_id") and config.get("sheets_creds"):
            try:
                emit_log("📊 Kết nối Google Sheets...")
                sheets = GoogleSheetsManager(
                    credentials_json=config["sheets_creds"],
                    spreadsheet_id=config["sheets_id"],
                )
                sheets.ensure_sheet_exists()
                emit_log(f"✅ Sheets OK (tab: {get_current_sheet_name()})")
            except Exception as e:
                emit_log(f"⚠️ Sheets lỗi: {e} — bỏ qua Sheets", "warning")

        # ── Khởi động Chrome ───────────────────────────────────────────────────
        emit_log("🌐 Khởi động Chrome...")
        scraper = FacebookScraper(
            cookie_string=config["cookie"],
            headless=config.get("headless", True),
        )

        total_new = 0
        scrape_status["total"] = len(sources)

        for i, src in enumerate(sources):
            if not scrape_status["running"]:
                emit_log("⏹ Dừng theo yêu cầu", "warning")
                break

            scrape_status.update({"current_source": src["name"], "progress": i})
            emit_log(f"🔍 [{i+1}/{len(sources)}] {src['name']} — {src['url']}")
            emit_log(f"   Keywords: {', '.join(src['keywords']) or '(tất cả)'}")

            try:
                posts = scraper.scrape(
                    url       = src["url"],
                    keywords  = src["keywords"] or None,
                    max_posts = int(config.get("max_posts", 50)),
                    days_back = int(config.get("days_back", 1)),
                )

                if not posts:
                    emit_log(f"⚠️ Không có bài từ {src['name']}", "warning")
                    continue

                dicts = [p.to_dict() if hasattr(p, "to_dict") else p for p in posts]

                raw_new = save_raw_posts(dicts)
                db_new  = upsert_posts(dicts)
                sheets_new = 0
                if sheets:
                    try:
                        sheets_new = sheets.append_posts(posts)
                    except Exception as se:
                        emit_log(f"⚠️ Sheets append lỗi: {se}", "warning")

                total_new += raw_new
                scrape_status["posts_collected"] = total_new

                if raw_new > 0:
                    emit_log(
                        f"✅ {src['name']}: +{raw_new} bài mới "
                        f"(JSON +{raw_new} | SQLite +{db_new} | Sheets +{sheets_new})"
                    )
                else:
                    emit_log(f"ℹ️ {src['name']}: không có bài mới")

            except Exception as e:
                err = f"❌ Lỗi {src['name']}: {e}"
                emit_log(err, "error")
                scrape_status["errors"].append(err)

        scraper.close()
        scrape_status["progress"] = len(sources)
        scrape_status["last_run"] = datetime.now().isoformat()
        emit_log(f"🎉 Hoàn thành! Tổng {total_new} bài mới đã lưu")

    except Exception as e:
        emit_log(f"💥 Lỗi nghiêm trọng: {e}", "error")
        scrape_status["errors"].append(str(e))
    finally:
        scrape_status["running"] = False
