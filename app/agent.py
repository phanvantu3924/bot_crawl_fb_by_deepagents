"""
app/agent.py — Deep Agent Orchestrator.

Kiến trúc:
  ┌──────────────────────────────────────────────┐
  │          Orchestrator (DeepAgent)             │
  │  - Điều phối toàn bộ workflow                 │
  │  - Gọi các sub-agent tools theo thứ tự        │
  │  - Lưu memory vào AGENTS.md                   │
  └───────────┬──────────┬──────────┬─────────────┘
              │          │          │
    ┌─────────┘  ┌───────┘  ┌───────┘
    ▼            ▼          ▼
[Scraper]  [Analyzer]  [Reporter]
Sub-agent  Sub-agent   Sub-agent

Model: ollama/qwen3.5:35b via https://poc-ai.hawee.com.vn/ollama/v1
"""

import hashlib
import json
import logging
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

from .storage import (
    raw_posts_as_text,
    load_raw_posts,
    save_report,
    get_today_stats,
    upsert_posts_with_analysis,
)
from .sub_agents.analyzer import analyze_posts, BatchAnalysisResult
from .sub_agents.reporter import generate_report_content, ReportContent

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
AGENTS_MD = Path("AGENTS.md")
CACHE_DIR  = Path("data/cache")

# ── LLM config ────────────────────────────────────────────────────────────────
OLLAMA_MODEL    = "qwen3.5:35b"
OLLAMA_BASE_URL = "https://poc-ai.hawee.com.vn/ollama/v1"


def _create_llm(temperature: float = 0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        api_key="dummy",
        temperature=temperature,
    )


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_key(data: str) -> str:
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _load_cache(key: str) -> Optional[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Memory ────────────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    base = """\
Bạn là Facebook Page Monitoring Agent — công cụ tự động theo dõi và tổng hợp nội dung từ các Facebook Page.

## NHIỆM VỤ
1. Đọc dữ liệu bài viết đã thu thập hôm nay
2. Phân tích và lọc theo chủ đề quan tâm
3. Tạo báo cáo đầy đủ
4. Gửi báo cáo qua Telegram

## QUY TRÌNH BẮT BUỘC
1. Gọi `get_stats` — kiểm tra số bài hôm nay
2. Nếu có bài, gọi `run_analysis` — phân tích + tạo báo cáo
3. Gọi `send_telegram_report` — gửi báo cáo
4. Nếu có xu hướng đáng chú ý, gọi `update_memory`

## QUY TẮC
- KHÔNG bịa thông tin ngoài dữ liệu thực tế
- Luôn đảm bảo báo cáo được gửi dù có ít bài
- Xử lý lỗi gracefully, không dừng đột ngột
"""
    if AGENTS_MD.exists():
        memory = AGENTS_MD.read_text(encoding="utf-8").strip()
        if memory:
            base += f"\n\n## Bộ nhớ dài hạn (AGENTS.md)\n{memory}"
    return base


# ── Telegram sender ────────────────────────────────────────────────────────────

def _send_telegram(config: dict, html_text: str) -> str:
    """Gửi HTML lên Telegram theo chunks 4000 ký tự. Trả về message_id cuối."""
    token   = config.get("tg_token", "")
    chat_id = config.get("tg_chat_id", "")

    if not token or not chat_id:
        raise ValueError("Thiếu tg_token hoặc tg_chat_id trong config")

    header = (
        f"<b>📊 FACEBOOK PAGE MONITORING — "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}</b>\n\n"
    )
    full_text = header + html_text

    chunks, buf = [], ""
    for line in full_text.splitlines(keepends=True):
        if len(buf) + len(line) > 4000:
            chunks.append(buf)
            buf = line
        else:
            buf += line
    if buf:
        chunks.append(buf)

    last_msg_id = ""
    for chunk in chunks:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if not resp.ok:
            err = resp.json().get("description", resp.text)
            raise RuntimeError(f"Telegram lỗi: {err}")
        last_msg_id = str(resp.json().get("result", {}).get("message_id", ""))

    logger.info(f"✅ Đã gửi {len(chunks)} phần lên Telegram (msg_id: {last_msg_id})")
    return last_msg_id


# ── Tools cho Deep Agent ───────────────────────────────────────────────────────

