"""
storage.py — Lưu trữ hai tầng:
  - data/raw/YYYY-MM-DD.json : dữ liệu thô (agent grep/compact)
  - data/bot.db (SQLite)     : bài đã xử lý, deduplicate

Pre-processing pipeline:
  raw_posts_as_text() giới hạn token và loại bỏ noise trước khi truyền vào LLM.
  Giới hạn: tối đa MAX_POSTS_PER_LLM bài, mỗi bài MAX_CHARS_PER_POST ký tự.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Giới hạn context cho LLM ──────────────────────────────────────────────────
MAX_POSTS_PER_LLM  = 80    # Tối đa bao nhiêu bài gửi vào 1 lần gọi LLM
MAX_CHARS_PER_POST = 300   # Mỗi bài cắt sau N ký tự (tránh bài spam dài)
_NOISE_RE = re.compile(       # Strip emoji clusters, whitespace thừa
    r"[\U0001F600-\U0001FFFF]{3,}|[\s]{3,}", re.UNICODE
)

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/bot.db")


# ══════════════════════════════════════════════════════════════════════════════
# JSON RAW STORE
# ══════════════════════════════════════════════════════════════════════════════

def _raw_path(date_str: Optional[str] = None) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return RAW_DIR / f"{date_str}.json"


def save_raw_posts(posts: list[dict]) -> int:
    """
    Thêm bài mới vào JSON ngày hôm nay.
    Trả về số bài thực sự được ghi (bỏ qua trùng post_id).
    """
    path = _raw_path()
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_ids = {p.get("post_id") for p in existing}
    new_posts = [p for p in posts if p.get("post_id") not in existing_ids]

    if new_posts:
        existing.extend(new_posts)
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    logger.info(f"📄 JSON raw: +{len(new_posts)} bài (bỏ {len(posts) - len(new_posts)} trùng)")
    return len(new_posts)


def load_raw_posts(date_str: Optional[str] = None) -> list[dict]:
    """Đọc toàn bộ bài thô của một ngày."""
    path = _raw_path(date_str)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _clean_post_text(text: str, max_chars: int = MAX_CHARS_PER_POST) -> str:
    """Làm sạch nội dung post: bỏ noise, cắt theo giới hạn ký tự."""
    if not text:
        return ""
    text = _NOISE_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        # Cắt ở ranh giới từ gần nhất để không bị vỡ giữa câu
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def raw_posts_as_text(
    date_str: Optional[str] = None,
    keyword: Optional[str] = None,
) -> str:
    """
    Trả về chuỗi VĂN BẢN CÓ CẤU TRÚC để LLM phân tích — đã tiền xử lý.

    Pipeline:
    1. Load bài thô từ JSON
    2. Lọc theo keyword (nếu có)
    3. Làm sạch text (bỏ noise, emoji cluster thừa)
    4. Giới hạn MAX_POSTS_PER_LLM bài để tránh ngốn token
    5. Format thành block có cấu trúc rõ ràng cho LLM

    LLM CHỈ được phép dùng dữ liệu trong block <posts> này.
    """
    posts = load_raw_posts(date_str)
    if not posts:
        return "<posts>\nKHÔNG CÓ BÀI VIẾT NÀO.\n</posts>"

    if keyword:
        # Sử dụng Regex để khớp từ khóa chính xác (Whole word match)
        # Pattern này đảm bảo phía trước và phía sau từ khóa không phải là chữ hoặc số
        pattern = rf"(?i)(?<![\w\d]){re.escape(keyword)}(?![\w\d])"
        posts = [p for p in posts if re.search(pattern, p.get("content") or "")]
        
        if not posts:
            return f"<posts>\nKHÔNG CÓ BÀI NÀO KHỚP CHÍNH XÁC TỪ KHÓA '{keyword.upper()}'.\n</posts>"

    label     = date_str or datetime.now().strftime("%Y-%m-%d")
    total_raw = len(posts)

    # Giới hạn số bài truyền vào LLM
    truncated = total_raw > MAX_POSTS_PER_LLM
    posts     = posts[:MAX_POSTS_PER_LLM]

    lines = []
    for i, p in enumerate(posts, 1):
        group   = p.get("group_name", "?") or "?"
        author  = p.get("author", "?") or "?"
        content = _clean_post_text(p.get("content") or "")
        kws     = ", ".join(p.get("keywords_matched") or []) or "—"
        lines.append(
            f"[{i}] Nhóm: {group} | Tác giả: {author}\n"
            f"    Từ khóa khớp: {kws}\n"
            f"    Nội dung: {content}"
        )

    header = (
        f"<posts date='{label}' total='{total_raw}' shown='{len(posts)}'"
        f" keyword='{keyword or 'tất cả'}'>"
    )
    if truncated:
        header += f"\n<!-- Chỉ hiển thị {MAX_POSTS_PER_LLM}/{total_raw} bài do giới hạn token -->"

    return header + "\n\n" + "\n\n".join(lines) + "\n</posts>"


# ══════════════════════════════════════════════════════════════════════════════
# SQLITE STORE
# ══════════════════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Tạo schema nếu chưa tồn tại."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id      TEXT    UNIQUE NOT NULL,
                group_name   TEXT,
                group_url    TEXT,
                author       TEXT,
                content      TEXT,
                post_url     TEXT,
                timestamp    TEXT,
                likes        INTEGER DEFAULT 0,
                comments     INTEGER DEFAULT 0,
                shares       INTEGER DEFAULT 0,
                keywords     TEXT,
                collected_at TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT NOT NULL,
                summary       TEXT,
                sent_at       TEXT,
                tg_message_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_posts_date    ON posts(collected_at);
            CREATE INDEX IF NOT EXISTS idx_reports_date  ON reports(date);
        """)
    logger.info("✅ SQLite schema OK")


