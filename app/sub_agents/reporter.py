"""
sub_agents/reporter.py — Sub-Agent tạo báo cáo.

Nhiệm vụ:
  - Nhận kết quả phân tích + metadata bài viết
  - Tạo báo cáo theo đúng format yêu cầu (docx mục 4.4):
      1. Tổng số bài trong ngày
      2. Khung giờ đăng (bài đầu → bài cuối)
      3. Danh sách bài liên quan (có tóm tắt + nhãn mức độ)
      4. Danh sách toàn bộ bài
  - Xuất cả Markdown file (lưu local) và HTML (gửi Telegram)

Sub-agent này được gọi bởi orchestrator agent cha.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .analyzer import BatchAnalysisResult, PostAnalysis

logger = logging.getLogger(__name__)

OLLAMA_MODEL    = "qwen3.5:35b"
OLLAMA_BASE_URL = "https://poc-ai.hawee.com.vn/ollama/v1"

REPORTS_DIR = Path("data/reports")


# ── Schemas ────────────────────────────────────────────────────────────────────

@dataclass
class ReportContent:
    """Kết quả báo cáo đầy đủ từ sub-agent."""
    markdown:     str      # Nội dung markdown để lưu file
    telegram_html: str     # Nội dung HTML để gửi Telegram
    summary:      str      # Tóm tắt 1-2 câu
    total_posts:  int
    relevant_count: int
    report_date:  str


class ReportSummary(BaseModel):
    """LLM sinh ra phần nhận xét tổng hợp."""
    summary: str = Field(description="2-3 câu tổng kết xu hướng, CHỈ từ data thực tế")
    highlights: List[str] = Field(
        default_factory=list,
        description="Tối đa 3 điểm nổi bật từ các bài liên quan"
    )


# ── Helper: format time ────────────────────────────────────────────────────────

def _fmt_time(ts: Optional[str]) -> str:
    """Chuyển ISO timestamp → HH:MM."""
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M")
    except Exception:
        return ts[:5] if len(ts) >= 5 else ts


def _fmt_datetime(ts: Optional[str]) -> str:
    """Chuyển ISO timestamp → DD/MM HH:MM."""
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return ts


# ── Core generator ─────────────────────────────────────────────────────────────

def _get_time_range(posts: List[Dict]) -> tuple[str, str]:
    """Lấy khung giờ đăng bài: (sớm nhất, muộn nhất)."""
    timestamps = [p.get("timestamp") for p in posts if p.get("timestamp")]
    if not timestamps:
        return ("?", "?")
    timestamps.sort()
    return (_fmt_time(timestamps[0]), _fmt_time(timestamps[-1]))


def _generate_ai_summary(relevant_posts: List[Dict], topics: List[str]) -> str:
    """Dùng LLM tạo nhận xét tổng hợp ngắn từ các bài liên quan."""
    if not relevant_posts:
        return "Hôm nay không có bài viết liên quan đến các chủ đề theo dõi."

    llm = ChatOpenAI(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        api_key="dummy",
        temperature=0.2,
    )

    posts_text = "\n".join(
        f"- [{p.get('relevance_level', '?')}] {p.get('summary', p.get('content', '')[:100])}"
        for p in relevant_posts[:20]
    )

    prompt = (
        "Bạn là trợ lý tóm tắt nội dung mạng xã hội.\n\n"
        f"Chủ đề theo dõi: {', '.join(topics)}\n\n"
        f"Bài liên quan hôm nay:\n{posts_text}\n\n"
        "Viết 2-3 câu nhận xét tổng hợp xu hướng nội dung từ các bài trên. "
        "CHỈ dùng thông tin có trong danh sách, không bịa thêm. "
        "Trả về CHỈ đoạn văn nhận xét, không tiêu đề, không giải thích."
    )

    try:
        resp = llm.invoke(prompt)
        return resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
    except Exception as e:
        logger.warning(f"⚠️ [Reporter] AI summary thất bại: {e}")
        topics_str = ", ".join(topics)
        return (
            f"Hôm nay có {len(relevant_posts)} bài liên quan đến {topics_str}. "
            "Vui lòng xem chi tiết danh sách bên dưới."
        )


# ── Markdown builder ───────────────────────────────────────────────────────────

def _build_markdown(
    all_posts:       List[Dict],
    analysis_map:    Dict[str, PostAnalysis],
    page_configs:    List[Dict],
    topics:          List[str],
    ai_summary:      str,
    report_date:     str,
    time_start:      str,
    time_end:        str,
) -> str:
    relevant = [p for p in all_posts if analysis_map.get(str(p.get("post_id")), None)
                and analysis_map[str(p.get("post_id"))].is_relevant]

    lines = [
        f"# 📊 BÁO CÁO FACEBOOK PAGE MONITORING",
        f"",
        f"**Ngày:** {report_date}",
        f"**Tạo lúc:** {datetime.now().strftime('%H:%M')}",
        f"**Pages theo dõi:** {len(page_configs)}",
        f"**Chủ đề:** {', '.join(topics)}",
        f"",
        "---",
        "",
        "## 📈 TỔNG QUAN",
        f"| Chỉ số | Giá trị |",
        f"|--------|---------|",
        f"| Tổng số bài trong ngày | **{len(all_posts)}** |",
        f"| Khung giờ đăng | **{time_start} → {time_end}** |",
        f"| Bài liên quan | **{len(relevant)}/{len(all_posts)}** |",
        "",
        "---",
        "",
        "## 🔍 NHẬN XÉT TỔNG HỢP",
        ai_summary,
        "",
        "---",
        "",
        "## ✅ DANH SÁCH BÀI LIÊN QUAN",
        "",
    ]

    if relevant:
        for p in relevant:
            a = analysis_map.get(str(p.get("post_id")))
            level_badge = {
                "cao":        "🔴 CAO",
                "trung_binh": "🟡 TRUNG BÌNH",
                "thap":       "🟢 THẤP",
            }.get(a.relevance_level if a else "", "⚪")

            lines += [
                f"### {_fmt_datetime(p.get('timestamp'))} — {p.get('group_name', '?')}",
                f"- **Mức độ liên quan:** {level_badge}",
                f"- **Chủ đề khớp:** {', '.join(a.matched_topics) if a else '—'}",
                f"- **Tác giả:** {p.get('author', '?')}",
                f"- **Tóm tắt:** {a.summary if a else (p.get('content') or '')[:120]}",
                f"- **Link:** {p.get('post_url') or '_(không có link)_'}",
                "",
            ]
    else:
        lines.append("_Không có bài viết liên quan hôm nay._\n")

    lines += [
        "---",
        "",
        "## 📋 DANH SÁCH TOÀN BỘ BÀI VIẾT",
        "",
    ]

    for i, p in enumerate(all_posts, 1):
        a = analysis_map.get(str(p.get("post_id")))
        tag = ""
        if a:
            tag = {
                "cao":             " ✅ **Liên quan - CAO**",
                "trung_binh":      " ✅ Liên quan - TRUNG BÌNH",
                "thap":            " 🔅 Liên quan - THẤP",
                "khong_lien_quan": " _(Không liên quan)_",
            }.get(a.relevance_level, "")

        content_preview = (p.get("content") or "")[:80].replace("\n", " ")
        lines.append(
            f"{i}. [{_fmt_time(p.get('timestamp'))}] **{p.get('group_name', '?')}** "
            f"— {p.get('author', '?')} — {content_preview}...{tag}"
        )

    lines.append("")
    lines.append(f"---\n_Báo cáo tự động bởi Facebook Page Monitoring Agent_")

    return "\n".join(lines)


# ── Telegram HTML builder ──────────────────────────────────────────────────────

def _build_telegram_html(
    all_posts:    List[Dict],
    analysis_map: Dict[str, PostAnalysis],
    topics:       List[str],
    ai_summary:   str,
    report_date:  str,
    time_start:   str,
    time_end:     str,
) -> str:
    relevant = [p for p in all_posts if analysis_map.get(str(p.get("post_id")), None)
                and analysis_map[str(p.get("post_id"))].is_relevant]

    lines = [
        f"<b>📊 BÁO CÁO NGÀY {report_date}</b>",
        "",
        f"🗓 Khung giờ: <b>{time_start} → {time_end}</b>",
        f"📌 Tổng bài: <b>{len(all_posts)}</b>  |  Liên quan: <b>{len(relevant)}</b>",
        f"🏷 Chủ đề: {', '.join(topics)}",
        "",
        "─────────────────────",
        "",
        "<b>📈 NHẬN XÉT</b>",
        ai_summary,
        "",
        "─────────────────────",
        "",
        f"<b>✅ BÀI LIÊN QUAN ({len(relevant)} bài)</b>",
        "",
    ]

    if relevant:
        for p in relevant:
            a = analysis_map.get(str(p.get("post_id")))
            level_emoji = {
                "cao":        "🔴",
                "trung_binh": "🟡",
                "thap":       "🟢",
            }.get(a.relevance_level if a else "", "⚪")
            topics_str = ", ".join(a.matched_topics) if a else "—"
            # Đảm bảo summary luôn là string (tránh lỗi lặp ký tự khi content là list/None)
            raw_summary = (a.summary if a else None) or ""
            if not isinstance(raw_summary, str):
                raw_summary = str(raw_summary)
            if not raw_summary.strip():
                raw_content = p.get("content") or ""
                raw_summary = raw_content[:100] if isinstance(raw_content, str) else ""
            summary_text = raw_summary.replace("<", "&lt;").replace(">", "&gt;")
            link_part = f'\n  🔗 <a href="{p.get("post_url")}">Xem bài</a>' if p.get("post_url") else ""

            lines += [
                f"{level_emoji} <b>[{p.get('group_name', '?')}]</b> {_fmt_datetime(p.get('timestamp'))}",
                f"  📌 Chủ đề: <i>{topics_str}</i>",
                f"  📝 {summary_text}{link_part}",
                "",
            ]
    else:
        lines.append("Không có bài liên quan hôm nay.\n")

    lines += [
        "─────────────────────",
        "",
        f"<b>📋 TẤT CẢ {len(all_posts)} BÀI</b>",
        "",
    ]

    for i, p in enumerate(all_posts, 1):
        a = analysis_map.get(str(p.get("post_id")))
        tag = ""
        if a and a.is_relevant:
            tag = " ✅"
        content_preview = (p.get("content") or "")[:60].replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(
            f"{i}. [{_fmt_time(p.get('timestamp'))}] <b>{p.get('group_name', '?')}</b> "
            f"— {content_preview}...{tag}"
        )

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_report_content(
    all_posts:    List[Dict],
    analysis:     BatchAnalysisResult,
    page_configs: List[Dict],
    topics:       List[str],
) -> ReportContent:
    """
    Sub-agent tạo nội dung báo cáo đầy đủ.

    Args:
        all_posts:    Toàn bộ bài viết thu thập được trong ngày.
        analysis:     Kết quả phân tích từ analyzer sub-agent.
        page_configs: Cấu hình các pages theo dõi.
        topics:       Danh sách chủ đề tổng hợp.

    Returns:
        ReportContent gồm markdown + telegram_html + metadata.
    """
    logger.info(f"📝 [Reporter] Tạo báo cáo: {len(all_posts)} bài, {analysis.total_relevant} liên quan")

    report_date = datetime.now().strftime("%d/%m/%Y")

    # Map analysis theo post_id
    analysis_map: Dict[str, PostAnalysis] = {a.post_id: a for a in analysis.analyses}

    # Lấy khung giờ
    time_start, time_end = _get_time_range(all_posts)

    # Các bài liên quan với analysis gắn vào
    relevant_posts_with_analysis = []
    for p in all_posts:
        pid = str(p.get("post_id", ""))
        a = analysis_map.get(pid)
        if a and a.is_relevant:
            enriched = dict(p)
            enriched["relevance_level"] = a.relevance_level
            enriched["summary"] = a.summary
            enriched["matched_topics"] = a.matched_topics
            relevant_posts_with_analysis.append(enriched)

    # AI summary
    ai_summary = _generate_ai_summary(relevant_posts_with_analysis, topics)

    # Build outputs
    markdown = _build_markdown(
        all_posts, analysis_map, page_configs,
        topics, ai_summary, report_date, time_start, time_end
    )
    tg_html = _build_telegram_html(
        all_posts, analysis_map, topics,
        ai_summary, report_date, time_start, time_end
    )

    # Lưu markdown local
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    md_path   = REPORTS_DIR / f"{date_str}.md"
    md_path.write_text(markdown, encoding="utf-8")
    logger.info(f"💾 [Reporter] Đã lưu báo cáo: {md_path}")

    return ReportContent(
        markdown      = markdown,
        telegram_html = tg_html,
        summary       = ai_summary,
        total_posts   = len(all_posts),
        relevant_count= analysis.total_relevant,
        report_date   = report_date,
    )