def _make_tools(config: dict):
    """Tạo tool list cho Deep Agent orchestrator."""

    def get_stats() -> str:
        """Lấy thống kê nhanh: số bài hôm nay và lần gửi báo cáo cuối."""
        s = get_today_stats()
        return (
            f"Hôm nay thu thập được {s['total_posts_today']} bài.\n"
            f"Báo cáo cuối lúc: {s['last_report_at'] or 'Chưa gửi lần nào'}"
        )

    def run_analysis(keyword: Optional[str] = None) -> str:
        """
        Chạy pipeline đầy đủ: phân tích bài viết → tạo báo cáo → lưu file.
        keyword: (tùy chọn) lọc chỉ bài có từ khóa này.
        Trả về tóm tắt kết quả để agent biết trạng thái.
        """
        try:
            posts = load_raw_posts()
            if not posts:
                return "KHÔNG CÓ BÀI VIẾT — Chưa thu thập hoặc không có bài nào hôm nay."

            # Lấy topics từ config
            page_configs  = config.get("pages") or []
            global_topics = config.get("global_topics") or []
            all_topics: List[str] = list({
                t for pc in page_configs for t in (pc.get("topics") or [])
            } | set(global_topics))

            # Fallback nếu không cấu hình gì
            if not all_topics:
                all_topics = config.get("keywords") or ["Chưa phân loại"]

            if keyword:
                pattern = rf"(?i)(?<![a-zA-Z]){re.escape(keyword)}(?![a-zA-Z])"
                posts = [p for p in posts if re.search(pattern, p.get("content") or "")]
                if not posts:
                    return f"Không có bài nào khớp từ khóa '{keyword}'."

            # Cache check
            cache_key = _cache_key(json.dumps([p.get("post_id") for p in posts]) + str(all_topics))
            cached = _load_cache(cache_key)
            analysis: BatchAnalysisResult
            if cached:
                logger.info(" Cache hit — bỏ qua analyzer LLM call")
                from .sub_agents.analyzer import BatchAnalysisResult as BAR, PostAnalysis as PA
                analyses_data = cached.get("analyses", [])
                analysis = BAR(
                    analyses=[PA(**a) for a in analyses_data],
                    total_relevant=cached.get("total_relevant", 0),
                    insight=cached.get("insight"),
                )
            else:
                analysis = analyze_posts(posts, all_topics)
                _save_cache(cache_key, analysis.model_dump())

            # Cập nhật analysis vào storage
            upsert_posts_with_analysis(posts, analysis)

            # Tạo báo cáo
            report: ReportContent = generate_report_content(
                all_posts=posts,
                analysis=analysis,
                page_configs=page_configs,
                topics=all_topics,
            )

            # Lưu report vào bộ nhớ để send_telegram_report dùng
            _make_tools._last_report = report

            return (
                f"✅ Phân tích xong: {len(posts)} bài | {analysis.total_relevant} liên quan\n"
                f"Báo cáo: {report.report_date} | {report.relevant_count}/{report.total_posts} bài"
            )
        except Exception as e:
            logger.error(f"❌ run_analysis lỗi: {e}", exc_info=True)
            return f"❌ Lỗi khi phân tích: {e}"

    _make_tools._last_report = None

    def send_telegram_report() -> str:
        """
        Gửi báo cáo đã tạo lên Telegram và lưu vào SQLite.
        Phải gọi run_analysis trước.
        """
        report: Optional[ReportContent] = getattr(_make_tools, "_last_report", None)
        if not report:
            return "❌ Chưa có báo cáo — hãy gọi run_analysis trước."
        try:
            msg_id = _send_telegram(config, report.telegram_html)
            save_report(report.markdown, tg_message_id=msg_id)
            return f"✅ Đã gửi lên Telegram (msg_id: {msg_id}) và lưu SQLite."
        except Exception as e:
            logger.error(f"❌ Telegram lỗi: {e}")
            return f"❌ Gửi Telegram thất bại: {e}"

    def get_today_report_preview() -> str:
        """Xem trước nội dung báo cáo (không gửi). Hữu ích để kiểm tra trước khi gửi."""
        report: Optional[ReportContent] = getattr(_make_tools, "_last_report", None)
        if not report:
            return "Chưa có báo cáo — gọi run_analysis trước."
        return f"PREVIEW:\n{report.markdown[:2000]}..."

    def update_memory(note: str) -> str:
        """
        Ghi chú xu hướng vào AGENTS.md — bộ nhớ dài hạn.
        note: nội dung muốn ghi nhớ cho lần chạy tiếp theo.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## [{timestamp}]\n{note}\n"
        with AGENTS_MD.open("a", encoding="utf-8") as f:
            f.write(entry)
        return f"✅ Đã ghi nhớ vào AGENTS.md: {note[:80]}"

    return [get_stats, run_analysis, send_telegram_report,
            get_today_report_preview, update_memory]


# ── Public API ────────────────────────────────────────────────────────────────

def create_report_agent(config: dict):
    """Khởi tạo Deep Agent orchestrator với đầy đủ tools và memory."""
    model = _create_llm()
    return create_deep_agent(
        model=model,
        tools=_make_tools(config),
        system_prompt=_build_system_prompt(),
    )


def run_daily_report(config: dict, keyword: str = None) -> dict:
    """
    Entry point: chạy toàn bộ pipeline monitoring.

    Pipeline:
      1. Load bài viết từ JSON raw
      2. Sub-agent Analyzer: phân tích relevance
      3. Sub-agent Reporter: tạo báo cáo Markdown + HTML
      4. Gửi Telegram + lưu SQLite + cập nhật AGENTS.md

    Args:
        config:  Cấu hình từ config.json.
        keyword: Lọc chỉ bài có từ khóa này (optional).

    Returns:
        dict {success: bool, message: str, stats: dict}.
    """
    try:
        logger.info("🤖 [Orchestrator] Bắt đầu chạy daily report...")

        # ── Bước 1: Load data ──────────────────────────────────────────────────
        stats = get_today_stats()
        logger.info(f"📊 Có {stats['total_posts_today']} bài hôm nay")

        posts = load_raw_posts()
        if not posts:
            msg = "Hôm nay chưa có bài viết nào."
            logger.info(msg)
            try:
                _send_telegram(config, f"<i>{msg}</i>")
            except Exception:
                pass
            save_report(msg)
            return {"success": True, "message": msg, "stats": stats}

        # ── Bước 2: Topics từ config ───────────────────────────────────────────
        page_configs  = config.get("pages") or []
        global_topics = config.get("global_topics") or []
        all_topics: List[str] = list({
            t for pc in page_configs for t in (pc.get("topics") or [])
        } | set(global_topics))

        if not all_topics:
            all_topics = config.get("keywords") or ["Chưa phân loại"]

        # ── Bước 3: Filter by keyword nếu có ──────────────────────────────────
        filtered_posts = posts
        if keyword:
            pattern = rf"(?i)(?<![a-zA-Z]){re.escape(keyword)}(?![a-zA-Z])"
            filtered_posts = [p for p in posts if re.search(pattern, p.get("content") or "")]
            if not filtered_posts:
                msg = f"Không có bài nào về '{keyword}' hôm nay."
                _send_telegram(config, f"<i>{msg}</i>")
                return {"success": True, "message": msg, "stats": stats}

        # ── Bước 4: Cache check ───────────────────────────────────────────────
        cache_key = _cache_key(
            json.dumps([p.get("post_id") for p in filtered_posts]) + str(all_topics)
        )
        cached = _load_cache(cache_key)

        if cached:
            logger.info("✅ Cache hit — bỏ qua analyzer")
            from .sub_agents.analyzer import BatchAnalysisResult as BAR, PostAnalysis as PA
            analysis = BAR(
                analyses=[PA(**a) for a in cached.get("analyses", [])],
                total_relevant=cached.get("total_relevant", 0),
                insight=cached.get("insight"),
            )
        else:
            # ── Bước 5: Sub-agent Analyzer ────────────────────────────────────
            logger.info(f"🔍 [Analyzer sub-agent] Phân tích {len(filtered_posts)} bài...")
            analysis = analyze_posts(filtered_posts, all_topics)
            _save_cache(cache_key, analysis.model_dump())

        # Cập nhật DB với kết quả analysis
        upsert_posts_with_analysis(filtered_posts, analysis)

        # ── Bước 6: Sub-agent Reporter ─────────────────────────────────────────
        logger.info("📝 [Reporter sub-agent] Tạo báo cáo...")
        report: ReportContent = generate_report_content(
            all_posts    = filtered_posts,
            analysis     = analysis,
            page_configs = page_configs,
            topics       = all_topics,
        )

        # ── Bước 7: Gửi Telegram ──────────────────────────────────────────────
        msg_id = _send_telegram(config, report.telegram_html)
        save_report(report.markdown, tg_message_id=msg_id)

        # ── Bước 8: Update memory nếu có insight ─────────────────────────────
        if analysis.insight:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with AGENTS_MD.open("a", encoding="utf-8") as f:
                f.write(f"\n## [{timestamp}]\n{analysis.insight}\n")
            logger.info(f"🧠 Memory updated: {analysis.insight[:60]}")

        logger.info("✅ [Orchestrator] Pipeline hoàn thành")
        return {
            "success": True,
            "message": f"Báo cáo đã gửi — {report.relevant_count}/{report.total_posts} bài liên quan",
            "stats": {
                "total_posts":   report.total_posts,
                "relevant":      report.relevant_count,
                "topics":        all_topics,
                "tg_message_id": msg_id,
            },
        }

    except Exception as e:
        logger.error(f"❌ [Orchestrator] Lỗi: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
