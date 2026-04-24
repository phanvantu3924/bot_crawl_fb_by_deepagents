"""
sub_agents/analyzer.py — Sub-Agent phân tích nội dung bài viết.

Nhiệm vụ:
  - Nhận danh sách bài viết + danh sách chủ đề theo dõi
  - Phân loại từng bài: liên quan / không liên quan
  - Gán nhãn mức độ: cao / trung_binh / thap / khong_lien_quan
  - Tóm tắt nội dung từng bài liên quan

Sub-agent này được gọi bởi orchestrator agent cha như một tool.
Có fallback 3 tầng để đảm bảo luôn trả về kết quả.
"""

import json
import logging
import re
from typing import List, Dict, Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# ── Config LLM ─────────────────────────────────────────────────────────────────

OLLAMA_MODEL    = "qwen3.5:35b"
OLLAMA_BASE_URL = "https://poc-ai.hawee.com.vn/ollama/v1"


def _create_llm(temperature: float = 0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        api_key="dummy",
        temperature=temperature,
    )


# ── Pydantic Schema ────────────────────────────────────────────────────────────

class PostAnalysis(BaseModel):
    """Kết quả phân tích một bài viết."""
    post_id:         str            = Field(description="ID hoặc index của bài viết")
    is_relevant:     bool           = Field(description="Có liên quan đến chủ đề theo dõi không")
    relevance_level: str            = Field(
        description="Mức độ liên quan: cao | trung_binh | thap | khong_lien_quan"
    )
    matched_topics:  List[str]      = Field(default_factory=list, description="Các chủ đề khớp")
    summary:         str            = Field(description="Tóm tắt nội dung bài viết, tối đa 120 ký tự")

    @property
    def relevance_label(self) -> str:
        """Nhãn hiển thị thân thiện."""
        return {
            "cao":             "🔴 Liên quan - CAO",
            "trung_binh":      "🟡 Liên quan - TRUNG BÌNH",
            "thap":            "🟢 Liên quan - THẤP",
            "khong_lien_quan": "⚪ Không liên quan",
        }.get(self.relevance_level, "⚪ Không xác định")


class BatchAnalysisResult(BaseModel):
    """Kết quả phân tích toàn bộ batch bài viết."""
    analyses:       List[PostAnalysis] = Field(default_factory=list)
    total_relevant: int                = Field(default=0)
    insight:        Optional[str]      = Field(
        default=None,
        description="Nhận xét nhanh về xu hướng nội dung (1-2 câu từ data thực tế)"
    )


# ── Synonyms map ──────────────────────────────────────────────────────────────

# Đã xóa bỏ TOPIC_SYNONYMS hardcode. Việc đối chiếu từ khóa giờ đây phụ thuộc hoàn toàn vào
# cấu hình global_topics của người dùng và hướng dẫn trong AGENTS.md.
TOPIC_SYNONYMS: Dict[str, List[str]] = {}


def _keyword_match_fallback(posts: List[Dict], topics: List[str]) -> BatchAnalysisResult:
    """
    Fallback thuần keyword nếu LLM không khả dụng.
    Kiểm tra từ khóa + từ đồng nghĩa trong nội dung bài viết.
    """
    analyses = []
    for p in posts:
        content = (p.get("content") or "").lower()
        matched = []
        for topic in topics:
            synonyms = [topic.lower()] + [s.lower() for s in TOPIC_SYNONYMS.get(topic, [])]
            for syn in synonyms:
                pattern = rf"(?i)(?<![a-zA-Z]){re.escape(syn)}(?![a-zA-Z])"
                if re.search(pattern, content):
                    matched.append(topic)
                    break

        match_count = len(matched)
        if match_count == 0:
            level = "khong_lien_quan"
        elif match_count >= 3 or any(t.lower() in content[:100] for t in matched):
            level = "cao"
        elif match_count >= 2:
            level = "trung_binh"
        else:
            level = "thap"

        raw_content = (p.get("content") or "")
        if not isinstance(raw_content, str):
            raw_content = ""
        # Làm sạch: bỏ newline thừa, giữ tối đa 120 ký tự
        clean_summary = " ".join(raw_content.split())[:120].strip()
        analyses.append(PostAnalysis(
            post_id         = str(p.get("post_id", "")),
            is_relevant     = match_count > 0,
            relevance_level = level,
            matched_topics  = matched,
            summary         = clean_summary,
        ))

    total_relevant = sum(1 for a in analyses if a.is_relevant)
    return BatchAnalysisResult(analyses=analyses, total_relevant=total_relevant)


# ── System Prompt ──────────────────────────────────────────────────────────────