def upsert_posts(posts: list[dict]) -> int:
    """
    Chèn bài vào SQLite, bỏ qua nếu post_id đã tồn tại.
    Trả về số bài được chèn mới.
    """
    if not posts:
        return 0

    now = datetime.now().isoformat()
    inserted = 0

    with _get_conn() as conn:
        for p in posts:
            cur = conn.execute(
                """INSERT OR IGNORE INTO posts
                   (post_id, group_name, group_url, author, content,
                    post_url, timestamp, likes, comments, shares, keywords, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    (p.get("post_id") or "")[:200],
                    p.get("group_name", ""),
                    p.get("group_url", ""),
                    p.get("author", ""),
                    (p.get("content") or "")[:2000],
                    p.get("post_url", ""),
                    p.get("timestamp", ""),
                    p.get("likes", 0),
                    p.get("comments", 0),
                    p.get("shares", 0),
                    ", ".join(p["keywords_matched"])
                    if isinstance(p.get("keywords_matched"), list)
                    else "",
                    now,
                ),
            )
            if cur.rowcount:   # ✅ rowcount đáng tin hơn SELECT changes()
                inserted += 1

    logger.info(f"💾 SQLite: +{inserted} bài (bỏ {len(posts) - inserted} trùng)")
    return inserted


def save_report(summary: str, tg_message_id: str = "") -> int:
    """Lưu báo cáo đã gửi vào SQLite. Trả về row id."""
    now = datetime.now()
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reports (date, summary, sent_at, tg_message_id) VALUES (?,?,?,?)",
            (now.strftime("%Y-%m-%d"), summary, now.isoformat(), tg_message_id),
        )
        return cur.lastrowid


def get_today_stats() -> dict:
    """Thống kê nhanh cho ngày hôm nay."""
    today = datetime.now().strftime("%Y-%m-%d")
    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE collected_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        last = conn.execute(
            "SELECT sent_at FROM reports WHERE date=? ORDER BY id DESC LIMIT 1", (today,)
        ).fetchone()
    return {
        "total_posts_today": total,
        "last_report_at": last[0] if last else None,
    }
