"""
routes.py — Flask Blueprint: toàn bộ API endpoints.
"""
import json
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template

from .job import scrape_status, run_scrape_job, emit_log
from .agent import run_daily_report
from .storage import get_today_stats

AGENTS_MD = Path("AGENTS.md")

# ✅ Blueprint khai báo TRƯỚC @api.route(...)
api = Blueprint("api", __name__)


# ── Giao diện ────────────────────────────────────────────────────────────────

@api.route("/")
def index():
    return render_template("index.html")


# ── Scraper ───────────────────────────────────────────────────────────────────

@api.route("/api/status")
def get_status():
    """Trạng thái hiện tại của tiến trình quét."""
    return jsonify(scrape_status)


@api.route("/api/run", methods=["POST"])
def run_scraper():
    """Bắt đầu thu thập dữ liệu Facebook."""
    if scrape_status["running"]:
        return jsonify({"success": False, "message": "Tiến trình đang chạy, vui lòng đợi..."}), 400

    config = request.json
    if not config:
        return jsonify({"success": False, "message": "Thiếu dữ liệu cấu hình"}), 400

    required = ["cookie", "groups", "keywords", "sheets_id", "sheets_creds"]
    missing = [f for f in required if not config.get(f)]
    if missing:
        return jsonify({"success": False, "message": f"Thiếu các trường: {', '.join(missing)}"}), 400

    scrape_status.update({
        "running": True, "progress": 0, "total": len(config["groups"]),
        "current_group": "", "posts_collected": 0, "errors": [], "log": [],
    })
    threading.Thread(target=run_scrape_job, args=(config,), daemon=True).start()
    return jsonify({"success": True, "message": "Đã bắt đầu thu thập dữ liệu Facebook..."})


@api.route("/api/stop", methods=["POST"])
def stop_scraper():
    """Dừng tiến trình quét đang chạy."""
    if not scrape_status["running"]:
        return jsonify({"success": False, "message": "Không có tiến trình nào đang chạy"})
    scrape_status["running"] = False
    emit_log("⏹ Đang dừng tiến trình quét...", "warning")
    return jsonify({"success": True, "message": "Đang tiến hành dừng quét..."})


# ── Agent / Báo cáo ──────────────────────────────────────────────────────────

@api.route("/api/report", methods=["POST"])
def generate_report():
    """Trigger Deep Agent phân tích và gửi báo cáo lên Telegram channel.

    Body JSON (tùy chọn):
      { "keyword": "BA" }  → chỉ tổng hợp vị trí/từ khóa đó
      {}                   → báo cáo tổng hợp toàn bộ như cũ
    """
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "Chưa có config.json — hãy lưu cấu hình trước"}), 400

    data = request.json or {}
    keyword = data.get("keyword") or None  # None nếu rỗng hoặc không truyền

    threading.Thread(target=run_daily_report, args=(config, keyword), daemon=True).start()
    msg = f"Agent đang tổng hợp vị trí '{keyword}'..." if keyword else "Agent đang phân tích và gửi báo cáo..."
    return jsonify({"success": True, "message": msg})


@api.route("/api/stats")
def stats():
    """Thống kê nhanh từ SQLite."""
    return jsonify(get_today_stats())


# ── Agent Memory ─────────────────────────────────────────────────────────────

@api.route("/api/agent/memory", methods=["GET"])
def get_memory():
    """Đọc nội dung AGENTS.md."""
    if not AGENTS_MD.exists():
        return jsonify({"content": ""})
    try:
        return jsonify({"content": AGENTS_MD.read_text(encoding="utf-8")})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/api/agent/memory", methods=["POST"])
def save_memory():
    """Ghi đè nội dung AGENTS.md."""
    data = request.json or {}
    try:
        AGENTS_MD.write_text(data.get("content", ""), encoding="utf-8")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ── Config ────────────────────────────────────────────────────────────────────

@api.route("/api/config/save", methods=["POST"])
def save_config():
    """Lưu cấu hình vào config.json."""
    config = request.json
    try:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/api/config/load")
def load_config():
    """Đọc config.json."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({})
