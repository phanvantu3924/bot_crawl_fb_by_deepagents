"""
storage.py — Lưu trữ hai tầng:
  - data/raw/YYYY-MM-DD.json : dữ liệu thô (scraper ghi vào)
  - data/bot.db (SQLite)     : bài đã xử lý + kết quả analysis

Thêm mới (so với bản gốc):
  - Cột relevance_label, relevance_level, topics_matched trong bảng posts
  - raw_posts_as_text() giữ nguyên để backward compat
  - upsert_posts_with_analysis() để lưu kết quả sub-agent analyzer
  - get_posts_for_dashboard() cho Dashboard API
"""
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# ── Giới hạn context LLM ──────────────────────────────────────────────────────
MAX_POSTS_PER_LLM  = 80
MAX_CHARS_PER_POST = 300

_NOISE_RE = re.compile(r"[\U0001F600-\U0001FFFF]{3,}|[\s]{3,}", re.UNICODE)

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/bot.db")


# ══════════════════════════════════════════════════════════════════════════════
# JSON RAW STORE
# ══════════════════════════════════════════════════════════════════════════════

def _raw_path(date_str: Optional[str] = None) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return RAW_DIR / f"{date_str}.json"


def save_raw_posts(posts: List[dict]) -> int:
    """Thêm bài mới vào JSON ngày hôm nay. Trả về số bài mới."""
    path = _raw_path()
    existing: List[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing_ids = {p.get("post_id") for p in existing}
    new_posts    = [p for p in posts if p.get("post_id") not in existing_ids]

    if new_posts:
        existing.extend(new_posts)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"📄 JSON raw: +{len(new_posts)} bài (bỏ {len(posts) - len(new_posts)} trùng)")
    return len(new_posts)


def load_raw_posts(date_str: Optional[str] = None) -> List[dict]:
    """Đọc toàn bộ bài thô của một ngày."""
    path = _raw_path(date_str)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _clean_post_text(text: str, max_chars: int = MAX_CHARS_PER_POST) -> str:
    if not text:
        return ""
    text = _NOISE_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def raw_posts_as_text(
    date_str: Optional[str] = None,
    keyword:  Optional[str] = None,
) -> str:
    """Trả về chuỗi text có cấu trúc để LLM phân tích."""
    posts = load_raw_posts(date_str)
    if not posts:
        return "<posts>\nKHÔNG CÓ BÀI VIẾT NÀO.\n</posts>"

    if keyword:
        pattern = rf"(?i)(?<![a-zA-Z]){re.escape(keyword)}(?![a-zA-Z])"
        posts   = [p for p in posts if re.search(pattern, p.get("content") or "")]
        if not posts:
            return f"<posts>\nKHÔNG CÓ BÀI NÀO KHỚP TỪ KHÓA '{keyword.upper()}'.\n</posts>"

    label     = date_str or datetime.now().strftime("%Y-%m-%d")
    total_raw = len(posts)
    truncated = total_raw > MAX_POSTS_PER_LLM
    posts     = posts[:MAX_POSTS_PER_LLM]

    lines = []
    for i, p in enumerate(posts, 1):
        content = _clean_post_text(p.get("content") or "")
        kws     = ", ".join(p.get("keywords_matched") or []) or "—"
        lines.append(
            f"[{i}] Nhóm: {p.get('group_name', '?')} | Tác giả: {p.get('author', '?')}\n"
            f"    Từ khóa khớp: {kws}\n"
            f"    Nội dung: {content}"
        )

    header = (
        f"<posts date='{label}' total='{total_raw}' shown='{len(posts)}'"
        f" keyword='{keyword or 'tất cả'}'>"
    )
    if truncated:
        header += f"\n<!-- Chỉ hiển thị {MAX_POSTS_PER_LLM}/{total_raw} bài -->"

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
    """Tạo schema. Thêm các cột mới nếu chưa có (safe migration)."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id          TEXT    UNIQUE NOT NULL,
                group_name       TEXT,
                group_url        TEXT,
                author           TEXT,
                content          TEXT,
                post_url         TEXT,
                timestamp        TEXT,
                source_type      TEXT DEFAULT 'page',
                likes            INTEGER DEFAULT 0,
                comments         INTEGER DEFAULT 0,
                shares           INTEGER DEFAULT 0,
                keywords         TEXT,
                relevance_label  TEXT DEFAULT 'khong_lien_quan',
                relevance_level  TEXT DEFAULT 'khong_lien_quan',
                topics_matched   TEXT DEFAULT '',
                summary          TEXT DEFAULT '',
                collected_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT NOT NULL,
                summary       TEXT,
                sent_at       TEXT,
                tg_message_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_posts_date   ON posts(collected_at);
            CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(date);
        """)

    # Safe migration: thêm cột mới nếu chưa tồn tại
    new_cols = [
        ("source_type",     "TEXT DEFAULT 'page'"),
        ("relevance_label", "TEXT DEFAULT 'khong_lien_quan'"),
        ("relevance_level", "TEXT DEFAULT 'khong_lien_quan'"),
        ("topics_matched",  "TEXT DEFAULT ''"),
        ("summary",         "TEXT DEFAULT ''"),
    ]
    with _get_conn() as conn:
        for col, defn in new_cols:
            try:
                conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {defn}")
            except Exception:
                pass  # Cột đã tồn tại

    # Tạo index cho các cột mới sau khi đã đảm bảo cột tồn tại
    with _get_conn() as conn:
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_rel ON posts(relevance_level)")
        except Exception as e:
            logger.warning(f"Could not create index idx_posts_rel: {e}")

    logger.info("✅ SQLite schema OK")



