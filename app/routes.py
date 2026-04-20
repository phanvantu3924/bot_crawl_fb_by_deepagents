"""
routes.py — Flask Blueprint: toàn bộ API endpoints + Dashboard.

Endpoints mới (so với bản gốc):
  GET  /api/dashboard/data     — Dữ liệu tổng hợp cho Dashboard
  GET  /api/posts              — Danh sách bài viết với filters
  GET  /api/posts/pages        — Danh sách pages đã có
  GET  /api/report/file        — Tải file báo cáo Markdown mới nhất
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, render_template, send_file

from .job import scrape_status, run_scrape_job, emit_log
from .agent import run_daily_report
from .storage import (
    get_today_stats,
    get_posts_for_dashboard,
    get_posts_by_day,
    get_distinct_pages,
)

AGENTS_MD   = Path("AGENTS.md")
REPORTS_DIR = Path("data/reports")

api = Blueprint("api", __name__)


# ── Giao diện ─────────────────────────────────────────────────────────────────

@api.route("/")
def index():
    return render_template("index.html")


# ── Scraper ───────────────────────────────────────────────────────────────────

@api.route("/api/status")
def get_status():
    return jsonify(scrape_status)


@api.route("/api/run", methods=["POST"])
def run_scraper():
    """Bắt đầu thu thập dữ liệu Facebook."""
    if scrape_status["running"]:
        return jsonify({"success": False, "message": "Tiến trình đang chạy, vui lòng đợi..."}), 400

    config = request.json
    if not config:
        return jsonify({"success": False, "message": "Thiếu dữ liệu cấu hình"}), 400

    # Kiểm tra có ít nhất 1 nguồn
    has_pages  = bool(config.get("pages"))
    has_groups = bool(config.get("groups"))
    if not has_pages and not has_groups:
        return jsonify({"success": False, "message": "Cần ít nhất 1 Page hoặc Group URL trong config"}), 400

    source_count = len(config.get("pages") or []) + len((config.get("groups") or "").split("\n"))
    scrape_status.update({
        "running": True, "progress": 0, "total": source_count,
        "current_source": "", "posts_collected": 0, "errors": [], "log": [],
    })
    threading.Thread(target=run_scrape_job, args=(config,), daemon=True).start()
    return jsonify({"success": True, "message": "Đã bắt đầu thu thập dữ liệu Facebook..."})


@api.route("/api/stop", methods=["POST"])
def stop_scraper():
    if not scrape_status["running"]:
        return jsonify({"success": False, "message": "Không có tiến trình nào đang chạy"})
    scrape_status["running"] = False
    emit_log("⏹ Đang dừng...", "warning")
    return jsonify({"success": True, "message": "Đang dừng..."})


# ── Agent / Báo cáo ───────────────────────────────────────────────────────────

@api.route("/api/report", methods=["POST"])
def generate_report():
    """
    Trigger pipeline: Analyzer sub-agent → Reporter sub-agent → Telegram.

    Body JSON (tùy chọn):
      { "keyword": "QA" }  → chỉ tổng hợp bài chứa từ khóa này
      {}                   → báo cáo toàn bộ
    """
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "Chưa có config.json"}), 400

    data    = request.json or {}
    keyword = data.get("keyword") or None

    threading.Thread(target=run_daily_report, args=(config, keyword), daemon=True).start()
    msg = f"Agent đang tổng hợp '{keyword}'..." if keyword else "Agent đang phân tích và gửi báo cáo..."
    return jsonify({"success": True, "message": msg})


@api.route("/api/stats")
def stats():
    return jsonify(get_today_stats())


# ── Dashboard ─────────────────────────────────────────────────────────────────

@api.route("/api/dashboard/data")
def dashboard_data():
    """Dữ liệu tổng hợp cho Dashboard widget."""
    today_stats = get_today_stats()
    posts_by_day = get_posts_by_day(days=7)
    pages = get_distinct_pages()

    return jsonify({
        "today": today_stats,
        "posts_by_day": posts_by_day,
        "pages": pages,
        "generated_at": datetime.now().isoformat(),
    })


@api.route("/api/posts")
def get_posts():
    """
    Danh sách bài viết với filters.

    Query params:
      date         YYYY-MM-DD, mặc định hôm nay
      page         tên page/group (partial match)
      topic        chủ đề đã match
      relevant     1 = chỉ lấy bài liên quan
      limit        max số bài (mặc định 100)
    """
    date_str      = request.args.get("date")
    page_name     = request.args.get("page")
    topic         = request.args.get("topic")
    relevant_only = request.args.get("relevant") == "1"
    limit         = int(request.args.get("limit", 100))

    posts = get_posts_for_dashboard(
        date_str=date_str,
        page_name=page_name,
        topic=topic,
        relevant_only=relevant_only,
        limit=limit,
    )
    return jsonify({"posts": posts, "count": len(posts)})


@api.route("/api/posts/pages")
def get_pages():
    """Danh sách tên page/group đã có trong DB."""
    return jsonify({"pages": get_distinct_pages()})


# ── Report file download ──────────────────────────────────────────────────────

@api.route("/api/report/file")
def get_report_file():
    """Tải báo cáo Markdown mới nhất."""
    date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"{date_str}.md"
    if not path.exists():
        return jsonify({"success": False, "message": f"Chưa có báo cáo ngày {date_str}"}), 404
    return send_file(str(path.absolute()), as_attachment=True, download_name=f"report_{date_str}.md")


# ── Agent Memory ──────────────────────────────────────────────────────────────

@api.route("/api/agent/memory", methods=["GET"])
def get_memory():
    if not AGENTS_MD.exists():
        return jsonify({"content": ""})
    try:
        return jsonify({"content": AGENTS_MD.read_text(encoding="utf-8")})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/api/agent/memory", methods=["POST"])
def save_memory():
    data = request.json or {}
    try:
        AGENTS_MD.write_text(data.get("content", ""), encoding="utf-8")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ── Config ────────────────────────────────────────────────────────────────────

@api.route("/api/config/save", methods=["POST"])
def save_config():
    config = request.json
    try:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/api/config/load")
def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({})