def _get_system_prompt() -> str:
    import os
    agents_context = ""
    if os.path.exists("AGENTS.md"):
        with open("AGENTS.md", "r", encoding="utf-8") as f:
            agents_context = f.read().strip()
            
    return f"""\
Bạn là sub-agent phân tích nội dung mạng xã hội.

## NHIỆM VỤ CHÍNH
Phân tích danh sách bài viết và đánh giá mức độ liên quan với các chủ đề theo dõi.

## QUY TẮC BẮT BUỘC
1. CHỈ dùng thông tin có trong nội dung bài viết — KHÔNG suy đoán, KHÔNG bịa.
2. Nếu bài viết quá ngắn hoặc không rõ ràng → is_relevant = false, level = khong_lien_quan.
3. Tóm tắt PHẢI phản ánh đúng nội dung, tối đa 120 ký tự.
4. Khi đánh giá mức độ:
   - cao: bài chủ yếu bàn về chủ đề, có nhiều thông tin hữu ích
   - trung_binh: bài đề cập chủ đề nhưng không phải nội dung chính
   - thap: bài chỉ thoáng đề cập
   - khong_lien_quan: không liên quan gì

## NGỮ CẢNH TỪ NGƯỜI DÙNG (AGENTS.md)
{agents_context}
"""

def analyze_posts(posts: List[Dict], topics: List[str]) -> BatchAnalysisResult:
    """
    Sub-agent phân tích danh sách bài viết với danh sách chủ đề.

    Args:
        posts:  Danh sách bài viết dạng dict (có keys: post_id, content, group_name, author).
        topics: Danh sách chủ đề cần theo dõi, ví dụ ['QA', 'ERP', 'AI'].

    Returns:
        BatchAnalysisResult với từng bài được gán nhãn relevance.
    """
    if not posts:
        return BatchAnalysisResult()

    logger.info(f"🔍 [Analyzer] Phân tích {len(posts)} bài với topics: {topics}")

    # ── Build posts text ──────────────────────────────────────────────────────
    posts_text = "\n\n---\n\n".join(
        f"POST_ID: {p.get('post_id', f'post_{i}')}\n"
        f"Page/Nhóm: {p.get('group_name', '?')}\n"
        f"Tác giả: {p.get('author', '?')}\n"
        f"Nội dung: {(p.get('content') or '')[:400]}"
        for i, p in enumerate(posts)
    )

    # Nếu chỉ có "Chưa phân loại", ta không ép LLM phải theo chủ đề này mà để nó tự đọc AGENTS.md
    topics_str = ", ".join(topics)
    if topics == ["Chưa phân loại"] or not topics:
        topics_str = "Tự động trích xuất từ file AGENTS.md (Nếu bài viết khớp với ngữ cảnh trong AGENTS.md thì is_relevant = true, topic = tên chủ đề tương ứng)."

    prompt = (
        f"{_get_system_prompt()}\n\n"
        f"## CHỦ ĐỀ CẦN THEO DÕI\n{topics_str}\n\n"
        f"## BÀI VIẾT\n{posts_text}\n\n"
        "Trả về JSON hợp lệ theo schema BatchAnalysisResult. "
        "Đảm bảo mỗi bài có đúng post_id như trên."
    )

    llm = _create_llm()

    # ── Tầng 1: Structured output ─────────────────────────────────────────────
    try:
        structured_llm = llm.with_structured_output(BatchAnalysisResult)
        result: BatchAnalysisResult = structured_llm.invoke(prompt)
        result.total_relevant = sum(1 for a in result.analyses if a.is_relevant)
        logger.info(f"✅ [Analyzer] Structured output OK — {result.total_relevant}/{len(posts)} liên quan")
        return result
    except Exception as e:
        logger.warning(f"⚠️ [Analyzer] Structured output thất bại: {e} — thử JSON parse")

    # ── Tầng 2: JSON parse từ text response ───────────────────────────────────
    try:
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        # Tìm JSON object đầu tiên trong response
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            data   = json.loads(json_match.group())
            result = BatchAnalysisResult(**data)
            result.total_relevant = sum(1 for a in result.analyses if a.is_relevant)
            logger.info(f"✅ [Analyzer] JSON parse OK — {result.total_relevant}/{len(posts)} liên quan")
            return result
    except Exception as e:
        logger.warning(f"⚠️ [Analyzer] JSON parse thất bại: {e} — dùng keyword fallback")

    # ── Tầng 3: Keyword fallback ──────────────────────────────────────────────
    result = _keyword_match_fallback(posts, topics)
    logger.info(f"✅ [Analyzer] Keyword fallback — {result.total_relevant}/{len(posts)} liên quan")
    return result