def upsert_posts(posts: List[dict]) -> int:
    """Insert bài vào SQLite (không có analysis). Backward compat."""
    return upsert_posts_with_analysis(posts, None)


def upsert_posts_with_analysis(posts: List[dict], analysis=None) -> int:
    """
    Upsert bài vào SQLite, kèm kết quả analysis nếu có.
    analysis: BatchAnalysisResult hoặc None.
    """
    if not posts:
        return 0

    # Build analysis lookup
    analysis_map: Dict[str, object] = {}
    if analysis and hasattr(analysis, "analyses"):
        for a in analysis.analyses:
            analysis_map[str(a.post_id)] = a

    now      = datetime.now().isoformat()
    inserted = 0

    with _get_conn() as conn:
        for p in posts:
            pid = (p.get("post_id") or "")[:200]
            a   = analysis_map.get(pid)

            rel_label = "khong_lien_quan"
            rel_level = "khong_lien_quan"
            topics_m  = ""
            summary   = ""

            if a:
                rel_label = a.relevance_level
                rel_level = a.relevance_level
                topics_m  = ", ".join(a.matched_topics or [])
                summary   = a.summary or ""

            cur = conn.execute(
                """INSERT OR IGNORE INTO posts
                   (post_id, group_name, group_url, author, content,
                    post_url, timestamp, source_type, likes, comments, shares,
                    keywords, relevance_label, relevance_level, topics_matched,
                    summary, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pid,
                    p.get("group_name", ""),
                    p.get("group_url", ""),
                    p.get("author", ""),
                    (p.get("content") or "")[:2000],
                    p.get("post_url", ""),
                    p.get("timestamp", ""),
                    p.get("source_type", "page"),
                    p.get("likes", 0),
                    p.get("comments", 0),
                    p.get("shares", 0),
                    ", ".join(p["keywords_matched"])
                    if isinstance(p.get("keywords_matched"), list) else "",
                    rel_label,
                    rel_level,
                    topics_m,
                    summary[:500],
                    now,
                ),
            )
            if cur.rowcount:
                inserted += 1
            elif a:
                # Cập nhật analysis cho bài đã tồn tại
                conn.execute(
                    """UPDATE posts SET
                       relevance_label=?, relevance_level=?, topics_matched=?, summary=?
                       WHERE post_id=?""",
                    (rel_label, rel_level, topics_m, summary[:500], pid),
                )

    logger.info(f"💾 SQLite: +{inserted} bài (bỏ {len(posts) - inserted} trùng)")
    return inserted


def save_report(summary: str, tg_message_id: str = "") -> int:
    """Lưu báo cáo vào SQLite. Trả về row id."""
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
        relevant = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE collected_at LIKE ? AND relevance_level != ?",
            (f"{today}%", "khong_lien_quan"),
        ).fetchone()[0]
        last = conn.execute(
            "SELECT sent_at FROM reports WHERE date=? ORDER BY id DESC LIMIT 1", (today,)
        ).fetchone()
    return {
        "total_posts_today": total,
        "relevant_today":    relevant,
        "last_report_at":    last[0] if last else None,
    }


def get_posts_for_dashboard(
    date_str:       Optional[str] = None,
    page_name:      Optional[str] = None,
    topic:          Optional[str] = None,
    relevant_only:  bool = False,
    limit:          int  = 100,
) -> List[dict]:
    """
    Lấy bài viết cho Dashboard với các bộ lọc:
    - date_str:      lọc theo ngày (YYYY-MM-DD), mặc định hôm nay
    - page_name:     lọc theo tên page/group
    - topic:         lọc theo chủ đề đã match
    - relevant_only: chỉ lấy bài liên quan
    - limit:         giới hạn số bài trả về
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    conditions = ["collected_at LIKE ?"]
    params: List = [f"{date_str}%"]

    if page_name:
        conditions.append("group_name LIKE ?")
        params.append(f"%{page_name}%")
    if topic:
        conditions.append("topics_matched LIKE ?")
        params.append(f"%{topic}%")
    if relevant_only:
        conditions.append("relevance_level != ?")
        params.append("khong_lien_quan")

    where = " AND ".join(conditions)
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""SELECT post_id, group_name, author, content, post_url,
                       timestamp, source_type, keywords, relevance_level,
                       topics_matched, summary, collected_at
                FROM posts WHERE {where}
                ORDER BY collected_at DESC LIMIT ?""",
            params,
        ).fetchall()

    return [dict(r) for r in rows]


def get_posts_by_day(days: int = 7) -> List[dict]:
    """Lấy số bài theo ngày trong N ngày gần nhất (cho chart Dashboard)."""
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT substr(collected_at, 1, 10) as day,
                      COUNT(*) as total,
                      SUM(CASE WHEN relevance_level != 'khong_lien_quan' THEN 1 ELSE 0 END) as relevant
               FROM posts
               GROUP BY day
               ORDER BY day DESC
               LIMIT ?""",
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_distinct_pages() -> List[str]:
    """Lấy danh sách tên page/group đã có trong DB."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT group_name FROM posts ORDER BY group_name"
        ).fetchall()
    return [r[0] for r in rows if r[0]]
